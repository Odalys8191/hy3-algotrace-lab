"""OpenAI-compatible Hy3 adapter with a credential-free immutable response cache."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import NoReturn, TypeVar, cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ValidationError

from .contracts import (
    ErrorTaxonomy,
    ProblemOracle,
    ProblemRecord,
    ReviewerVerdict,
    SolutionTrace,
)
from .prompts import (
    ADVERSARIAL_REVIEW_PROMPT_VERSION,
    ADVERSARIAL_REVIEW_SYSTEM_PROMPT,
    ARBITER_PROMPT_VERSION,
    ARBITER_SYSTEM_PROMPT,
    GENERATOR_PROMPT_VERSION,
    GENERATOR_SYSTEM_PROMPT,
    LOGIC_REVIEW_PROMPT_VERSION,
    LOGIC_REVIEW_SYSTEM_PROMPT,
    SCHEMA_REPAIR_PROMPT,
)

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
TRANSIENT_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Structural JSON-schema keywords the endpoint grammar compiler handles
# correctly. Validation keywords such as minLength are dropped before the
# schema is sent: TokenHub hy3's constrained decoding mangles newline
# escapes inside string values whenever the schema contains them
# (observed 2026-09-09, reproduced with minimal probes). All semantic
# constraints stay enforced client-side by pydantic validation instead.
_STRUCTURE_ONLY_SCHEMA_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "additionalProperties",
        "allOf",
        "anyOf",
        "const",
        "description",
        "enum",
        "items",
        "oneOf",
        "prefixItems",
        "properties",
        "required",
        "title",
        "type",
    }
)


def sanitize_json_schema(schema: object) -> object:
    """Return a copy of ``schema`` without non-structural validation keywords.

    Keeps the document a valid structural JSON schema so the endpoint can
    constrain output shape, while length, pattern, and numeric bounds are
    left to the client-side pydantic validation that already owns them.
    Keys of ``properties`` and ``$defs`` mappings are field identifiers, not
    schema keywords, so their entries are preserved and recursed into.
    """

    if isinstance(schema, list):
        return [sanitize_json_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    sanitized = {key: value for key, value in schema.items() if key in _STRUCTURE_ONLY_SCHEMA_KEYS}
    for mapping_key in ("properties", "$defs"):
        mapping = sanitized.get(mapping_key)
        if isinstance(mapping, dict):
            sanitized[mapping_key] = {
                name: sanitize_json_schema(sub) for name, sub in mapping.items()
            }
    schema_containers = ("items", "prefixItems", "additionalProperties", "anyOf", "oneOf", "allOf")
    for container_key in schema_containers:
        if container_key in sanitized:
            sanitized[container_key] = sanitize_json_schema(sanitized[container_key])
    return sanitized


class Hy3Error(RuntimeError):
    """Base error for failures at the external model boundary."""


class Hy3ConfigurationError(Hy3Error):
    """Raised when required endpoint configuration is unavailable."""


class Hy3ResponseError(Hy3Error):
    """Raised when Hy3 returns an unusable response."""

    def __init__(
        self,
        message: str,
        *,
        error_taxonomy: ErrorTaxonomy | None = None,
        diagnostic: Hy3FailureDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.error_taxonomy = error_taxonomy
        self.diagnostic = diagnostic


class Hy3SpendLimitError(Hy3Error):
    """Raised before transmission when the configured RMB cap cannot cover an attempt."""


class Hy3TokenLimitError(Hy3Error):
    """Raised before transmission when the configured token quota cannot cover an attempt."""


@dataclass(frozen=True, slots=True)
class _CostReservation:
    upper_bound_rmb: Decimal


@dataclass(frozen=True, slots=True)
class _CostState:
    charged_attempt_upper_bound_rmb: Decimal
    charged_upper_bound_rmb: Decimal
    remaining_upper_bound_rmb: Decimal


@dataclass(frozen=True, slots=True)
class _TokenReservation:
    upper_bound_tokens: int


@dataclass(frozen=True, slots=True)
class _TokenState:
    charged_attempt_upper_bound_tokens: int
    charged_upper_bound_tokens: int
    remaining_upper_bound_tokens: int


@dataclass(frozen=True, slots=True)
class Hy3Usage:
    """Strict allowlist of provider usage fields safe for diagnostic persistence."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Hy3ValidationIssue:
    """Sanitized validation location and fixed diagnostic code."""

    path: str
    code: str


@dataclass(frozen=True, slots=True)
class Hy3FailureDiagnostic:
    """Credential- and response-free terminal failure metadata."""

    category: str
    reviewer: str | None = None
    validation_issues: tuple[Hy3ValidationIssue, ...] = ()
    http_status: int | None = None
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Hy3AttemptOutcome:
    """Whitelisted settlement metadata emitted exactly once per HTTP attempt."""

    sequence: int | None
    context: Hy3AttemptContext
    category: str
    http_status: int | None
    finish_reason: str | None
    usage: Hy3Usage | None
    usage_status: str
    charged_attempt_upper_bound_rmb: str | None
    charged_upper_bound_rmb: str | None
    remaining_upper_bound_rmb: str | None
    charged_attempt_upper_bound_tokens: int | None
    charged_upper_bound_tokens: int | None
    remaining_upper_bound_tokens: int | None
    validation_issues: tuple[Hy3ValidationIssue, ...] = ()


