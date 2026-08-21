"""Validation and discovery for formal CodeContests problem bundles."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hy3_algotrace.artifacts import sha256_json
from hy3_algotrace.contracts import ProblemOracle, ProblemRecord, SolutionTrace, Topic


class BundleValidationError(ValueError):
    """Raised when a problem cannot enter the formal catalog."""


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


def determine_primary_topic(tags: Iterable[str]) -> Topic:
    """Derive exactly one formal topic from Codeforces tags.

    A formal record is intentionally rejected if its tags identify multiple pilot
    topics. This keeps quota membership reproducible rather than heuristic.
    """

    normalized = {tag.strip().casefold() for tag in tags if tag.strip()}
    candidates = [topic for topic, topic_tags in _TOPIC_TAGS.items() if normalized & topic_tags]
    if len(candidates) != 1:
        raise BundleValidationError("primary topic must be unambiguous from Codeforces tags")
    return candidates[0]


def problem_content_hash(record: ProblemRecord) -> str:
    """Hash a record excluding its self-referential ``content_hash`` field."""

    payload = record.model_dump(mode="json")
    del payload["content_hash"]
    return sha256_json(payload)


def validate_problem_record(record: ProblemRecord) -> None:
    """Apply formal-dataset rules not expressible in the shared contract."""

    if record.source != "codeforces" or record.source_split not in {"validation", "test"}:
        raise BundleValidationError("formal records must be Codeforces validation/test entries")
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
    """Internal-only data needed to judge and audit one formal problem."""

    record: ProblemRecord
    oracle: ProblemOracle
    reference_cpp: str
    gold_trace: SolutionTrace

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
        """Load every direct child directory containing a complete formal bundle."""

        root_path = Path(root)
        if not root_path.is_dir():
            raise BundleValidationError(f"catalog directory does not exist: {root_path}")
        bundles: list[ProblemBundle] = []
        for directory in sorted(path for path in root_path.iterdir() if path.is_dir()):
            problem_path = directory / "problem.json"
            if not problem_path.exists():
                continue
            try:
                record = ProblemRecord.model_validate(_read_json(problem_path))
                oracle = ProblemOracle.model_validate(_read_json(directory / "oracle.json"))
                gold_trace = SolutionTrace.model_validate(_read_json(directory / "gold_trace.json"))
                reference_cpp = (directory / "reference.cpp").read_text(encoding="utf-8")
            except (OSError, json.JSONDecodeError, ValueError) as error:
                raise BundleValidationError(f"invalid bundle in {directory}: {error}") from error
            bundles.append(
                ProblemBundle(
                    record=record,
                    oracle=oracle,
                    reference_cpp=reference_cpp,
                    gold_trace=gold_trace,
                )
            )
        return cls(bundles)

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
        """Return model-visible problem data with all secret judge inputs removed."""

        record = self._get_bundle(problem_id).record
        return record.model_dump(
            mode="json",
            exclude={"hidden_tests", "generated_tests"},
        )

    def get_problem(self, problem_id: str) -> dict[str, Any]:
        """Compatibility alias for the public problem detail API."""

        return self.get_public_detail(problem_id)

    def get_bundle(self, problem_id: str) -> ProblemBundle:
        """Return internal judge data; callers must never use this for API output."""

        return self._get_bundle(problem_id)

    def _get_bundle(self, problem_id: str) -> ProblemBundle:
        try:
            return self._by_id[problem_id]
        except KeyError as error:
            raise KeyError(f"unknown problem ID: {problem_id}") from error


def _read_json(path: Path) -> Mapping[str, Any]:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise BundleValidationError(f"{path.name} must contain a JSON object")
    return value
