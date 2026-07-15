from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from os import environ
from threading import Condition, Event, Lock, Thread
from time import monotonic
from typing import Callable, Literal, Mapping


@dataclass(frozen=True)
class WebRuntimeConfig:
    worker_count: int = 4
    queue_capacity: int = 32
    max_active_runs_per_user: int = 4
    run_timeout_seconds: int = 60

    def __post_init__(self) -> None:
        _require_range("worker_count", self.worker_count, 1, 16)
        _require_range("queue_capacity", self.queue_capacity, 1, 256)
        _require_range("max_active_runs_per_user", self.max_active_runs_per_user, 1, 32)
        _require_range("run_timeout_seconds", self.run_timeout_seconds, 1, 3600)
        if self.max_active_runs_per_user > self.worker_count + self.queue_capacity:
            raise ValueError("max_active_runs_per_user exceeds total runtime capacity")


def _require_range(name: str, value: int, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")


def _parse_integer(source: Mapping[str, str], name: str, default: int) -> int:
    raw = source.get(name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"{name} must be a decimal integer")
    return int(raw)


def load_web_runtime_config(source: Mapping[str, str] | None = None) -> WebRuntimeConfig:
    values = environ if source is None else source
    return WebRuntimeConfig(
        worker_count=_parse_integer(values, "SPECGATE_WEB_WORKERS", 4),
        queue_capacity=_parse_integer(values, "SPECGATE_WEB_QUEUE_CAPACITY", 32),
        max_active_runs_per_user=_parse_integer(
            values,
            "SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER",
            4,
        ),
        run_timeout_seconds=_parse_integer(
            values,
            "SPECGATE_WEB_RUN_TIMEOUT_SECONDS",
            60,
        ),
    )


class RuntimeCapacityExceeded(ValueError):
    code = "runtime_capacity_exceeded"

    def __init__(self, scope: str = "global") -> None:
        self.scope = scope
        super().__init__("Web 运行队列已满 / Web runtime capacity is full")


class RunCancelled(RuntimeError):
    pass


class RunTimedOut(RuntimeError):
    pass


@dataclass(frozen=True)
class RunTask:
    run_id: int
    user_id: int
    resume: bool


@dataclass
class RunControl:
    cancel_event: Event
    deadline_at: str
    deadline_monotonic: float
    monotonic_clock: Callable[[], float]

    def check(self) -> None:
        if self.cancel_event.is_set():
            raise RunCancelled("运行已取消")
        if self.monotonic_clock() >= self.deadline_monotonic:
            raise RunTimedOut("运行已超时")


@dataclass(frozen=True)
class RuntimeShutdownSnapshot:
    pending_run_ids: tuple[int, ...]
    running_run_ids: tuple[int, ...]


@dataclass(frozen=True)
class _QueuedTask:
    task: RunTask
    reservation_kind: Literal["worker", "queue"]


class RuntimeReservation:
    def __init__(
        self,
        coordinator: WebRuntimeCoordinator,
        kind: Literal["worker", "queue"],
    ) -> None:
        self._coordinator = coordinator
        self.kind = kind
        self._active = True
        self._run_id: int | None = None

    def bind(self, run_id: int) -> None:
        if not self._active:
            raise RuntimeError("runtime reservation is no longer active")
        if self._run_id is not None:
            raise RuntimeError("runtime reservation is already bound")
        self._coordinator._bind_reserved(self, run_id)
        self._run_id = run_id

    def submit(self, task: RunTask) -> None:
        if not self._active:
            raise RuntimeError("runtime reservation is no longer active")
        self._coordinator._submit_reserved(self, task)
        self._active = False

    def release(self) -> None:
        if not self._active:
            return
        self._coordinator._release_reserved(self)
        self._active = False


class WebRuntimeCoordinator:
    def __init__(
        self,
        config: WebRuntimeConfig,
        execute: Callable[[RunTask, RunControl], None],
        *,
        monotonic_clock: Callable[[], float] = monotonic,
        utc_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.config = config
        self._execute = execute
        self._monotonic = monotonic_clock
        self._utc_clock = utc_clock
        self._condition = Condition(Lock())
        self._pending: deque[_QueuedTask] = deque()
        self._controls: dict[int, RunControl] = {}
        self._reserved_run_ids: dict[int, RuntimeReservation] = {}
        self._threads: list[Thread] = []
        self._running = 0
        self._reserved_workers = 0
        self._queued_slots = 0
        self._accepting = True
        self._stopping = False
        self._refill_provider: Callable[[set[int]], RunTask | None] | None = None
        self._refill_lock = Lock()

    def start(self) -> None:
        with self._condition:
            if self._threads:
                return
            self._threads = [
                Thread(
                    target=self._worker,
                    name=f"specgate-web-run-{index + 1}",
                    daemon=True,
                )
                for index in range(self.config.worker_count)
            ]
            threads = tuple(self._threads)
        for thread in threads:
            thread.start()

    def reserve(self) -> RuntimeReservation:
        with self._condition:
            if not self._accepting:
                raise RuntimeCapacityExceeded("shutdown")
            has_waiting_queue = any(
                item.reservation_kind == "queue" for item in self._pending
            )
            if (
                not has_waiting_queue
                and self._running + self._reserved_workers < self.config.worker_count
            ):
                self._reserved_workers += 1
                return RuntimeReservation(self, "worker")
            if self._queued_slots < self.config.queue_capacity:
                self._queued_slots += 1
                return RuntimeReservation(self, "queue")
            raise RuntimeCapacityExceeded("global")

    def submit(self, reservation: RuntimeReservation, task: RunTask) -> None:
        reservation.submit(task)

    def _scheduled_run_ids_locked(self) -> set[int]:
        return (
            {item.task.run_id for item in self._pending}
            | set(self._controls)
            | set(self._reserved_run_ids)
        )

    def _submit_reserved(self, reservation: RuntimeReservation, task: RunTask) -> None:
        with self._condition:
            scheduled = self._scheduled_run_ids_locked()
            if reservation._run_id is not None and reservation._run_id != task.run_id:
                raise ValueError("runtime reservation is bound to another run")
            if reservation._run_id == task.run_id:
                self._reserved_run_ids.pop(task.run_id, None)
                scheduled.discard(task.run_id)
            if task.run_id in scheduled:
                raise ValueError("run is already scheduled")
            self._pending.append(_QueuedTask(task, reservation.kind))
            self._condition.notify_all()

    def _bind_reserved(self, reservation: RuntimeReservation, run_id: int) -> None:
        with self._condition:
            if run_id in self._scheduled_run_ids_locked():
                raise ValueError("run is already scheduled")
            self._reserved_run_ids[run_id] = reservation

    def _release_reserved(self, reservation: RuntimeReservation) -> None:
        with self._condition:
            if reservation._run_id is not None:
                current = self._reserved_run_ids.get(reservation._run_id)
                if current is reservation:
                    self._reserved_run_ids.pop(reservation._run_id, None)
            self._release_kind(reservation.kind)
            self._condition.notify_all()

    def _release_kind(self, kind: Literal["worker", "queue"]) -> None:
        if kind == "worker":
            self._reserved_workers -= 1
        else:
            self._queued_slots -= 1
        if self._reserved_workers < 0 or self._queued_slots < 0:
            raise RuntimeError("runtime capacity accounting underflow")

    def discard_pending(self, run_id: int) -> bool:
        with self._condition:
            for index, item in enumerate(self._pending):
                if item.task.run_id == run_id:
                    del self._pending[index]
                    self._release_kind(item.reservation_kind)
                    self._condition.notify_all()
                    return True
            return False

    def signal_cancel(self, run_id: int) -> bool:
        with self._condition:
            control = self._controls.get(run_id)
            if control is None:
                return False
            control.cancel_event.set()
            return True

    @property
    def running_count(self) -> int:
        with self._condition:
            return self._running

    @property
    def pending_count(self) -> int:
        with self._condition:
            return self._queued_slots

    def pending_run_ids(self) -> tuple[int, ...]:
        with self._condition:
            return tuple(item.task.run_id for item in self._pending)

    def scheduled_run_ids(self) -> set[int]:
        with self._condition:
            return self._scheduled_run_ids_locked()

    def set_refill_provider(
        self,
        provider: Callable[[set[int]], RunTask | None],
    ) -> None:
        self._refill_provider = provider

    def refill(self) -> None:
        self._refill()

    def _refill(self) -> None:
        provider = self._refill_provider
        if provider is None or self._stopping:
            return
        if not self._refill_lock.acquire(blocking=False):
            return
        try:
            while True:
                try:
                    reservation = self.reserve()
                except RuntimeCapacityExceeded:
                    return
                task = provider(self.scheduled_run_ids())
                if task is None:
                    reservation.release()
                    return
                try:
                    reservation.bind(task.run_id)
                    self.submit(reservation, task)
                except Exception:
                    reservation.release()
                    raise
        finally:
            self._refill_lock.release()

    def _take_runnable_locked(self) -> _QueuedTask | None:
        for index, item in enumerate(self._pending):
            if item.reservation_kind == "worker":
                del self._pending[index]
                self._reserved_workers -= 1
                self._running += 1
                return item
        if self._running + self._reserved_workers >= self.config.worker_count:
            return None
        for index, item in enumerate(self._pending):
            if item.reservation_kind == "queue":
                del self._pending[index]
                self._queued_slots -= 1
                self._running += 1
                return item
        return None

    def _worker(self) -> None:
        while True:
            with self._condition:
                item = self._take_runnable_locked()
                while item is None:
                    if self._stopping and not self._pending:
                        return
                    self._condition.wait()
                    item = self._take_runnable_locked()

                started_monotonic = self._monotonic()
                deadline_at = self._utc_clock() + timedelta(
                    seconds=self.config.run_timeout_seconds
                )
                control = RunControl(
                    cancel_event=Event(),
                    deadline_at=deadline_at.isoformat(),
                    deadline_monotonic=(
                        started_monotonic + self.config.run_timeout_seconds
                    ),
                    monotonic_clock=self._monotonic,
                )
                self._controls[item.task.run_id] = control

            try:
                self._execute(item.task, control)
            except Exception:
                pass
            finally:
                with self._condition:
                    self._controls.pop(item.task.run_id, None)
                    self._running -= 1
                    if self._running < 0:
                        raise RuntimeError("runtime running count underflow")
                    self._condition.notify_all()
                self._refill()

    def begin_shutdown(self) -> RuntimeShutdownSnapshot:
        with self._condition:
            self._accepting = False
            self._stopping = True
            pending = tuple(item.task.run_id for item in self._pending)
            for item in self._pending:
                self._release_kind(item.reservation_kind)
            self._pending.clear()
            running = tuple(self._controls)
            for control in self._controls.values():
                control.cancel_event.set()
            self._condition.notify_all()
            return RuntimeShutdownSnapshot(pending, running)

    def join(self, timeout_seconds: float = 5.0) -> None:
        deadline = self._monotonic() + timeout_seconds
        for thread in tuple(self._threads):
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                break
            thread.join(timeout=remaining)

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        self.begin_shutdown()
        self.join(timeout_seconds)
