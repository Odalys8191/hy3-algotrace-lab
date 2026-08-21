"""Narrow public interface for C++17 judging."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .contracts import JudgeEvidence, ProblemRecord


@runtime_checkable
class Judge(Protocol):
    """Evaluate C++17 source against a problem's private final tests."""

    def judge(self, problem: ProblemRecord, cpp_source: str) -> JudgeEvidence:
        """Compile and evaluate source without executing it on the host."""
