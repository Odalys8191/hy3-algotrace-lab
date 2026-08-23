"""Validation and discovery for formal CodeContests and synthetic pilot bundles."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hy3_algotrace.artifacts import canonical_json_bytes, sha256_json
from hy3_algotrace.contracts import ProblemOracle, ProblemRecord, SolutionTrace, TestCase, Topic


class BundleValidationError(ValueError):
    """Raised when a problem cannot enter a formal catalog."""


_TOPIC_TAGS: Mapping[Topic, frozenset[str]] = {
    Topic.CONSTRUCTION_SIMULATION: frozenset({"constructive algorithms", "implementation"}),
    Topic.GREEDY: frozenset({"greedy"}),
    Topic.BINARY_SEARCH: frozenset({"binary search"}),
    Topic.DYNAMIC_PROGRAMMING: frozenset({"dp"}),
    Topic.GRAPH: frozenset(
        {
            "graphs",
            "graph matchings",
            "shortest paths",
            "trees",
            "dfs and similar",
            "flows",
            "2-sat",
            "dsu",
        }
    ),
}
_MAX_TIME_LIMIT_MS = 10_000
_MAX_MEMORY_LIMIT_MB = 1_024
_CATALOG_ROOT_FILES = frozenset({"manifest.json"})
_FORMAL_BUNDLE_FILES = frozenset(
    {"problem.json", "oracle.json", "gold_trace.json", "reference.cpp"}
)
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW


def determine_primary_topic(tags: Iterable[str]) -> Topic:
    """Derive exactly one formal topic from Codeforces tags."""

    normalized = {tag.strip().casefold() for tag in tags if tag.strip()}
    candidates = [topic for topic, topic_tags in _TOPIC_TAGS.items() if normalized & topic_tags]
    if len(candidates) != 1:
        raise BundleValidationError("primary topic must be unambiguous from Codeforces tags")
    return candidates[0]


def canonical_codeforces_url(contest_id: int, index: str) -> str:
    """Return the only accepted canonical Codeforces problem URL."""

    return f"https://codeforces.com/problemset/problem/{contest_id}/{index}"


def problem_content_hash(record: ProblemRecord) -> str:
    """Hash a record excluding its self-referential ``content_hash`` field."""

    payload = record.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_json(payload)


def validate_problem_record(record: ProblemRecord) -> None:
    """Apply formal-dataset rules not expressible in the shared contract."""

    if record.source != "codeforces" or record.source_split not in {"validation", "test"}:
        raise BundleValidationError("formal records must be Codeforces validation/test entries")
    expected_id = f"cf-{record.cf_contest_id}-{record.cf_index.casefold()}"
    if record.problem_id != expected_id:
        raise BundleValidationError("problem ID must match Codeforces contest and index")
    expected_url = canonical_codeforces_url(record.cf_contest_id, record.cf_index)
    parsed = urlsplit(record.source_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "codeforces.com"
        or parsed.query
        or parsed.fragment
        or record.source_url != expected_url
    ):
        raise BundleValidationError("Codeforces URL must match the stated contest and index")
    if not record.attribution.strip():
        raise BundleValidationError("formal records require attribution")
    if record.is_description_translated:
        raise BundleValidationError("formal records require the original English statement")
    if record.input_file or record.output_file:
        raise BundleValidationError("formal records must use standard stdin/stdout")
    if not record.hidden_tests:
        raise BundleValidationError("formal records require non-empty hidden tests")
    if not (0 < record.time_limit_ms <= _MAX_TIME_LIMIT_MS) or not (
        0 < record.memory_limit_mb <= _MAX_MEMORY_LIMIT_MB
    ):
        raise BundleValidationError("formal records have invalid resource limits")
    primary_topic = determine_primary_topic(record.cf_tags)
    if primary_topic is not record.topic:
        raise BundleValidationError("record topic does not match its unambiguous primary topic")
    if problem_content_hash(record) != record.content_hash:
        raise BundleValidationError("problem content_hash does not match canonical record content")


@dataclass(frozen=True, slots=True)
class ProblemBundle:
    """Internal data needed to judge and audit one formal Codeforces problem."""

    record: ProblemRecord
    oracle: ProblemOracle
    reference_cpp: str
    gold_trace: SolutionTrace
    formal_selection_eligible: Literal[True] = True

    def __post_init__(self) -> None:
        validate_problem_record(self.record)
        if self.oracle.problem_id != self.record.problem_id:
            raise BundleValidationError("oracle problem ID does not match problem record")
        if not self.reference_cpp.strip():
            raise BundleValidationError("reference.cpp cannot be empty")
        if sha256_json(self.reference_cpp) != self.oracle.reference_solution_hash:
            raise BundleValidationError(
                "oracle reference solution hash does not match reference.cpp"
            )
        if self.gold_trace.problem_id != self.record.problem_id:
            raise BundleValidationError("gold trace problem ID does not match problem record")


class PilotProblemRecord(BaseModel):
    """Project-authored fixture record kept outside the Codeforces contract boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["project_authored_test_fixture"] = "project_authored_test_fixture"
    formal_selection_eligible: Literal[False] = False
    formal_metrics_eligible: Literal[False] = False
    problem_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    statement_en: str = Field(min_length=1)
    language: Literal["cpp17"] = "cpp17"
    time_limit_ms: int = Field(gt=0)
    memory_limit_mb: int = Field(gt=0)
    public_tests: tuple[TestCase, ...] = Field(min_length=1)
    hidden_tests: tuple[TestCase, ...] = Field(min_length=1)
    generated_tests: tuple[TestCase, ...] = ()
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("content_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    def expected_content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        del payload["content_hash"]
        return sha256_json(payload)


class PilotManifest(BaseModel):
    """Closed, immutable declaration of the five local pilot directories."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.2"] = "1.2"
    kind: Literal["project_authored_test_fixture_pilots"] = (
        "project_authored_test_fixture_pilots"
    )
    formal_selection_eligible: Literal[False] = False
    formal_metrics_eligible: Literal[False] = False
    notice: str = Field(min_length=1)
    bundles: tuple[str, ...] = Field(min_length=5, max_length=5)

    @field_validator("bundles")
    @classmethod
    def validate_bundle_names(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(names)) != len(names):
            raise ValueError("pilot manifest bundle names must be unique")
        if any(
            not name
            or name in {".", ".."}
            or "\x00" in name
            or Path(name).is_absolute()
            or Path(name).parts != (name,)
            for name in names
        ):
            raise ValueError("pilot bundle names must be safe single path components")
        return names


@dataclass(frozen=True, slots=True)
class PilotBundle:
    """Complete local-only fixture envelope; never a formal dataset candidate."""

    record: PilotProblemRecord
    oracle: ProblemOracle
    reference_cpp: str
    gold_trace: SolutionTrace
    formal_selection_eligible: Literal[False] = False

    @property
    def public_tests(self) -> tuple[TestCase, ...]:
        return self.record.public_tests

    @property
    def hidden_tests(self) -> tuple[TestCase, ...]:
        return self.record.hidden_tests

    def __post_init__(self) -> None:
        if self.record.content_hash != self.record.expected_content_hash():
            raise BundleValidationError(
                "pilot content_hash does not match canonical record content"
            )
        if self.oracle.problem_id != self.record.problem_id:
            raise BundleValidationError("pilot oracle problem ID does not match pilot record")
        if not self.reference_cpp.strip():
            raise BundleValidationError("pilot reference.cpp cannot be empty")
        if sha256_json(self.reference_cpp) != self.oracle.reference_solution_hash:
            raise BundleValidationError("pilot oracle reference hash does not match reference.cpp")
        if self.gold_trace.problem_id != self.record.problem_id:
            raise BundleValidationError("pilot gold trace problem ID does not match pilot record")


@dataclass(frozen=True, slots=True)
class ProblemSummary:
    problem_id: str
    title: str
    topic: Topic
    rating: int


class ProblemCatalog:
    """An immutable in-memory index of validated formal bundles."""

    def __init__(self, bundles: Iterable[ProblemBundle]) -> None:
        by_id: dict[str, ProblemBundle] = {}
        for bundle in bundles:
            problem_id = bundle.record.problem_id
            if problem_id in by_id:
                raise BundleValidationError(f"duplicate problem ID in catalog: {problem_id}")
            by_id[problem_id] = bundle
        self._by_id = dict(sorted(by_id.items()))

    @classmethod
    def from_directory(cls, root: Path | str) -> ProblemCatalog:
        """Load a formal root and fail closed on every unrecognized entry."""

        root_path = Path(root)
        try:
            root_fd = os.open(root_path, _DIRECTORY_OPEN_FLAGS)
        except OSError as error:
            raise BundleValidationError(
                f"catalog directory cannot be opened securely: {root_path}"
            ) from error
        try:
            bundles: list[ProblemBundle] = []
            for name in sorted(os.listdir(root_fd)):
                metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    raise BundleValidationError(f"catalog symlink is forbidden: {name}")
                if stat.S_ISREG(metadata.st_mode):
                    if name not in _CATALOG_ROOT_FILES:
                        raise BundleValidationError(f"unknown catalog entry: {name}")
                    continue
                if not stat.S_ISDIR(metadata.st_mode):
                    raise BundleValidationError(f"unknown catalog entry: {name}")
                try:
                    bundle_fd = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=root_fd)
                except OSError as error:
                    raise BundleValidationError(
                        f"catalog bundle cannot be opened without following symlinks: {name}"
                    ) from error
                try:
                    bundles.append(_load_formal_bundle_at(bundle_fd, name))
                finally:
                    os.close(bundle_fd)
            return cls(bundles)
        except OSError as error:
            raise BundleValidationError(f"cannot inspect catalog directory: {root_path}") from error
        finally:
            os.close(root_fd)

    def list_problems(self) -> tuple[ProblemSummary, ...]:
        """List only metadata safe for a public service response."""

        return tuple(
            ProblemSummary(
                problem_id=bundle.record.problem_id,
                title=bundle.record.title,
                topic=bundle.record.topic,
                rating=bundle.record.rating,
            )
            for bundle in self._by_id.values()
        )

    def get_public_detail(self, problem_id: str) -> dict[str, Any]:
        """Return model-visible data without hidden tests or generated judge cases."""

        record = self._get_bundle(problem_id).record
        return record.model_dump(mode="json", exclude={"hidden_tests", "generated_tests"})

    def get_problem(self, problem_id: str) -> dict[str, Any]:
        """Compatibility alias for the public problem detail API."""

        return self.get_public_detail(problem_id)

    def get_bundle(self, problem_id: str) -> ProblemBundle:
        """Return internal judge data; never use it for API output."""

        return self._get_bundle(problem_id)

    def _get_bundle(self, problem_id: str) -> ProblemBundle:
        try:
            return self._by_id[problem_id]
        except KeyError as error:
            raise KeyError(f"unknown problem ID: {problem_id}") from error


def load_pilot_bundles(root: Path | str) -> tuple[PilotBundle, ...]:
    """Load all declared project-authored pilots through versioned validators."""

    root_path = Path(root)
    try:
        root_fd = os.open(root_path, _DIRECTORY_OPEN_FLAGS)
    except OSError as error:
        raise BundleValidationError(f"invalid pilot root: {root_path}") from error
    try:
        try:
            manifest = _strict_model_validate(
                PilotManifest, _read_json_at(root_fd, "manifest.json")
            )
        except (OSError, json.JSONDecodeError, ValueError) as error:
            raise BundleValidationError(f"invalid pilot manifest: {error}") from error
        declared = set(manifest.bundles)
        discovered: set[str] = set()
        for name in os.listdir(root_fd):
            metadata = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode):
                raise BundleValidationError(f"pilot symlink is forbidden: {name}")
            if name == "manifest.json" and stat.S_ISREG(metadata.st_mode):
                continue
            if not stat.S_ISDIR(metadata.st_mode):
                raise BundleValidationError(f"unknown pilot entry: {name}")
            if name not in declared:
                raise BundleValidationError(f"undeclared pilot bundle directory: {name}")
            discovered.add(name)
        if discovered != declared:
            raise BundleValidationError("pilot manifest declares a missing bundle directory")
        bundles: list[PilotBundle] = []
        for name in manifest.bundles:
            try:
                directory_fd = os.open(name, _DIRECTORY_OPEN_FLAGS, dir_fd=root_fd)
            except OSError as error:
                raise BundleValidationError(
                    f"pilot bundle cannot be opened without following symlinks: {name}"
                ) from error
            try:
                bundles.append(_load_pilot_bundle_at(directory_fd, name))
            finally:
                os.close(directory_fd)
        problem_ids = [bundle.record.problem_id for bundle in bundles]
        if len(set(problem_ids)) != len(problem_ids):
            raise BundleValidationError("pilot bundles must have unique problem IDs")
        return tuple(bundles)
    except OSError as error:
        raise BundleValidationError(f"cannot inspect pilot root: {root_path}") from error
    finally:
        os.close(root_fd)


def _load_pilot_bundle_at(directory_fd: int, directory_name: str) -> PilotBundle:
    try:
        _validate_bundle_members(directory_fd, directory_name, "pilot.json")
        record = _strict_model_validate(
            PilotProblemRecord, _read_json_at(directory_fd, "pilot.json")
        )
        oracle = _strict_model_validate(
            ProblemOracle, _read_json_at(directory_fd, "oracle.json")
        )
        gold_trace = _strict_model_validate(
            SolutionTrace, _read_json_at(directory_fd, "gold_trace.json")
        )
        reference_cpp = _read_text_at(directory_fd, "reference.cpp")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise BundleValidationError(f"invalid pilot bundle {directory_name}: {error}") from error
    return PilotBundle(record, oracle, reference_cpp, gold_trace)


def _load_formal_bundle_at(directory_fd: int, directory_name: str) -> ProblemBundle:
    try:
        _validate_bundle_members(directory_fd, directory_name, "problem.json")
        record = _strict_model_validate(
            ProblemRecord, _read_json_at(directory_fd, "problem.json")
        )
        oracle = _strict_model_validate(
            ProblemOracle, _read_json_at(directory_fd, "oracle.json")
        )
        gold_trace = _strict_model_validate(
            SolutionTrace, _read_json_at(directory_fd, "gold_trace.json")
        )
        reference_cpp = _read_text_at(directory_fd, "reference.cpp")
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise BundleValidationError(f"invalid bundle in {directory_name}: {error}") from error
    return ProblemBundle(record, oracle, reference_cpp, gold_trace)


def _validate_bundle_members(
    directory_fd: int, directory_name: str, record_filename: str
) -> None:
    members = set(os.listdir(directory_fd))
    for member in members:
        metadata = os.stat(member, dir_fd=directory_fd, follow_symlinks=False)
        if stat.S_ISLNK(metadata.st_mode):
            raise BundleValidationError(
                f"bundle member symlink is forbidden: {directory_name}/{member}"
            )
        if not stat.S_ISREG(metadata.st_mode):
            raise BundleValidationError(
                f"bundle member must be a regular file: {directory_name}/{member}"
            )
    if record_filename not in members:
        raise BundleValidationError(f"unknown catalog entry: {directory_name}")
    expected = (_FORMAL_BUNDLE_FILES - {"problem.json"}) | {record_filename}
    if members != expected:
        raise BundleValidationError(
            f"bundle {directory_name} must contain exactly the required bundle members"
        )


def _read_json_at(directory_fd: int, name: str) -> Mapping[str, Any]:
    value: Any = json.loads(_read_text_at(directory_fd, name))
    if not isinstance(value, Mapping):
        raise BundleValidationError(f"{name} must contain a JSON object")
    return value


def _strict_model_validate[ModelT: BaseModel](
    model_type: type[ModelT], payload: Mapping[str, Any]
) -> ModelT:
    validated = model_type.model_validate(payload)
    if canonical_json_bytes(payload) != canonical_json_bytes(
        validated.model_dump(mode="json")
    ):
        raise BundleValidationError(
            "disk artifact must use strict JSON types and explicit canonical fields"
        )
    return validated


def _read_text_at(directory_fd: int, name: str) -> str:
    file_fd = os.open(name, _FILE_OPEN_FLAGS, dir_fd=directory_fd)
    try:
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            raise BundleValidationError(f"bundle member must be a regular file: {name}")
        with os.fdopen(file_fd, encoding="utf-8") as stream:
            file_fd = -1
            return stream.read()
    finally:
        if file_fd >= 0:
            os.close(file_fd)
