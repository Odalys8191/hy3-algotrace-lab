"""OpenAI-compatible Hy3 adapter with a credential-free immutable response cache."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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
    ) -> None:
        super().__init__(message)
        self.error_taxonomy = error_taxonomy


@dataclass(frozen=True, slots=True)
class _SafeFailure:
    message: str
    error_taxonomy: ErrorTaxonomy | None = None


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

    @classmethod
    def from_env(cls) -> Hy3Config:
        base_url = os.environ.get("HY3_BASE_URL", "")
        api_key = os.environ.get("HY3_API_KEY", "")
        model = os.environ.get("HY3_MODEL", "hy3")
        return cls(base_url=base_url, api_key=api_key, model=model)


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


def _accept_result(_result: BaseModel) -> None:
    """Replace context-bearing validators before raising a public safe failure."""


def _raise_safe_failure(
    message: str, error_taxonomy: ErrorTaxonomy | None
) -> NoReturn:
    """Publish a sanitized error from a frame with no client or transport state."""

    raise Hy3ResponseError(message, error_taxonomy=error_taxonomy)


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
    ) -> None:
        self._config = config
        self._cache = cache
        self._http = httpx.Client(
            transport=transport,
            timeout=config.timeout_seconds,
            headers={"Authorization": f"Bearer {config.api_key}"},
        )

    def close(self) -> None:
        self._http.close()

    def generate(self, problem: ProblemRecord) -> SolutionTrace:
        visible_input = generation_input(problem)
        outcome = self._structured_call(
            output_model=SolutionTrace,
            prompt_version=GENERATOR_PROMPT_VERSION,
            system_prompt=GENERATOR_SYSTEM_PROMPT,
            canonical_input=visible_input,
            user_payload=visible_input,
            validate_result=lambda result: self._validate_trace_identity(
                result, problem_id=problem.problem_id
            ),
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            del outcome, visible_input, problem, self
            _raise_safe_failure(message, error_taxonomy)
        return outcome

    def review(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        *,
        reviewer_id: str,
    ) -> ReviewerVerdict:
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
            "oracle": oracle.model_dump(mode="json"),
            "trace": trace.model_dump(mode="json"),
        }
        outcome = self._structured_call(
            output_model=ReviewerVerdict,
            prompt_version=prompt_version,
            system_prompt=system_prompt,
            canonical_input=review_payload,
            user_payload=review_payload,
            validate_result=lambda result: self._validate_verdict_identity(
                result, reviewer_id=reviewer_id, trace=trace
            ),
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            del outcome, review_payload, problem, oracle, trace, self
            _raise_safe_failure(message, error_taxonomy)
        return outcome

    def arbitrate(
        self,
        problem: ProblemRecord,
        oracle: ProblemOracle,
        trace: SolutionTrace,
        primary: tuple[ReviewerVerdict, ReviewerVerdict],
    ) -> ReviewerVerdict:
        payload = {
            "reviewer_id": "arbiter",
            "problem": generation_input(problem),
            "oracle": oracle.model_dump(mode="json"),
            "trace": trace.model_dump(mode="json"),
            "primary_verdicts": [verdict.model_dump(mode="json") for verdict in primary],
        }
        outcome = self._structured_call(
            output_model=ReviewerVerdict,
            prompt_version=ARBITER_PROMPT_VERSION,
            system_prompt=ARBITER_SYSTEM_PROMPT,
            canonical_input=payload,
            user_payload=payload,
            validate_result=lambda result: self._validate_verdict_identity(
                result, reviewer_id="arbiter", trace=trace
            ),
        )
        if isinstance(outcome, _SafeFailure):
            message = outcome.message
            error_taxonomy = outcome.error_taxonomy
            del outcome, payload, problem, oracle, trace, primary, self
            _raise_safe_failure(message, error_taxonomy)
        return outcome

    @staticmethod
    def _validate_trace_identity(trace: SolutionTrace, *, problem_id: str) -> None:
        if trace.problem_id != problem_id:
            raise Hy3ResponseError("generation response problem identity does not match request")

    @staticmethod
    def _validate_verdict_identity(
        verdict: ReviewerVerdict, *, reviewer_id: str, trace: SolutionTrace
    ) -> None:
        if verdict.reviewer_id != reviewer_id or verdict.trace_id != trace.trace_id:
            raise Hy3ResponseError("review response identity does not match its request")
        known_steps = {step.step_id for step in trace.steps}
        reviewed_step_ids = tuple(review.step_id for review in verdict.per_step_reviews)
        reviewed_steps = set(reviewed_step_ids)
        if not reviewed_steps <= known_steps:
            raise Hy3ResponseError("review response references an unknown trace step")
        if len(reviewed_step_ids) != len(known_steps) or reviewed_steps != known_steps:
            raise Hy3ResponseError("review response must cover every trace step exactly once")

    def _structured_call(
        self,
        *,
        output_model: type[StructuredModel],
        prompt_version: str,
        system_prompt: str,
        canonical_input: object,
        user_payload: object,
        validate_result: Callable[[StructuredModel], None],
    ) -> StructuredModel | _SafeFailure:
        parameters: dict[str, object] = {"reasoning_effort": "high"}
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
            system_prompt=system_prompt,
            user_payload=user_payload,
            validate_result=validate_result,
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
        system_prompt: str,
        user_payload: object,
        validate_result: Callable[[StructuredModel], None],
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
            first_content = self._completion(messages, output_model)
        except Hy3ResponseError as error:
            return None, self._safe_failure(error)
        try:
            result = self._validate_content(first_content, output_model)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as first_error:
            safe_content = self._content_text(self._redact_value(first_content))
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
                        f"{SCHEMA_REPAIR_PROMPT}\n"
                        f"Validation error: {safe_validation_error}"
                    ),
                },
            ]
            try:
                repaired_content = self._completion(repair_messages, output_model)
            except Hy3ResponseError as error:
                return None, self._safe_failure(error)
            try:
                result = self._validate_content(repaired_content, output_model)
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as error:
                return None, _SafeFailure(
                    self._redact(
                        f"response failed schema validation after one repair: {error}"
                    ),
                    ErrorTaxonomy.FORMAT_SCHEMA,
                )

        try:
            self._ensure_secret_free(result)
            validate_result(result)
        except Hy3ResponseError as error:
            return None, self._safe_failure(error)
        return result, None

    def _safe_failure(self, error: Hy3ResponseError) -> _SafeFailure:
        return _SafeFailure(self._redact(str(error)), error.error_taxonomy)

    def _completion(
        self, messages: list[dict[str, str]], output_model: type[BaseModel]
    ) -> object:
        payload = {
            "model": self._config.model,
            "reasoning_effort": "high",
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__,
                    "strict": True,
                    "schema": output_model.model_json_schema(),
                },
            },
        }
        url = f"{self._config.base_url.rstrip('/')}/chat/completions"
        terminal_error: Hy3ResponseError | None = None
        for attempt in range(self._config.max_attempts):
            try:
                response = self._http.post(url, json=payload)
            except httpx.TransportError as error:
                if attempt + 1 < self._config.max_attempts:
                    continue
                terminal_error = Hy3ResponseError(
                    self._redact(f"Hy3 transport failure: {error}")
                )
                break
            if response.status_code in TRANSIENT_STATUS_CODES:
                if attempt + 1 < self._config.max_attempts:
                    continue
            if response.is_error:
                raise Hy3ResponseError(
                    self._redact(f"Hy3 HTTP {response.status_code}: {response.text}")
                )
            try:
                document = response.json()
                return document["choices"][0]["message"]["content"]
            except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
                terminal_error = Hy3ResponseError(
                    self._redact(f"invalid OpenAI-compatible response envelope: {error}")
                )
                break
        if terminal_error is not None:
            raise terminal_error
        raise Hy3ResponseError("Hy3 request exhausted retries")

    @staticmethod
    def _content_text(content: object) -> str:
        if isinstance(content, str):
            return content
        return _canonical_json(content)

    @staticmethod
    def _validate_content(
        content: object, output_model: type[StructuredModel]
    ) -> StructuredModel:
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
