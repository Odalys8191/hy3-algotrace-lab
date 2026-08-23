"""Dependency-injected executors for deterministic tests and local background work."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Literal, Protocol


class ExecutorTaskHealth(StrEnum):
    """Safe observable state for an in-process background task."""

    ACTIVE = "active"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExecutorTaskFailure:
    """Controlled failure metadata that never retains the worker exception."""

    task_id: str
    code: Literal["internal_failure"] = "internal_failure"
    message: Literal["background task failed"] = "background task failed"


class RunExecutor(Protocol):
    def submit(self, task: Callable[[], None], *, task_id: str | None = None) -> None: ...

    def failure_for(self, task_id: str) -> ExecutorTaskFailure | None: ...

    def task_health(self, task_id: str) -> ExecutorTaskHealth: ...

    def active_task_ids(self) -> tuple[str, ...]: ...


class SynchronousExecutor:
    """Execute immediately so tests can observe deterministic terminal state."""

    def submit(self, task: Callable[[], None], *, task_id: str | None = None) -> None:
        del task_id
        task()

    def failure_for(self, task_id: str) -> ExecutorTaskFailure | None:
        del task_id
        return None

    def task_health(self, task_id: str) -> ExecutorTaskHealth:
        del task_id
        return ExecutorTaskHealth.UNKNOWN

    def active_task_ids(self) -> tuple[str, ...]:
        return ()


class InProcessBackgroundExecutor:
    """Small local thread pool; immutable artifacts remain the source of truth."""

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be positive")
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="hy3-algotrace-run",
        )
        self._lock = Lock()
        self._futures: dict[str, Future[None]] = {}
        self._failures: dict[str, ExecutorTaskFailure] = {}

    def submit(self, task: Callable[[], None], *, task_id: str | None = None) -> None:
        if task_id is None:
            raise ValueError("background execution requires a task ID for monitoring")
        with self._lock:
            if task_id in self._futures or task_id in self._failures:
                raise ValueError(f"duplicate background task ID: {task_id}")
            future = self._pool.submit(task)
            self._futures[task_id] = future
        future.add_done_callback(lambda completed: self._task_done(task_id, completed))

    def failure_for(self, task_id: str) -> ExecutorTaskFailure | None:
        with self._lock:
            return self._failures.get(task_id)

    def task_health(self, task_id: str) -> ExecutorTaskHealth:
        with self._lock:
            if task_id in self._futures:
                return ExecutorTaskHealth.ACTIVE
            if task_id in self._failures:
                return ExecutorTaskHealth.FAILED
            return ExecutorTaskHealth.UNKNOWN

    def active_task_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._futures))

    def _task_done(self, task_id: str, future: Future[None]) -> None:
        failed = False
        try:
            future.result()
        except BaseException:
            failed = True
        with self._lock:
            self._futures.pop(task_id, None)
            if failed:
                self._failures[task_id] = ExecutorTaskFailure(task_id=task_id)

    def shutdown(self, *, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=False)
