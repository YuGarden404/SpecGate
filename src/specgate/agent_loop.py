from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

from specgate.action_pipeline import ExecutionOutcome
from specgate.actions import Action, ActionParseError
from specgate.llm import LLMClient, LLMProviderError
from specgate.metrics import RunMetrics, add_run_metrics
from specgate.run_control import (
    CancellationToken,
    LoopDecisionKind,
    RunCancelled,
    RunTimedOut,
    StopPolicy,
)
from specgate.run_state import (
    Observation,
    RunState,
    RunStateStore,
    RunStatus,
    StateDelta,
)
from specgate.runtime_events import RunEventContext, RunEventSink


_STABLE_PROVIDER_ERROR_CODES = frozenset(
    {
        "llm_authentication_failed",
        "llm_provider_unavailable",
        "llm_rate_limited",
        "llm_request_rejected",
        "llm_request_timeout",
        "llm_response_invalid",
    }
)


@dataclass(frozen=True)
class ContextBuild:
    text: str
    metadata: dict[str, Any]


class ContextBuilder(Protocol):
    def build(self, state: RunState) -> ContextBuild: ...


class ActionExecutor(Protocol):
    def execute(self, action: Action, state: RunState) -> ExecutionOutcome: ...


ActionParser = Callable[[str], Action]


class AgentLoop:
    def __init__(
        self,
        *,
        context_builder: ContextBuilder,
        llm: LLMClient,
        parse_action: ActionParser,
        action_executor: ActionExecutor,
        state_store: RunStateStore,
        stop_policy: StopPolicy,
        cancel_token: CancellationToken,
        event_sink: RunEventSink,
        event_context: RunEventContext,
    ) -> None:
        self._context_builder = context_builder
        self._llm = llm
        self._parse_action = parse_action
        self._action_executor = action_executor
        self._state_store = state_store
        self._stop_policy = stop_policy
        self._cancel_token = cancel_token
        self._event_sink = event_sink
        self._event_context = event_context

    def run(self, run_id: str) -> RunState:
        try:
            self._event_sink.emit(
                self._event_context,
                "RunStarted",
                {"status": RunStatus.RUNNING.value},
                phase="loop",
            )
            while True:
                self._cancel_token.check()
                state = self._state_store.get(run_id)
                decision = self._stop_policy.decide(state)

                if decision.kind is LoopDecisionKind.SUSPEND:
                    self._event_sink.emit(
                        self._event_context,
                        "RunSuspended",
                        {
                            "status": state.status.value,
                            "reason": decision.reason,
                        },
                        step=state.step,
                        phase="loop",
                    )
                    return state

                if decision.kind is LoopDecisionKind.TERMINATE:
                    if (
                        decision.outcome is not None
                        and decision.outcome is not state.status
                    ):
                        state = self._state_store.apply(
                            run_id,
                            state.revision,
                            StateDelta(status=decision.outcome),
                        )
                    self._event_sink.emit(
                        self._event_context,
                        "RunFinished",
                        {
                            "status": state.status.value,
                            "reason": decision.reason,
                        },
                        step=state.step,
                        phase="loop",
                    )
                    return state

                assert decision.kind is LoopDecisionKind.CONTINUE
                built = self._context_builder.build(state)
                self._event_sink.emit(
                    self._event_context,
                    "ContextBuilt",
                    built.metadata,
                    step=state.step,
                    phase="context",
                )

                try:
                    raw = self._llm.complete(built.text)
                except LLMProviderError as exc:
                    return self._finish_provider_failure(run_id, state, exc)

                self._cancel_token.check()
                self._event_sink.emit(
                    self._event_context,
                    "LLMCompleted",
                    {"response_chars": len(raw)},
                    step=state.step,
                    phase="llm",
                )

                try:
                    action = self._parse_action(raw)
                except ActionParseError as exc:
                    delta = parse_error_delta(state, exc)
                else:
                    outcome = self._action_executor.execute(action, state)
                    delta = _add_loop_metrics(outcome.state_delta)

                self._state_store.apply(run_id, state.revision, delta)
        except RunCancelled:
            return self._finish_control_signal(
                run_id,
                RunStatus.CANCELLED,
                "run_cancelled",
            )
        except RunTimedOut:
            return self._finish_control_signal(
                run_id,
                RunStatus.TIMED_OUT,
                "run_timed_out",
            )
        except Exception:
            self._record_system_failure(run_id)
            raise

    def _finish_provider_failure(
        self,
        run_id: str,
        state: RunState,
        error: LLMProviderError,
    ) -> RunState:
        code = _provider_error_code(error)
        status = (
            RunStatus.TIMED_OUT
            if code == "llm_request_timeout"
            else RunStatus.FAILED
        )
        observation = _stable_error_observation(code)
        updated = self._state_store.apply(
            run_id,
            state.revision,
            StateDelta(
                status=status,
                append_observations=(observation,),
                metrics=RunMetrics(llm_calls=1),
            ),
        )
        self._event_sink.emit(
            self._event_context,
            "RunFailed",
            {"status": status.value, "code": code},
            step=updated.step,
            phase="llm",
        )
        return updated

    def _finish_control_signal(
        self,
        run_id: str,
        status: RunStatus,
        code: str,
    ) -> RunState:
        state = self._state_store.get(run_id)
        updated = self._state_store.apply(
            run_id,
            state.revision,
            StateDelta(
                status=status,
                append_observations=(_stable_error_observation(code),),
            ),
        )
        try:
            self._event_sink.emit(
                self._event_context,
                "RunFinished",
                {"status": status.value, "code": code},
                step=updated.step,
                phase="loop",
            )
        except Exception:
            self._record_system_failure(run_id)
            raise
        return updated

    def _record_system_failure(self, run_id: str) -> None:
        try:
            state = self._state_store.get(run_id)
            updated = self._state_store.apply(
                run_id,
                state.revision,
                StateDelta(
                    status=RunStatus.FAILED,
                    append_observations=(
                        _stable_error_observation("runtime_failed"),
                    ),
                ),
            )
            step = updated.step
        except Exception:
            step = 0
        try:
            self._event_sink.emit(
                self._event_context,
                "RunFailed",
                {"status": RunStatus.FAILED.value, "code": "runtime_failed"},
                step=step,
                phase="loop",
            )
        except Exception:
            pass


def parse_error_delta(
    state: RunState,
    error: ActionParseError,
) -> StateDelta:
    del error
    return StateDelta(
        step=state.step + 1,
        append_observations=(
            Observation(
                "action_parse_failed",
                {"code": "action_parse_failed"},
            ),
        ),
        metrics=RunMetrics(steps=1, llm_calls=1, parse_errors=1),
    )


def _add_loop_metrics(delta: StateDelta) -> StateDelta:
    return replace(
        delta,
        metrics=add_run_metrics(
            delta.metrics,
            RunMetrics(steps=1, llm_calls=1),
        ),
    )


def _stable_error_observation(code: str) -> Observation:
    return Observation("runtime_error", {"code": code})


def _provider_error_code(error: LLMProviderError) -> str:
    if error.code in _STABLE_PROVIDER_ERROR_CODES:
        return error.code
    return "llm_provider_failed"
