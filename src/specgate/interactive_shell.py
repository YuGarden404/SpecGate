from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Protocol, TypeVar

from specgate.approvals import (
    ApprovalStore,
    approval_queue_path,
    read_approval_queue_if_present,
)
from specgate.run_control import RunCancelled
from specgate.shell_config import ConfigCommandResult
from specgate.shell_renderer import ShellEventRenderer
from specgate.shell_runtime import (
    ConnectionTestResult,
    ShellRunOutcome,
    SpecGateShellRuntime,
)
from specgate.shell_terminal import SHELL_PROMPT, ShellTerminal
from specgate.trace import redact
from specgate.user_config import UserShellConfig


EXIT_WORDS = frozenset({"exit", "quit", "q"})
COMMANDS = frozenset(
    {
        "help",
        "status",
        "setup",
        "mode",
        "workspace",
        "model",
        "url",
        "api-key",
        "verbose",
        "approvals",
        "clear",
        "exit",
    }
)
MOCK_DEMO_REQUEST = "Run the built-in SpecGate MockLLM Demo."
_POLL_SECONDS = 0.05
_T = TypeVar("_T")


@dataclass(frozen=True)
class ShellInput:
    kind: str
    name: str | None = None
    argument: str | None = None


def parse_input(raw: str) -> ShellInput:
    value = raw.strip()
    if not value:
        return ShellInput("empty")
    if value.lower() in EXIT_WORDS:
        return ShellInput("exit")
    if not value.startswith("/"):
        return ShellInput("request", argument=value)
    head, separator, tail = value[1:].partition(" ")
    name = head.lower()
    if name == "exit":
        return ShellInput("exit")
    argument = tail.strip() if separator and tail.strip() else None
    return ShellInput("command", name=name, argument=argument)


class EventCancellationToken:
    def __init__(self) -> None:
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise RunCancelled("run cancelled")

    def remaining_seconds(self) -> float:
        return float("inf")


class ShellConfigRuntime(Protocol):
    config: UserShellConfig

    def ensure_ready(self) -> UserShellConfig: ...

    def execute(self, name: str, argument: str | None) -> ConfigCommandResult: ...


class PendingApprovalView(Protocol):
    id: str
    action: str
    path: str | None
    risk_level: str
    reason: str


class ShellRuntime(Protocol):
    @property
    def workspace(self): ...

    def start(
        self,
        request: str,
        event_sink,
        cancel_token: EventCancellationToken,
    ) -> ShellRunOutcome: ...

    def decide(
        self,
        pending: ShellRunOutcome,
        *,
        decision: str,
        reason: str | None,
    ) -> ShellRunOutcome: ...

    def test_connection(
        self,
        cancel_token: EventCancellationToken,
    ) -> ConnectionTestResult: ...

    def close(self) -> None: ...


