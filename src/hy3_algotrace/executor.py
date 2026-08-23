"""Dependency-injected executors for deterministic tests and local background work."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol


class RunExecutor(Protocol):
    def submit(self, task: Callable[[], None]) -> None: ...


class SynchronousExecutor:
    """Execute immediately so tests can observe deterministic terminal state."""

    def submit(self, task: Callable[[], None]) -> None:
        task()


class InProcessBackgroundExecutor:
    """Small local thread pool; immutable artifacts remain the source of truth."""

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="hy3-algotrace-run",
        )

    def submit(self, task: Callable[[], None]) -> None:
        self._pool.submit(task)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)