class RmbCostGuard:
    """Conservatively reserve TokenHub spend before every HTTP attempt.

    The request UTF-8 byte count is an upper bound on tokenizer input tokens.
    Missing or malformed provider usage keeps the full reservation charged, so
    timeouts and non-standard responses cannot silently reopen the budget.
    """

    _MILLION = Decimal(1_000_000)
    _INPUT_RMB_PER_MILLION = Decimal(1)
    _OUTPUT_RMB_PER_MILLION = Decimal(4)
    _PROTOCOL_INPUT_TOKEN_MARGIN = 4096

    def __init__(
        self,
        *,
        limit_rmb: str,
        max_output_tokens: int,
        initial_charged_upper_bound_rmb: str = "0",
    ) -> None:
        try:
            limit = Decimal(limit_rmb)
            initial_charged = Decimal(initial_charged_upper_bound_rmb)
        except InvalidOperation:
            raise ValueError("RMB spend cap must be a finite positive decimal") from None
        if not limit.is_finite() or limit <= 0:
            raise ValueError("RMB spend cap must be a finite positive decimal")
        if not initial_charged.is_finite() or initial_charged < 0 or initial_charged > limit:
            raise ValueError("initial RMB charge must be finite and within the spend cap")
        if isinstance(max_output_tokens, bool) or max_output_tokens < 1:
            raise ValueError("max output tokens must be a positive integer")
        self._limit = limit
        self._max_output_tokens = max_output_tokens
        self._charged = initial_charged
        self._lock = threading.Lock()

    @property
    def charged_upper_bound_rmb(self) -> float:
        with self._lock:
            return float(self._charged)

    @property
    def remaining_upper_bound_rmb(self) -> float:
        with self._lock:
            return float(self._limit - self._charged)

    @property
    def limit_rmb(self) -> float:
        return float(self._limit)

    def reserve(self, payload: object) -> _CostReservation:
        request_bytes = len(_canonical_json(payload).encode("utf-8"))
        input_upper = request_bytes + self._PROTOCOL_INPUT_TOKEN_MARGIN
        upper = (
            Decimal(input_upper) * self._INPUT_RMB_PER_MILLION
            + Decimal(self._max_output_tokens) * self._OUTPUT_RMB_PER_MILLION
        ) / self._MILLION
        with self._lock:
            if self._charged + upper > self._limit:
                raise Hy3SpendLimitError("TokenHub RMB spend cap exhausted")
            self._charged += upper
        return _CostReservation(upper_bound_rmb=upper)

    def cancel(self, reservation: _CostReservation) -> None:
        with self._lock:
            self._charged -= reservation.upper_bound_rmb

    def reservation_state(self, reservation: _CostReservation) -> _CostState:
        with self._lock:
            charged = self._charged
        return _CostState(
            charged_attempt_upper_bound_rmb=reservation.upper_bound_rmb,
            charged_upper_bound_rmb=charged,
            remaining_upper_bound_rmb=self._limit - charged,
        )

    def settle(
        self,
        reservation: _CostReservation,
        usage: Hy3Usage | None,
    ) -> _CostState:
        actual = reservation.upper_bound_rmb
        if usage is not None:
            actual = (
                Decimal(usage.prompt_tokens) * self._INPUT_RMB_PER_MILLION
                + Decimal(usage.completion_tokens) * self._OUTPUT_RMB_PER_MILLION
            ) / self._MILLION
        # Never let a malformed endpoint report release more than the amount
        # conservatively reserved for this attempt.
        actual = min(actual, reservation.upper_bound_rmb)
        with self._lock:
            self._charged -= reservation.upper_bound_rmb - actual
            charged = self._charged
        return _CostState(
            charged_attempt_upper_bound_rmb=actual,
            charged_upper_bound_rmb=charged,
            remaining_upper_bound_rmb=self._limit - charged,
        )


