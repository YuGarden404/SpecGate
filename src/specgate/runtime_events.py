from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Any, Callable, Protocol

from specgate.trace import TraceStore, redact


@dataclass(frozen=True)
class RunEventContext:
    run_id: str
    agent_run_id: str
    parent_run_id: str | None = None


@dataclass(frozen=True)
class RunEvent:
    run_id: str
    agent_run_id: str
    parent_run_id: str | None
    step: int
    phase: str
    event_type: str
    timestamp: str
    payload: dict[str, Any]


class RunEventSink(Protocol):
    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None: ...


class NullRunEventSink:
    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        del context, event_type, payload, step, phase


class FanoutRunEventSink:
    def __init__(
        self,
        primary: RunEventSink,
        observers: tuple[RunEventSink, ...] = (),
        on_observer_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._primary = primary
        self._observers = tuple(observers)
        self._on_observer_error = on_observer_error or (lambda error: None)

    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        safe_payload = redact(deepcopy(payload))
        assert isinstance(safe_payload, dict)
        self._primary.emit(
            context,
            event_type,
            deepcopy(safe_payload),
            step=step,
            phase=phase,
        )
        for observer in self._observers:
            try:
                observer.emit(
                    context,
                    event_type,
                    deepcopy(safe_payload),
                    step=step,
                    phase=phase,
                )
            except Exception as exc:
                try:
                    self._on_observer_error(exc)
                except Exception:
                    pass


class InMemoryRunEventSink:
    def __init__(self, clock: Callable[[], str]) -> None:
        self._clock = clock
        self._events: list[RunEvent] = []
        self._lock = Lock()

    @property
    def events(self) -> tuple[RunEvent, ...]:
        with self._lock:
            return deepcopy(tuple(self._events))

    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        event = RunEvent(
            run_id=context.run_id,
            agent_run_id=context.agent_run_id,
            parent_run_id=context.parent_run_id,
            step=step,
            phase=phase,
            event_type=event_type,
            timestamp=self._clock(),
            payload=redact(deepcopy(payload)),
        )
        with self._lock:
            self._events.append(deepcopy(event))


@dataclass(frozen=True)
class TraceRunEventSink:
    trace: TraceStore

    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict[str, Any],
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        self.trace.append(
            event_type,
            {
                "run_id": context.run_id,
                "agent_run_id": context.agent_run_id,
                "parent_run_id": context.parent_run_id,
                "step": step,
                "phase": phase,
                "data": redact(deepcopy(payload)),
            },
        )
