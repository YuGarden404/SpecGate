from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import specgate.workspace_fs as workspace_fs
from specgate.approvals import ApprovalStore, GovernanceConfig, approval_queue_path
from specgate.config import WorkspaceConfig, load_workspace_config
from specgate.context_lifecycle import CompressionConfig
from specgate.credential_store import KeyringCredentialStore
from specgate.gate import GateResult
from specgate.llm import LLMClient, LLMProviderError, MockLLM, OpenAICompatibleLLM
from specgate.llm_transport import (
    LLMEndpointPolicy,
    LLMTransportError,
    PublicDNSResolver,
    SafeHTTPSChatTransport,
)
from specgate.policy import WorkspacePolicy
from specgate.report import generate_report
from specgate.retrieval import RetrievalConfig
from specgate.runner import AgentRunner, RunResult
from specgate.runtime_events import RunEventSink
from specgate.user_config import UserShellConfig


_CONNECTION_ERROR_CODES = frozenset(
    {
        "llm_authentication_failed",
        "llm_provider_unavailable",
        "llm_rate_limited",
        "llm_request_rejected",
        "llm_request_timeout",
        "llm_response_invalid",
        "llm_redirect_forbidden",
        "llm_tls_failed",
        "llm_url_invalid",
        "llm_host_not_allowed",
        "llm_dns_resolution_failed",
        "llm_address_not_public",
    }
)


class ShellCancellationToken(Protocol):
    def check(self) -> None: ...

    def remaining_seconds(self) -> float: ...


class _NeverCancelled:
    def check(self) -> None:
        return None

    def remaining_seconds(self) -> float:
        return float("inf")


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    code: str


@dataclass(frozen=True)
class ShellRunOutcome:
    run_id: str
    status: str
    passed: bool
    pending_approval_id: str | None
    html_path: Path
    report_path: Path
    trace_path: Path


def _default_workspace_config(root: Path) -> WorkspaceConfig:
    return WorkspaceConfig(
        policy=WorkspacePolicy(
            root=root,
            allowed_actions={
                "write_file",
                "replace_file",
                "read_file",
                "list_files",
                "finish",
            },
            allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
            allowed_write_paths={"index.html"},
        ),
        governance=GovernanceConfig(),
    )


def _status_for(result: RunResult) -> str:
    if result.outcome == "needs_approval":
        return "pending_approval"
    if result.passed:
        return "completed"
    return "cancelled" if result.outcome == "cancelled" else "failed"