class TokenQuotaGuard:
    """Reserve a conservative total-token upper bound before every HTTP attempt."""

    _PROTOCOL_INPUT_TOKEN_MARGIN = 4096

    def __init__(
        self,
        *,
        limit_tokens: int,
        max_output_tokens: int,
        initial_charged_upper_bound_tokens: int = 0,
    ) -> None:
        values = (limit_tokens, max_output_tokens, initial_charged_upper_bound_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("token quota values must be integers")
        if limit_tokens < 1 or max_output_tokens < 1:
            raise ValueError("token quota and max output must be positive")
        if not 0 <= initial_charged_upper_bound_tokens <= limit_tokens:
            raise ValueError("initial token charge must be within the token quota")
        self._limit = limit_tokens
        self._max_output_tokens = max_output_tokens
        self._charged = initial_charged_upper_bound_tokens
        self._lock = threading.Lock()

    @property
    def limit_tokens(self) -> int:
        return self._limit

    @property
    def charged_upper_bound_tokens(self) -> int:
        with self._lock:
            return self._charged

    @property
    def remaining_upper_bound_tokens(self) -> int:
        with self._lock:
            return self._limit - self._charged

    def reserve(self, payload: object) -> _TokenReservation:
        request_bytes = len(_canonical_json(payload).encode("utf-8"))
        upper = request_bytes + self._PROTOCOL_INPUT_TOKEN_MARGIN + self._max_output_tokens
        with self._lock:
            if self._charged + upper > self._limit:
                raise Hy3TokenLimitError("TokenHub token quota exhausted")
            self._charged += upper
        return _TokenReservation(upper_bound_tokens=upper)

    def cancel(self, reservation: _TokenReservation) -> None:
        with self._lock:
            self._charged -= reservation.upper_bound_tokens

    def reservation_state(self, reservation: _TokenReservation) -> _TokenState:
        with self._lock:
            charged = self._charged
        return _TokenState(
            charged_attempt_upper_bound_tokens=reservation.upper_bound_tokens,
            charged_upper_bound_tokens=charged,
            remaining_upper_bound_tokens=self._limit - charged,
        )

    def settle(self, reservation: _TokenReservation, usage: Hy3Usage | None) -> _TokenState:
        actual = reservation.upper_bound_tokens
        if usage is not None:
            reported_total = usage.prompt_tokens + usage.completion_tokens
            if usage.total_tokens is not None:
                reported_total = max(reported_total, usage.total_tokens)
            actual = min(reported_total, reservation.upper_bound_tokens)
        with self._lock:
            self._charged -= reservation.upper_bound_tokens - actual
            charged = self._charged
        return _TokenState(
            charged_attempt_upper_bound_tokens=actual,
            charged_upper_bound_tokens=charged,
            remaining_upper_bound_tokens=self._limit - charged,
        )


@dataclass(frozen=True, slots=True)
class _SafeFailure:
    message: str
    error_taxonomy: ErrorTaxonomy | None = None
    diagnostic: Hy3FailureDiagnostic | None = None


@dataclass(frozen=True, slots=True)
class Hy3AttemptContext:
    """Credential-free metadata emitted immediately before one HTTP attempt."""

    operation: str
    phase: str
    retry_number: int
    reviewer: str | None = None
    reservation_upper_bound_rmb: str | None = None
    charged_upper_bound_rmb: str | None = None
    remaining_upper_bound_rmb: str | None = None
    reservation_upper_bound_tokens: int | None = None
    charged_upper_bound_tokens: int | None = None
    remaining_upper_bound_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class _CompletionResult:
    content: object
    sequence: int | None
    context: Hy3AttemptContext
    http_status: int
    finish_reason: str | None
    usage: Hy3Usage | None
    cost_state: _CostState | None
    token_state: _TokenState | None


@dataclass(frozen=True, slots=True)
class Hy3Config:
    """Environment-backed connection settings; the API key is excluded from repr."""

    base_url: str
    api_key: str = field(repr=False)
    model: str = "hy3"
    max_attempts: int = 3
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise Hy3ConfigurationError("HY3_BASE_URL must be set")
        if not self.api_key:
            raise Hy3ConfigurationError("HY3_API_KEY must be set")
        if self.max_attempts < 1:
            raise Hy3ConfigurationError("max_attempts must be positive")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise Hy3ConfigurationError("timeout_seconds must be finite and positive")

    @classmethod
    def from_env(cls) -> Hy3Config:
        try:
            timeout_seconds = float(os.environ.get("HY3_TIMEOUT_SECONDS", "60"))
        except ValueError:
            timeout_seconds = float("nan")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise Hy3ConfigurationError("timeout_seconds must be finite and positive")
        base_url = os.environ.get("HY3_BASE_URL", "")
        api_key = os.environ.get("HY3_API_KEY", "")
        model = os.environ.get("HY3_MODEL", "hy3")
        return cls(base_url=base_url, api_key=api_key, model=model, timeout_seconds=timeout_seconds)


def endpoint_identity(endpoint: str) -> str:
    """Return a stable endpoint identity with user-info, query, and fragment removed."""

    parsed = urlsplit(endpoint)
    if not parsed.scheme or parsed.hostname is None:
        raise Hy3ConfigurationError("HY3_BASE_URL must be an absolute URL")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc.lower(), path, "", ""))


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _allowed_step_ids_instruction(trace: SolutionTrace) -> str:
    step_ids = [step.step_id for step in trace.steps]
    return f"Allowed trace step IDs: {_canonical_json(step_ids)}"


_SAFE_FINISH_REASONS = frozenset(
    {"stop", "length", "content_filter", "tool_calls", "function_call"}
)
_SAFE_VALIDATION_FIELDS = frozenset(
    {
        "schema_version",
        "trace_id",
        "problem_id",
        "language",
        "steps",
        "step_id",
        "step_number",
        "stage",
        "claim",
        "rationale",
        "depends_on",
        "status",
        "problem_understanding",
        "algorithm",
        "correctness_argument",
        "time_complexity",
        "space_complexity",
        "edge_cases",
        "code",
        "reviewer_id",
        "material_error",
        "error_taxonomy",
        "first_error_step_id",
        "explanation",
        "per_step_reviews",
        "material",
        "taxonomy",
        "evidence",
        "confidence",
    }
)
_SAFE_VALIDATION_CODES = frozenset(
    {
        "bool_type",
        "enum",
        "extra_forbidden",
        "finite_number",
        "float_parsing",
        "float_type",
        "greater_than_equal",
        "int_parsing",
        "int_type",
        "less_than_equal",
        "list_type",
        "literal_error",
        "missing",
        "model_type",
        "string_too_short",
        "string_type",
        "tuple_type",
        "value_error",
    }
)


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _usage_from_document(document: object) -> Hy3Usage | None:
    if not isinstance(document, Mapping) or not isinstance(document.get("usage"), Mapping):
        return None
    usage = document["usage"]
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    total_tokens = usage.get("total_tokens")
    if (
        isinstance(prompt_tokens, bool)
        or isinstance(completion_tokens, bool)
        or not isinstance(prompt_tokens, int)
        or not isinstance(completion_tokens, int)
        or prompt_tokens < 0
        or completion_tokens < 0
        or (
            total_tokens is not None
            and (
                isinstance(total_tokens, bool)
                or not isinstance(total_tokens, int)
                or total_tokens < 0
            )
        )
    ):
        return None
    return Hy3Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def _finish_reason_from_document(document: object) -> str | None:
    try:
        if not isinstance(document, Mapping):
            return None
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            return None
        reason = choices[0].get("finish_reason")
    except (IndexError, TypeError):  # pragma: no cover - defensive against exotic mappings
        return None
    if reason is None:
        return None
    return reason if isinstance(reason, str) and reason in _SAFE_FINISH_REASONS else "other"