class InteractiveShell:
    def __init__(
        self,
        terminal: ShellTerminal,
        config_controller: ShellConfigRuntime,
        runtime: SpecGateShellRuntime | ShellRuntime,
    ) -> None:
        self._terminal = terminal
        self._config_controller = config_controller
        self._runtime = runtime
        self._executor: ThreadPoolExecutor | None = None
        self._last_outcome: ShellRunOutcome | None = None

    def run(self) -> int:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="specgate-shell",
        )
        try:
            previous = self._config_controller.config
            try:
                ready = self._config_controller.ensure_ready()
            except (EOFError, KeyboardInterrupt):
                return 0
            except (OSError, TypeError, ValueError) as exc:
                self._write_error("Shell setup failed", exc)
                return 1
            if ready.mode == "real" and ready != previous:
                self._offer_connection_test()
            self._terminal.write("Type /help for commands.", style="muted")

            while True:
                try:
                    item = parse_input(self._terminal.read(SHELL_PROMPT))
                    if item.kind == "exit":
                        break
                    if item.kind == "empty":
                        continue
                    if item.kind == "command":
                        self._handle_command(item)
                    else:
                        assert item.argument is not None
                        self._handle_request(item.argument)
                except (EOFError, KeyboardInterrupt):
                    break
            return 0
        finally:
            executor = self._executor
            self._executor = None
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
            self._runtime.close()

    def _handle_command(self, item: ShellInput) -> None:
        assert item.name is not None
        if item.name == "approvals":
            self._handle_external_approvals()
            return
        result = self._config_controller.execute(item.name, item.argument)
        if item.name == "status":
            self._print_last_status()
        if result.ok and result.request_connection_test:
            self._offer_connection_test()

    def _handle_request(self, request: str) -> None:
        config = self._config_controller.config
        if config.mode == "mock":
            self._terminal.write(
                "[Mock] 当前模式不会处理自定义需求，只能展示内置 Demo。",
                style="warning",
            )
            if not self._read_yes_no("是否运行 Mock Demo？[Y/n] ", default=True):
                return
            request = MOCK_DEMO_REQUEST

        token = EventCancellationToken()
        renderer = ShellEventRenderer(
            self._terminal,
            verbose=self._config_controller.config.verbose,
        )
        try:
            pending = self._execute_active(
                lambda: self._runtime.start(request, renderer, token),
                token,
            )
            while pending.status == "pending_approval":
                self._last_outcome = pending
                approval_id = pending.pending_approval_id or "approval"
                self._terminal.write(
                    f"[Approval] Decision required: {approval_id}",
                    style="approval",
                )
                approved = self._read_yes_no("Approve? [y/N]: ", default=False)
                decision = "approved" if approved else "denied"
                reason = None if approved else "human denied"
                pending = self._execute_active(
                    lambda: self._runtime.decide(
                        pending,
                        decision=decision,
                        reason=reason,
                    ),
                    token,
                )
            self._display_outcome(pending)
        except RunCancelled:
            self._terminal.write("[Cancelled]", style="warning")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._write_error("Run failed", exc)

    def _execute_active(
        self,
        operation: Callable[[], _T],
        token: EventCancellationToken,
    ) -> _T:
        executor = self._executor
        if executor is None:
            raise RuntimeError("shell_executor_not_running")
        future = executor.submit(operation)
        cancellation_announced = False
        while True:
            try:
                return self._wait_once(future)
            except FutureTimeout:
                continue
            except KeyboardInterrupt:
                token.cancel()
                if not cancellation_announced:
                    self._terminal.write(
                        "[Agent] Cancelling active run...",
                        style="warning",
                    )
                    cancellation_announced = True

    def _wait_once(self, future: Future[_T]) -> _T:
        return future.result(timeout=_POLL_SECONDS)

    def _display_outcome(self, result: ShellRunOutcome) -> None:
        self._last_outcome = result
        if result.status == "completed" and result.passed:
            self._terminal.write(f"[Done] {result.html_path}", style="success")
            self._terminal.write(f"[Report] {result.report_path}", style="muted")
            self._terminal.write(f"[Trace] {result.trace_path}", style="muted")
            return
        if result.status == "cancelled":
            self._terminal.write("[Cancelled]", style="warning")
            return
        if result.status == "pending_approval":
            approval_id = result.pending_approval_id or "approval"
            self._terminal.write(
                f"[Pending approval] {approval_id}",
                style="approval",
            )
            return
        self._terminal.write("[Failed] Run did not pass the final Gate.", style="error")

    def _offer_connection_test(self) -> None:
        self._terminal.write(
            "连接测试可能产生少量 API 费用。",
            style="warning",
        )
        if not self._read_yes_no("是否运行连接测试？[y/N] ", default=False):
            return
        token = EventCancellationToken()
        try:
            result = self._execute_active(
                lambda: self._runtime.test_connection(token),
                token,
            )
        except RunCancelled:
            self._terminal.write("[Cancelled] Connection test", style="warning")
            return
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._write_error("Connection test failed", exc)
            return
        if result.ok:
            self._terminal.write("Connection test passed.", style="success")
        else:
            self._terminal.write(
                f"Connection test failed: {self._safe_text(result.code)}",
                style="error",
            )

    def _handle_external_approvals(self) -> None:
        try:
            approvals = tuple(self._pending_approvals())
            if not approvals:
                root = self._runtime.workspace
                self._terminal.write(
                    "No pending approvals. /approvals only lists unresolved approvals.",
                    style="muted",
                )
                self._terminal.write(
                    f"Completed-run report: "
                    f"{(root / 'reports' / 'latest' / 'index.html').resolve()}",
                    style="muted",
                )
                self._terminal.write(
                    f"Completed-run trace: "
                    f"{(root / 'runs' / 'latest' / 'trace.jsonl').resolve()}",
                    style="muted",
                )
                return
            for approval in approvals:
                path = "" if approval.path is None else f" {approval.path}"
                self._terminal.write(
                    f"[Approval] {self._safe_text(approval.id)} "
                    f"{self._safe_text(approval.action)}{self._safe_text(path)} "
                    f"({self._safe_text(approval.risk_level)}): "
                    f"{self._safe_text(approval.reason)}",
                    style="approval",
                )
            selected = self._terminal.read("Approval ID: ").strip()
            choices = {approval.id for approval in approvals}
            if selected not in choices:
                self._terminal.write("Unknown pending approval ID.", style="error")
                return
            approved = self._read_yes_no("Approve? [y/N]: ", default=False)
            decision = "approved" if approved else "denied"
            reason = None if approved else "human denied"
            self._decide_external(selected, decision=decision, reason=reason)
            self._terminal.write(
                f"Approval {self._safe_text(selected)} {decision}.",
                style="success" if approved else "warning",
            )
            self._terminal.write(
                "Use specgate resume to continue a run left by another process.",
                style="muted",
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._write_error("Could not update approvals", exc)

    def _pending_approvals(self) -> tuple[PendingApprovalView, ...]:
        method = getattr(self._runtime, "pending_approvals", None)
        if callable(method):
            return tuple(method())
        root = self._runtime.workspace
        queue = read_approval_queue_if_present(root, approval_queue_path(root))
        if queue is None:
            return ()
        return tuple(
            approval
            for approval in queue.approvals
            if approval.status == "pending"
        )

    def _decide_external(
        self,
        approval_id: str,
        *,
        decision: str,
        reason: str | None,
    ) -> None:
        method = getattr(self._runtime, "decide_external", None)
        if callable(method):
            method(approval_id, decision=decision, reason=reason)
            return
        store = ApprovalStore(approval_queue_path(self._runtime.workspace))
        queue = store.read_existing()
        approval = queue.find(approval_id)
        if approval.status != "pending":
            raise ValueError("approval_not_pending")
        store.decide(
            approval_id,
            decision,
            expected_revision=queue.revision,
            decided_at=_utc_now(),
            reason=reason,
        )

    def _print_last_status(self) -> None:
        if self._last_outcome is None:
            self._terminal.write("Last run: none", style="muted")
            return
        self._terminal.write(
            f"Last run: {self._safe_text(self._last_outcome.status)} "
            f"({self._safe_text(self._last_outcome.run_id)})",
            style="muted",
        )

    def _read_yes_no(self, prompt: str, *, default: bool) -> bool:
        while True:
            value = self._terminal.read(prompt).strip().lower()
            if not value:
                return default
            if value in {"y", "yes"}:
                return True
            if value in {"n", "no"}:
                return False
            self._terminal.write("Please enter yes or no.", style="warning")

    def _write_error(self, prefix: str, error: BaseException) -> None:
        self._terminal.write(
            f"[Failed] {prefix}: {self._safe_text(error)}",
            style="error",
        )

    @staticmethod
    def _safe_text(value: object) -> str:
        safe = str(redact(str(value)))
        normalized = " ".join(safe.split())
        return normalized[:220] if normalized else "unknown_error"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
