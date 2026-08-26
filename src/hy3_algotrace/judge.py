"""Narrow public interface for C++17 judging."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import JudgeEvidence, ProblemRecord

MAX_COUNTEREXAMPLE_CHARACTERS = 2048


def sanitize_counterexample_input(input_data: str) -> str:
    """Return the canonical safe representation stored in Judge evidence."""

    sanitized = "".join(
        character if character in {"\n", "\t"} or ord(character) >= 32 else "\ufffd"
        for character in input_data
    )
    if len(sanitized) > MAX_COUNTEREXAMPLE_CHARACTERS:
        return sanitized[:MAX_COUNTEREXAMPLE_CHARACTERS] + "\n<truncated>"
    return sanitized


@runtime_checkable
class Judge(Protocol):
    """Evaluate C++17 source against a problem's private final tests."""

    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        """Compile and evaluate source without executing it on the host."""