def _validation_issues(error: BaseException) -> tuple[Hy3ValidationIssue, ...]:
    if isinstance(error, json.JSONDecodeError):
        return (Hy3ValidationIssue(path="$", code="json_invalid"),)
    if isinstance(error, ValidationError):
        issues: list[Hy3ValidationIssue] = []
        for item in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        ):
            safe_segments = []
            for segment in item.get("loc", ()):
                if isinstance(segment, int):
                    safe_segments.append("[]")
                elif isinstance(segment, str) and segment in _SAFE_VALIDATION_FIELDS:
                    safe_segments.append(segment)
                else:
                    safe_segments.append("*")
            error_type = item.get("type")
            issues.append(
                Hy3ValidationIssue(
                    path=".".join(safe_segments) or "$",
                    code=error_type
                    if isinstance(error_type, str) and error_type in _SAFE_VALIDATION_CODES
                    else "other",
                )
            )
        return tuple(issues) or (Hy3ValidationIssue(path="$", code="other"),)
    if isinstance(error, TypeError):
        return (Hy3ValidationIssue(path="$", code="type_error"),)
    return (Hy3ValidationIssue(path="$", code="value_error"),)


def _accept_result(_result: BaseModel) -> None:
    """Replace context-bearing validators before raising a public safe failure."""


def _raise_safe_failure(
    message: str,
    error_taxonomy: ErrorTaxonomy | None,
    diagnostic: Hy3FailureDiagnostic | None,
) -> NoReturn:
    """Publish a sanitized error from a frame with no client or transport state."""

    raise Hy3ResponseError(
        message,
        error_taxonomy=error_taxonomy,
        diagnostic=diagnostic,
    )


def build_cache_key(
    *,
    model: str,
    endpoint: str,
    prompt_version: str,
    parameters: Mapping[str, object],
    canonical_input: object,
) -> str:
    """Hash every behavior-affecting request field except credentials."""

    material = {
        "model": model,
        "endpoint": endpoint_identity(endpoint),
        "prompt_version": prompt_version,
        "parameters": dict(parameters),
        "input": canonical_input,
    }
    return hashlib.sha256(_canonical_json(material).encode()).hexdigest()