class SpecGateShellRuntime:
    def __init__(
        self,
        config_provider: UserShellConfig | Callable[[], UserShellConfig],
        *,
        llm_factory: Callable[..., LLMClient] | None = None,
        mock_llm_factory: Callable[[], LLMClient] | None = None,
        id_factory: Callable[[], str] | None = None,
        credential_reader: Callable[[str], str | None] | None = None,
        max_steps: int = 5,
        timeout: float = 60.0,
    ) -> None:
        self._config_provider = (
            config_provider
            if callable(config_provider)
            else lambda: config_provider
        )
        self._llm_factory = llm_factory
        self._mock_llm_factory = mock_llm_factory or (lambda: MockLLM([]))
        self._id_factory = id_factory or (lambda: uuid4().hex)
        self._credential_reader = (
            KeyringCredentialStore().get
            if credential_reader is None
            else credential_reader
        )
        self._max_steps = max_steps
        self._timeout = timeout
        self._resolver: PublicDNSResolver | None = None
        self._runners: dict[str, AgentRunner] = {}

    @property
    def workspace(self) -> Path:
        return self._resolve_workspace(self._config())

    def start(
        self,
        request: str,
        event_sink: RunEventSink,
        cancel_token: ShellCancellationToken,
    ) -> ShellRunOutcome:
        if self._runners:
            raise RuntimeError("approval_pending")
        if not isinstance(request, str) or not request.strip():
            raise ValueError("request_required")

        config = self._config()
        root = self._validate_workspace(config)
        settings = self._workspace_config(root)
        run_id = self._id_factory()
        llm = self._create_llm(config, cancel_token)
        runner = AgentRunner(
            root,
            llm,
            settings.policy,
            max_steps=self._max_steps,
            context_strategy=settings.context.strategy,
            governance_config=settings.governance,
            context_budget_chars=settings.context.budget_chars,
            retrieval_config=RetrievalConfig(
                top_k=settings.retrieval.top_k,
                chunk_lines=settings.retrieval.chunk_lines,
                chunk_overlap_lines=settings.retrieval.chunk_overlap_lines,
                max_chunk_chars=settings.retrieval.max_chunk_chars,
            ),
            compression_config=CompressionConfig(
                max_tool_result_chars=settings.compression.max_tool_result_chars
            ),
            stop_check=cancel_token.check,
            id_factory=lambda: run_id,
            event_sink=event_sink,
        )
        result = runner.run(task=request)
        outcome = self._outcome(root, run_id, result)
        if outcome.status == "pending_approval":
            self._runners[run_id] = runner
            return outcome
        return self._archive(outcome)

    def decide(
        self,
        pending: ShellRunOutcome,
        *,
        decision: str,
        reason: str | None,
    ) -> ShellRunOutcome:
        if pending.status != "pending_approval":
            raise ValueError("run_is_not_pending_approval")
        if decision not in {"approved", "denied"}:
            raise ValueError("invalid_approval_decision")
        approval_id = pending.pending_approval_id
        if approval_id is None:
            raise ValueError("pending_approval_id_required")
        try:
            runner = self._runners[pending.run_id]
        except KeyError as exc:
            raise ValueError("run_is_not_resumable_in_process") from exc

        store = ApprovalStore(runner.approval_queue_file)
        queue = store.read_existing()
        queue.find(approval_id)
        store.decide(
            approval_id,
            decision,
            expected_revision=queue.revision,
            decided_at=_utc_now(),
            reason=reason,
        )
        result = runner.resume_from_approval()
        root = pending.html_path.parent
        outcome = self._outcome(root, pending.run_id, result)
        if outcome.status == "pending_approval":
            return outcome
        self._runners.pop(pending.run_id, None)
        return self._archive(outcome)

    def test_connection(
        self,
        cancel_token: ShellCancellationToken | None = None,
    ) -> ConnectionTestResult:
        token = cancel_token or _NeverCancelled()
        try:
            llm = self._create_llm(self._config(), token)
            llm.complete(
                "Return exactly this strict JSON action: "
                '{"schema_version":"1","action":"finish",'
                '"args":{"summary":"connection test"}}'
            )
        except LLMProviderError as exc:
            code = (
                exc.code
                if exc.code in _CONNECTION_ERROR_CODES
                else "llm_provider_failed"
            )
            return ConnectionTestResult(False, code)
        return ConnectionTestResult(True, "ok")

    def close(self) -> None:
        resolver = self._resolver
        self._resolver = None
        if resolver is not None:
            resolver.shutdown()

    def _config(self) -> UserShellConfig:
        config = self._config_provider()
        if not isinstance(config, UserShellConfig):
            raise TypeError("shell_config_required")
        return config

    def _resolve_workspace(self, config: UserShellConfig) -> Path:
        if config.workspace is None:
            raise ValueError("workspace_not_configured")
        try:
            root = Path(config.workspace).expanduser().resolve(strict=True)
        except OSError as exc:
            raise ValueError("workspace_unavailable") from exc
        if not root.is_dir():
            raise ValueError("workspace_not_directory")
        return root

    def _validate_workspace(self, config: UserShellConfig) -> Path:
        root = self._resolve_workspace(config)
        for name, code in (
            ("TASK_SPEC.md", "workspace_missing_task_spec"),
            ("CHECKLIST.md", "workspace_missing_checklist"),
        ):
            try:
                content = workspace_fs.read_optional_workspace_text(root, name)
            except (OSError, UnicodeError, workspace_fs.WorkspacePathError) as exc:
                raise ValueError(code) from exc
            if content is None:
                raise ValueError(code)
        return root

    def _workspace_config(self, root: Path) -> WorkspaceConfig:
        config_path = root / "specgate.toml"
        return (
            load_workspace_config(config_path)
            if config_path.is_file()
            else _default_workspace_config(root)
        )

    def _create_llm(
        self,
        config: UserShellConfig,
        cancel_token: ShellCancellationToken,
    ) -> LLMClient:
        if config.mode == "mock":
            return self._mock_llm_factory()
        if config.llm is None:
            raise ValueError("llm_config_not_configured")
        credential = self._credential_reader(config.llm.provider)
        if not credential:
            raise ValueError("credential_not_configured")
        kwargs = {
            "base_url": config.llm.base_url,
            "api_key": credential,
            "model": config.llm.model,
            "timeout": self._timeout,
            "stop_check": cancel_token.check,
            "remaining_seconds": cancel_token.remaining_seconds,
        }
        if self._llm_factory is not None:
            return self._llm_factory(**kwargs)
        return self._default_real_llm(**kwargs)

    def _default_real_llm(self, **kwargs) -> OpenAICompatibleLLM:
        raw_url = kwargs["base_url"]
        try:
            parsed = urlsplit(raw_url)
            host = parsed.hostname
            port = parsed.port or 443
        except (TypeError, ValueError) as exc:
            raise LLMProviderError("llm_url_invalid") from exc
        if host is None:
            raise LLMProviderError("llm_url_invalid")
        authority = host if port == 443 else f"{host}:{port}"
        try:
            policy = LLMEndpointPolicy.from_csv(authority)
            endpoint = policy.normalize(raw_url)
        except (TypeError, ValueError) as exc:
            raise LLMProviderError("llm_url_invalid") from exc
        except LLMTransportError as exc:
            raise LLMProviderError(exc.code) from exc

        if self._resolver is None:
            self._resolver = PublicDNSResolver()
        transport = SafeHTTPSChatTransport(
            resolver=self._resolver,
            request_timeout_seconds=kwargs["timeout"],
        )
        return OpenAICompatibleLLM(
            base_url=endpoint.base_url,
            api_key=kwargs["api_key"],
            model=kwargs["model"],
            timeout=kwargs["timeout"],
            endpoint=endpoint,
            transport=transport,
            stop_check=kwargs["stop_check"],
            remaining_seconds=kwargs["remaining_seconds"],
        )

    def _outcome(
        self,
        root: Path,
        run_id: str,
        result: RunResult,
    ) -> ShellRunOutcome:
        status = _status_for(result)
        gate = result.final_gate or GateResult(
            False,
            [],
            [],
            f"Run {status.replace('_', ' ')}",
        )
        generate_report(
            root,
            gate,
            result.steps,
            metrics=result.metrics,
            permission_decisions=result.permission_decisions,
            trust=result.trust,
            profile=result.profile,
        )
        return ShellRunOutcome(
            run_id=run_id,
            status=status,
            passed=result.passed,
            pending_approval_id=result.pending_approval_id,
            html_path=root.joinpath("index.html").resolve(),
            report_path=root.joinpath("reports", "latest", "index.html").resolve(),
            trace_path=root.joinpath("runs", "latest", "trace.jsonl").resolve(),
        )

    def _archive(self, outcome: ShellRunOutcome) -> ShellRunOutcome:
        root = outcome.html_path.parent
        run_archive = root / "runs" / outcome.run_id
        report_archive = root / "reports" / outcome.run_id
        workspace_fs.copy_workspace_tree(root / "runs" / "latest", run_archive)
        workspace_fs.copy_workspace_tree(root / "reports" / "latest", report_archive)
        return ShellRunOutcome(
            run_id=outcome.run_id,
            status=outcome.status,
            passed=outcome.passed,
            pending_approval_id=outcome.pending_approval_id,
            html_path=outcome.html_path,
            report_path=report_archive.joinpath("index.html").resolve(),
            trace_path=run_archive.joinpath("trace.jsonl").resolve(),
        )


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