class JsonResponseCache:
    """Small create-only JSON cache local to the model adapter."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def _path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("cache key must be a lowercase SHA-256 digest")
        return self._directory / f"{key}.json"

    def get(self, key: str) -> object | None:
        path = self._path(key)
        try:
            return cast(object, json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return None

    def put(self, key: str, value: object) -> bool:
        """Atomically publish a value only if the key does not exist."""

        self._directory.mkdir(parents=True, exist_ok=True)
        target = self._path(key)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=self._directory,
            prefix=f".{key}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(_canonical_json(value))
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)


def generation_input(problem: ProblemRecord) -> dict[str, object]:
    """Build the model-visible problem input, deliberately excluding private evidence."""

    return {
        "problem_id": problem.problem_id,
        "title": problem.title,
        "statement_en": problem.statement_en,
        "language": problem.language,
        "time_limit_ms": problem.time_limit_ms,
        "memory_limit_mb": problem.memory_limit_mb,
        "public_tests": [test.model_dump(mode="json") for test in problem.public_tests],
    }


class Hy3Client:
    """Validate structured Hy3 outputs while keeping HTTP as the only external boundary."""

    def __init__(
        self,
        config: Hy3Config,
        *,
        cache: JsonResponseCache | None = None,
        transport: httpx.BaseTransport | None = None,
        attempt_observer: Callable[[Hy3AttemptContext], int | None] | None = None,
        attempt_outcome_observer: Callable[[Hy3AttemptOutcome], None] | None = None,
        parameters: Mapping[str, object] | None = None,
        cost_guard: RmbCostGuard | None = None,
        token_guard: TokenQuotaGuard | None = None,
    ) -> None:
        # The exact same detached scalar mapping drives both cache identity and HTTP.
        # Explicit parameters have no implicit defaults; historical callers retain high.
        chosen = dict(parameters) if parameters is not None else {"reasoning_effort": "high"}
        allowed = {
            "reasoning_effort",
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "top_p",
            "top_k",
            "seed",
            "presence_penalty",
            "frequency_penalty",
        }
        if any(
            name not in allowed
            or not isinstance(value, (str, int, float, bool, type(None)))
            or (isinstance(value, float) and not math.isfinite(value))
            for name, value in chosen.items()
        ):
            raise Hy3ConfigurationError("unsupported or invalid model parameter")
        self._parameters = chosen
        self._config = config
        self._cache = cache
        self._attempt_observer = attempt_observer
        self._attempt_outcome_observer = attempt_outcome_observer
        self._cost_guard = cost_guard
        self._token_guard = token_guard
        if cost_guard is not None:
            max_tokens = chosen.get("max_tokens")
            if max_tokens != cost_guard._max_output_tokens:
                raise Hy3ConfigurationError("cost guard requires the matching frozen max_tokens")
        if token_guard is not None:
            max_tokens = chosen.get("max_tokens")
            if max_tokens != token_guard._max_output_tokens:
                raise Hy3ConfigurationError("token guard requires the matching frozen max_tokens")
        self._http = httpx.Client(
            transport=transport,
            timeout=config.timeout_seconds,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    def close(self) -> None:
        self._http.close()

    def generate(self, problem: ProblemRecord, *, trace_id: str | None = None) -> SolutionTrace:
        visible_input = generation_input(problem)
        if trace_id is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", trace_id):
                raise ValueError("reserved trace ID must be a safe sample identity")
            visible_input = visible_input | {"trace_id": trace_id}

        def validate_trace(result: SolutionTrace) -> None:
            self._validate_trace_identity(result, problem_id=problem.problem_id)
            if trace_id is not None and result.trace_id != trace_id:
                raise Hy3ResponseError(
                    "generated trace ID does not match the reserved sample",
                    error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                    diagnostic=Hy3FailureDiagnostic(
                        category="validation_error",
                        reviewer="generator",
                        validation_issues=(
                            Hy3ValidationIssue(path="trace_id", code="identity_mismatch"),
                        ),
                    ),
                )

        outcome = self._structured_call(
            output_model=SolutionTrace,
            prompt_version=GENERATOR_PROMPT_VERSION,
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            canonical_input=visible_input,
            user_payload=visible_input,
            validate_result=validate_trace,
            reviewer="generator",
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            diagnostic = outcome.diagnostic
            del outcome, visible_input, problem, self
            _raise_safe_failure(message, error_taxonomy, diagnostic)
        return outcome

    def review(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        *,
        reviewer_id: str,
    ) -> ReviewerVerdict:
        # The oracle is available to local deterministic fusion only.  Remote
        # reviewers must reason from the public problem and supplied trace.
        del oracle
        if reviewer_id == "logic-reviewer":
            prompt_version = LOGIC_REVIEW_PROMPT_VERSION
            system_prompt = LOGIC_REVIEW_SYSTEM_PROMPT
        elif reviewer_id == "adversarial-reviewer":
            prompt_version = ADVERSARIAL_REVIEW_PROMPT_VERSION
            system_prompt = ADVERSARIAL_REVIEW_SYSTEM_PROMPT
        else:
            raise ValueError("reviewer_id must identify one of the two isolated reviewers")
        review_payload = {
            "reviewer_id": reviewer_id,
            "problem": generation_input(problem),
            "trace": trace.model_dump(mode="json"),
        }
        step_ids_instruction = _allowed_step_ids_instruction(trace)
        outcome = self._structured_call(
            output_model=ReviewerVerdict,
            prompt_version=prompt_version,
            system_prompt=f"{system_prompt}\n{step_ids_instruction}\n",
            canonical_input=review_payload,
            user_payload=review_payload,
            validate_result=lambda result: self._validate_verdict_identity(
                result, reviewer_id=reviewer_id, trace=trace
            ),
            reviewer=reviewer_id,
            repair_instruction=step_ids_instruction,
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            diagnostic = outcome.diagnostic
            del outcome, review_payload, problem, trace, self
            _raise_safe_failure(message, error_taxonomy, diagnostic)
        return outcome

    def arbitrate(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        primary: tuple[ReviewerVerdict, ReviewerVerdict],
    ) -> ReviewerVerdict:
        del oracle
        payload = {
            "reviewer_id": "arbiter",
            "problem": generation_input(problem),
            "trace": trace.model_dump(mode="json"),
            "primary_verdicts": [verdict.model_dump(mode="json") for verdict in primary],
        }
        step_ids_instruction = _allowed_step_ids_instruction(trace)
        outcome = self._structured_call(
            output_model=ReviewerVerdict,
            prompt_version=ARBITER_PROMPT_VERSION,
            system_prompt=f"{ARBITER_SYSTEM_PROMPT}\n{step_ids_instruction}\n",
            canonical_input=payload,
            user_payload=payload,
            validate_result=lambda result: self._validate_verdict_identity(
                result, reviewer_id="arbiter", trace=trace
            ),
            reviewer="arbiter",
            repair_instruction=step_ids_instruction,
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            diagnostic = outcome.diagnostic
            del outcome, payload, problem, trace, primary, self
            _raise_safe_failure(message, error_taxonomy, diagnostic)
        return outcome

    @staticmethod
    def _validate_trace_identity(trace: SolutionTrace, *, problem_id: str) -> None:
        if trace.problem_id != problem_id:
            raise Hy3ResponseError(
                "generation response problem identity does not match request",
                error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                diagnostic=Hy3FailureDiagnostic(
                    category="validation_error",
                    reviewer="generator",
                    validation_issues=(
                        Hy3ValidationIssue(path="problem_id", code="identity_mismatch"),
                    ),
                ),
            )

    @staticmethod
    def _validate_verdict_identity(
        verdict: ReviewerVerdict, *, reviewer_id: str, trace: SolutionTrace
    ) -> None:
        if verdict.reviewer_id != reviewer_id:
            raise Hy3ResponseError(
                "review response identity does not match its request",
                error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                diagnostic=Hy3FailureDiagnostic(
                    category="validation_error",
                    reviewer=reviewer_id,
                    validation_issues=(
                        Hy3ValidationIssue(path="reviewer_id", code="identity_mismatch"),
                    ),
                ),
            )
        if verdict.trace_id != trace.trace_id:
            raise Hy3ResponseError(
                "review response identity does not match its request",
                error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                diagnostic=Hy3FailureDiagnostic(
                    category="validation_error",
                    reviewer=reviewer_id,
                    validation_issues=(
                        Hy3ValidationIssue(path="trace_id", code="identity_mismatch"),
                    ),
                ),
            )
        known_steps = {step.step_id for step in trace.steps}
        reviewed_step_ids = tuple(review.step_id for review in verdict.per_step_reviews)
        reviewed_steps = set(reviewed_step_ids)
        if not reviewed_steps <= known_steps:
            raise Hy3ResponseError(
                "review response references an unknown trace step",
                error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                diagnostic=Hy3FailureDiagnostic(
                    category="validation_error",
                    reviewer=reviewer_id,
                    validation_issues=(
                        Hy3ValidationIssue(path="per_step_reviews", code="unknown_step_id"),
                    ),
                ),
            )
        if len(reviewed_step_ids) != len(known_steps) or reviewed_steps != known_steps:
            raise Hy3ResponseError(
                "review response must cover every trace step exactly once",
                error_taxonomy=ErrorTaxonomy.FORMAT_SCHEMA,
                diagnostic=Hy3FailureDiagnostic(
                    category="validation_error",
                    reviewer=reviewer_id,
                    validation_issues=(
                        Hy3ValidationIssue(
                            path="per_step_reviews",
                            code="step_coverage_mismatch",
                        ),
                    ),
                ),
            )

    def _structured_call(
        self,
        *,
        output_model: type[StructuredModel],
        prompt_version: str,
        system_prompt: str,
        canonical_input: object,
        user_payload: object,
        validate_result: Callable[[StructuredModel], None],
        reviewer: str,
        repair_instruction: str = "",
    ) -> StructuredModel | _SafeFailure:
        parameters = self._parameters
        key = build_cache_key(
            model=self._config.model,
            endpoint=self._config.base_url,
            prompt_version=prompt_version,
            parameters=parameters,
            canonical_input=canonical_input,
        )
        result, failure = self._obtain_validated_result(
            key=key,
            output_model=output_model,
            operation=prompt_version,
            system_prompt=system_prompt,
            user_payload=user_payload,
            validate_result=validate_result,
            reviewer=reviewer,
            repair_instruction=repair_instruction,
        )
        if failure is not None:
            system_prompt = ""
            canonical_input = None
            user_payload = None
            validate_result = _accept_result
            return failure
        if result is None:  # pragma: no cover - private outcome invariant
            return _SafeFailure("Hy3 response validation produced no result")
        if self._cache is not None:
            self._cache.put(key, result.model_dump(mode="json"))
        return result

    def _obtain_validated_result(
        self,
        *,
        key: str,
        output_model: type[StructuredModel],
        operation: str,
        system_prompt: str,
        user_payload: object,
        validate_result: Callable[[StructuredModel], None],
        reviewer: str,
        repair_instruction: str,
    ) -> tuple[StructuredModel | None, _SafeFailure | None]:
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                try:
                    cached_result = output_model.model_validate(cached)
                    self._ensure_secret_free(cached_result)
                    validate_result(cached_result)
                except Hy3ResponseError as error:
                    return None, self._safe_failure(error)
                except (ValidationError, TypeError, ValueError) as error:
                    return None, _SafeFailure(
                        self._redact(f"cached response failed schema validation: {error}"),
                        ErrorTaxonomy.FORMAT_SCHEMA,
                    )
                return cached_result, None

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _canonical_json(user_payload)},
        ]
        try:
            first_completion = self._completion(
                messages,
                output_model,
                operation=operation,
                phase="request",
                reviewer=reviewer,
            )
        except Hy3ResponseError as error:
            return None, self._safe_failure(error)
        first_result, first_error = self._validate_completion(
            first_completion,
            output_model=output_model,
            validate_result=validate_result,
            reviewer=reviewer,
        )
        if first_result is not None:
            return first_result, None
        assert first_error is not None
        if isinstance(first_error, Hy3ResponseError) and (
            first_error.diagnostic is None or first_error.diagnostic.category != "validation_error"
        ):
            return None, self._safe_failure(first_error)

        safe_content = self._content_text(self._redact_value(first_completion.content))
        safe_validation_error = self._redact(str(first_error))
        repair_messages = [
            *[
                {"role": message["role"], "content": self._redact(message["content"])}
                for message in messages
            ],
            {"role": "assistant", "content": safe_content},
            {
                "role": "user",
                "content": (
                    f"{SCHEMA_REPAIR_PROMPT}\n{repair_instruction}\n"
                    f"Validation error: {safe_validation_error}"
                ),
            },
        ]
        try:
            repaired_completion = self._completion(
                repair_messages,
                output_model,
                operation=operation,
                phase="schema_repair",
                reviewer=reviewer,
            )
        except Hy3ResponseError as error:
            return None, self._safe_failure(error)
        repaired_result, repaired_error = self._validate_completion(
            repaired_completion,
            output_model=output_model,
            validate_result=validate_result,
            reviewer=reviewer,
        )
        if repaired_result is not None:
            return repaired_result, None
        assert repaired_error is not None
        if isinstance(repaired_error, Hy3ResponseError):
            return None, self._safe_failure(repaired_error)
        issues = _validation_issues(repaired_error)
        return None, _SafeFailure(
            self._redact(f"response failed schema validation after one repair: {repaired_error}"),
            ErrorTaxonomy.FORMAT_SCHEMA,
            Hy3FailureDiagnostic(
                category="validation_error",
                reviewer=reviewer,
                validation_issues=issues,
                http_status=repaired_completion.http_status,
                finish_reason=repaired_completion.finish_reason,
            ),
        )

    def _validate_completion(
        self,
        completion: _CompletionResult,
        *,
        output_model: type[StructuredModel],
        validate_result: Callable[[StructuredModel], None],
        reviewer: str,
    ) -> tuple[StructuredModel | None, BaseException | None]:
        try:
            result = self._validate_content(completion.content, output_model)
            self._ensure_secret_free(result)
            validate_result(result)
        except Hy3ResponseError as error:
            diagnostic = error.diagnostic
            category = diagnostic.category if diagnostic is not None else "response_secret"
            issues = diagnostic.validation_issues if diagnostic is not None else ()
            self._emit_attempt_outcome(completion, category=category, issues=issues)
            return None, Hy3ResponseError(
                self._redact(str(error)),
                error_taxonomy=error.error_taxonomy,
                diagnostic=Hy3FailureDiagnostic(
                    category=category,
                    reviewer=diagnostic.reviewer if diagnostic is not None else reviewer,
                    validation_issues=issues,
                    http_status=completion.http_status,
                    finish_reason=completion.finish_reason,
                ),
            )
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
            self._emit_attempt_outcome(
                completion,
                category="validation_error",
                issues=_validation_issues(error),
            )
            return None, error
        self._emit_attempt_outcome(completion, category="accepted")
        return result, None

    def _safe_failure(self, error: Hy3ResponseError) -> _SafeFailure:
        return _SafeFailure(
            self._redact(str(error)),
            error.error_taxonomy,
            error.diagnostic,
        )

    def _completion(
        self,
        messages: list[dict[str, str]],
        output_model: type[BaseModel],
        *,
        operation: str,
        phase: str,
        reviewer: str,
    ) -> _CompletionResult:
        payload = {
            "model": self._config.model,
            **self._parameters,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": sanitize_json_schema(output_model.model_json_schema()),
                },
            },
        }
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        terminal_error: Hy3ResponseError | None = None
        cost_guard = self._cost_guard
        token_guard = self._token_guard
        for attempt in range(self._config.max_attempts):
            reservation = cost_guard.reserve(payload) if cost_guard else None
            try:
                token_reservation = token_guard.reserve(payload) if token_guard else None
            except Exception:
                if reservation is not None:
                    assert cost_guard is not None
                    cost_guard.cancel(reservation)
                raise
            reservation_state = (
                cost_guard.reservation_state(reservation)
                if cost_guard is not None and reservation is not None
                else None
            )
            token_reservation_state = (
                token_guard.reservation_state(token_reservation)
                if token_guard is not None and token_reservation is not None
                else None
            )
            context = Hy3AttemptContext(
                operation=operation,
                phase=phase,
                retry_number=attempt + 1,
                reviewer=reviewer,
                reservation_upper_bound_rmb=_decimal_text(reservation.upper_bound_rmb)
                if reservation is not None
                else None,
                charged_upper_bound_rmb=_decimal_text(reservation_state.charged_upper_bound_rmb)
                if reservation_state is not None
                else None,
                remaining_upper_bound_rmb=_decimal_text(reservation_state.remaining_upper_bound_rmb)
                if reservation_state is not None
                else None,
                reservation_upper_bound_tokens=(
                    token_reservation.upper_bound_tokens if token_reservation is not None else None
                ),
                charged_upper_bound_tokens=(
                    token_reservation_state.charged_upper_bound_tokens
                    if token_reservation_state is not None
                    else None
                ),
                remaining_upper_bound_tokens=(
                    token_reservation_state.remaining_upper_bound_tokens
                    if token_reservation_state is not None
                    else None
                ),
            )
            sequence: int | None = None
            try:
                if self._attempt_observer is not None:
                    sequence = self._attempt_observer(context)
            except Exception:
                if reservation is not None:
                    assert cost_guard is not None
                    cost_guard.cancel(reservation)
                if token_reservation is not None:
                    assert token_guard is not None
                    token_guard.cancel(token_reservation)
                raise
            try:
                response = self._http.post(url, json=payload)
            except httpx.TransportError as error:
                self._emit_attempt_outcome_values(
                    sequence=sequence,
                    context=context,
                    category="transport_error",
                    http_status=None,
                    finish_reason=None,
                    usage=None,
                    cost_state=reservation_state,
                    token_state=token_reservation_state,
                )
                if attempt + 1 < self._config.max_attempts:
                    continue
                terminal_error = Hy3ResponseError(
                    self._redact(f"Hy3 transport failure: {error}"),
                    diagnostic=Hy3FailureDiagnostic(
                        category="transport_error",
                        reviewer=reviewer,
                    ),
                )
                break
            try:
                response_document: object = response.json()
            except json.JSONDecodeError:
                response_document = None
            usage = _usage_from_document(response_document)
            finish_reason = _finish_reason_from_document(response_document)
            cost_state = (
                cost_guard.settle(reservation, usage)
                if cost_guard is not None and reservation is not None
                else None
            )
            token_state = (
                token_guard.settle(token_reservation, usage)
                if token_guard is not None and token_reservation is not None
                else None
            )
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt + 1 < self._config.max_attempts:
                    self._emit_attempt_outcome_values(
                        sequence=sequence,
                        context=context,
                        category="retryable_http",
                        http_status=response.status_code,
                        finish_reason=finish_reason,
                        usage=usage,
                        cost_state=cost_state,
                        token_state=token_state,
                    )
                    continue
            if response.is_error:
                self._emit_attempt_outcome_values(
                    sequence=sequence,
                    context=context,
                    category="http_error",
                    http_status=response.status_code,
                    finish_reason=finish_reason,
                    usage=usage,
                    cost_state=cost_state,
                    token_state=token_state,
                )
                raise Hy3ResponseError(
                    self._redact(f"Hy3 HTTP {response.status_code}: {response.text}"),
                    diagnostic=Hy3FailureDiagnostic(
                        category="http_error",
                        reviewer=reviewer,
                        http_status=response.status_code,
                        finish_reason=finish_reason,
                    ),
                )
            try:
                if not isinstance(response_document, Mapping):
                    raise TypeError("response envelope must be an object")
                document = response_document
                content = document["choices"][0]["message"]["content"]
                return _CompletionResult(
                    content=content,
                    sequence=sequence,
                    context=context,
                    http_status=response.status_code,
                    finish_reason=finish_reason,
                    usage=usage,
                    cost_state=cost_state,
                    token_state=token_state,
                )
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                self._emit_attempt_outcome_values(
                    sequence=sequence,
                    context=context,
                    category="invalid_envelope",
                    http_status=response.status_code,
                    finish_reason=finish_reason,
                    usage=usage,
                    cost_state=cost_state,
                    token_state=token_state,
                )
                terminal_error = Hy3ResponseError(
                    self._redact(f"invalid OpenAI-compatible response envelope: {error}"),
                    diagnostic=Hy3FailureDiagnostic(
                        category="invalid_envelope",
                        reviewer=reviewer,
                        http_status=response.status_code,
                        finish_reason=finish_reason,
                    ),
                )
                break
        if terminal_error is not None:
            raise terminal_error
        raise Hy3ResponseError("Hy3 request exhausted retries")

    def _emit_attempt_outcome(
        self,
        completion: _CompletionResult,
        *,
        category: str,
        issues: tuple[Hy3ValidationIssue, ...] = (),
    ) -> None:
        self._emit_attempt_outcome_values(
            sequence=completion.sequence,
            context=completion.context,
            category=category,
            http_status=completion.http_status,
            finish_reason=completion.finish_reason,
            usage=completion.usage,
            cost_state=completion.cost_state,
            token_state=completion.token_state,
            issues=issues,
        )

    def _emit_attempt_outcome_values(
        self,
        *,
        sequence: int | None,
        context: Hy3AttemptContext,
        category: str,
        http_status: int | None,
        finish_reason: str | None,
        usage: Hy3Usage | None,
        cost_state: _CostState | None,
        token_state: _TokenState | None = None,
        issues: tuple[Hy3ValidationIssue, ...] = (),
    ) -> None:
        if self._attempt_outcome_observer is None:
            return
        self._attempt_outcome_observer(
            Hy3AttemptOutcome(
                sequence=sequence,
                context=context,
                category=category,
                http_status=http_status,
                finish_reason=finish_reason,
                usage=usage,
                usage_status="reported" if usage is not None else "missing_or_invalid",
                charged_attempt_upper_bound_rmb=_decimal_text(
                    cost_state.charged_attempt_upper_bound_rmb
                )
                if cost_state is not None
                else None,
                charged_upper_bound_rmb=_decimal_text(cost_state.charged_upper_bound_rmb)
                if cost_state is not None
                else None,
                remaining_upper_bound_rmb=_decimal_text(cost_state.remaining_upper_bound_rmb)
                if cost_state is not None
                else None,
                charged_attempt_upper_bound_tokens=(
                    token_state.charged_attempt_upper_bound_tokens
                    if token_state is not None
                    else None
                ),
                charged_upper_bound_tokens=(
                    token_state.charged_upper_bound_tokens if token_state is not None else None
                ),
                remaining_upper_bound_tokens=(
                    token_state.remaining_upper_bound_tokens if token_state is not None else None
                ),
                validation_issues=issues,
            )
        )

    @staticmethod
    def _content_text(content: object) -> str:
        if isinstance(content, str):
            return content
        return _canonical_json(content)

    @staticmethod
    def _validate_content(content: object, output_model: type[StructuredModel]) -> StructuredModel:
        payload = json.loads(content) if isinstance(content, str) else content
        return output_model.model_validate(payload)

    def _redact(self, message: str) -> str:
        sanitized = message.replace(self._config.api_key, "[REDACTED]")
        sanitized = re.sub(
            r"(?i)(authorization|bearer|api[_-]?key)(\s*[:=]?\s*)[^\s,;\"']+",
            r"\1\2[REDACTED]",
            sanitized,
        )
        return sanitized

    def _redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._redact(value)
        if isinstance(value, Mapping):
            return {
                self._redact(key) if isinstance(key, str) else key: self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(item) for item in value)
        return value

    def _ensure_secret_free(self, value: BaseModel) -> None:
        if self._contains_secret(value.model_dump(mode="python")):
            raise Hy3ResponseError("Hy3 response contained configured credentials")

    def _contains_secret(self, value: object) -> bool:
        if isinstance(value, str):
            return self._config.api_key in value
        if isinstance(value, Mapping):
            return any(
                self._contains_secret(key) or self._contains_secret(item)
                for key, item in value.items()
            )
        if isinstance(value, (list, tuple)):
            return any(self._contains_secret(item) for item in value)
        return False
