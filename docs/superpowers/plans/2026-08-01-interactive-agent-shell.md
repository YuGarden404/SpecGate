# Interactive Agent Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v0.3.0 interactive `SpecGate >>` Shell while keeping each natural-language request inside the existing AgentService, Governance, approval, Gate, Trace, Memory, and workspace-safety boundaries.

**Architecture:** Bare `specgate` starts an `InteractiveShell`; explicit v0.2.0 subcommands remain unchanged. The Shell delegates configuration, terminal I/O, event rendering, and runtime execution to focused collaborators. Each prompt creates one task-aware AgentRun, streams redacted structured events, handles approval through the existing resume service, and archives per-run evidence before returning to the prompt.

**Tech Stack:** Python 3.11+, `argparse`, `unittest`, `prompt-toolkit>=3.0,<4`, existing Pydantic Action Protocol, AgentService, Runtime Events, OS keyring, `httpx`/OpenAI-compatible transport, Workspace FS, HTML Gate.

---

## Scope And File Map

Create these focused modules:

- `src/specgate/shell_terminal.py`: terminal protocol and `prompt-toolkit` implementation only.
- `src/specgate/shell_renderer.py`: redacted `RunEvent` to terminal-line mapping only.
- `src/specgate/shell_config.py`: setup wizard, status rendering, and persistent configuration mutations.
- `src/specgate/shell_runtime.py`: one-run construction, approval resume, report generation, and evidence archiving.
- `src/specgate/interactive_shell.py`: input classification, slash-command dispatch, cancellable REPL, and lifecycle.
- `tests/test_shell_terminal.py`: terminal color, secret input, and history behavior.
- `tests/test_shell_renderer.py`: event mapping, verbosity, fallback, and secret redaction.
- `tests/test_shell_config.py`: setup and command behavior with fake terminal/keyring.
- `tests/test_shell_runtime.py`: AgentRunner integration, approval, connection test, and evidence paths.
- `tests/test_interactive_shell.py`: REPL, Mock confirmation, cancellation, and exit behavior.
- `tests/shell_support.py`: shared scripted terminal, event sink, and cancellation test doubles; it contains no test cases.

Modify these existing boundaries:

- `src/specgate/user_config.py`, `tests/test_user_config.py`: schema v1-to-v2 migration and Shell settings.
- `src/specgate/context.py`, `tests/test_context.py`: ephemeral `UserRequestContextContributor`.
- `src/specgate/runtime_events.py`, `tests/test_runtime_events.py`: redacting fail-open fan-out sink.
- `src/specgate/action_pipeline.py`, `tests/test_action_pipeline.py`: structured Governance events.
- `src/specgate/agent_service.py`, `src/specgate/runner.py`, `tests/test_agent_service.py`, `tests/test_runner.py`: task-aware run, external event sink, aligned run ID, cancellation, and result identity.
- `src/specgate/cli.py`, `tests/test_cli.py`: bare-entry dispatch and Shell wiring.
- `pyproject.toml`, `src/specgate/__init__.py`, `tests/test_imports.py`: dependency and v0.3.0 version.
- `README.md`, `SPEC.md`, `SPEC_PROCESS.md`, `PLAN.md`, `AGENT_LOG.md`, `tests/test_final_evidence.py`: user workflow and course evidence.

The plan deliberately does not add a new Agent Loop, action dispatcher, approval state machine, Gate, raw prompt-history store, or plaintext credential fallback.

Naming alignment with the approved design is explicit: `ShellConfigController` is the concrete `ShellSetup` component. `ShellApprovalPrompt` is implemented as the private `_prompt_for_approval()` behavior of `InteractiveShell`, because it has no independent state or dependency beyond the terminal and the current `ShellRunOutcome`; it is still tested separately through inline and `/approvals` flows.

## Pre-Execution Documentation Checkpoint

The approved design and this plan are intentionally left uncommitted for user review. Before implementation, the user records them with:

```powershell
git add -- `
  docs/superpowers/specs/2026-08-01-interactive-agent-shell-design.md `
  docs/superpowers/plans/2026-08-01-interactive-agent-shell.md
git diff --cached --check
git commit -m "docs: design SpecGate v0.3.0 interactive shell"
```

### Task 1: Add Backward-Compatible Shell Settings

**Files:**
- Modify: `src/specgate/user_config.py:12-108`
- Modify: `src/specgate/cli.py:788-846`
- Test: `tests/test_user_config.py`
- Test: `tests/test_cli.py:703-845`

- [ ] **Step 1: Write schema migration and secret-boundary tests**

Add tests that assert v1 loads as real mode, v2 round-trips Shell fields, Mock mode may retain no LLM defaults, and saving legacy LLM defaults preserves Shell fields:

```python
def test_schema_v1_migrates_to_real_shell_defaults(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({
            "schema_version": 1,
            "provider": "openai-compatible",
            "base_url": "https://api.test/v1",
            "model": "model-v1",
        }), encoding="utf-8")

        config = load_user_shell_config(path=path)

        self.assertEqual(config.mode, "real")
        self.assertIsNone(config.workspace)
        self.assertFalse(config.verbose)
        self.assertEqual(config.llm.model, "model-v1")

def test_schema_v2_round_trip_contains_no_secret(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        config = UserShellConfig(
            mode="mock",
            workspace="D:/work/site",
            verbose=True,
            llm=None,
        )

        save_user_shell_config(config, path=path)

        self.assertEqual(load_user_shell_config(path=path), config)
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn("api_key", raw.lower())
        self.assertNotIn("secret", raw.lower())

def test_saving_llm_defaults_preserves_shell_preferences(self):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        save_user_shell_config(UserShellConfig(
            mode="mock", workspace="D:/work/site", verbose=True, llm=None
        ), path=path)

        save_user_llm_config(UserLLMConfig(
            "openai-compatible", "https://api.test/v1", "model-v2"
        ), path=path)

        saved = load_user_shell_config(path=path)
        self.assertEqual((saved.mode, saved.workspace, saved.verbose), (
            "mock", "D:/work/site", True
        ))
        self.assertEqual(saved.llm.model, "model-v2")
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
python -m unittest discover -s tests -p "test_user_config.py" -v
```

Expected: FAIL because `UserShellConfig`, `load_user_shell_config`, and `save_user_shell_config` do not exist.

- [ ] **Step 3: Implement schema v2 and v1 migration**

Add the following public model and keep `UserLLMConfig` unchanged for existing callers:

```python
SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
SHELL_MODES = frozenset({"mock", "real"})

@dataclass(frozen=True)
class UserShellConfig:
    mode: str
    workspace: str | None
    verbose: bool
    llm: UserLLMConfig | None

    def __post_init__(self) -> None:
        if self.mode not in SHELL_MODES:
            raise UserConfigError("invalid user config: mode")
        if self.workspace is not None:
            _config_value("workspace", self.workspace)
        if type(self.verbose) is not bool:
            raise UserConfigError("invalid user config: verbose")
```

Implement `_shell_from_payload()` with two exact accepted key sets. Schema v1 maps to `UserShellConfig("real", None, False, llm)`. Schema v2 accepts only `schema_version`, `provider`, `base_url`, `model`, `mode`, `workspace`, and `verbose`; the three LLM fields are either all strings or all `None`. Write schema v2 atomically with the current `NamedTemporaryFile` plus `os.replace` sequence.

Make existing APIs delegate without changing their external signatures:

```python
def load_user_llm_config(*, path: Path | None = None) -> UserLLMConfig | None:
    shell = load_user_shell_config(path=path)
    return None if shell is None else shell.llm

def save_user_llm_config(config: UserLLMConfig, *, path: Path | None = None) -> None:
    target = user_config_path() if path is None else path
    current = load_user_shell_config(path=target)
    shell = current or UserShellConfig("real", None, False, None)
    save_user_shell_config(replace(shell, llm=config), path=target)
```

Import `replace` from `dataclasses`. Update `configure_user()` to use these APIs so existing `/configure` behavior and environment-variable priority remain unchanged.

- [ ] **Step 4: Run configuration and CLI regression tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_user_config.py" -v
python -m unittest discover -s tests -p "test_cli.py" -v
```

Expected: PASS; configuration files contain no secret and existing `specgate configure` tests still pass.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/user_config.py src/specgate/cli.py tests/test_user_config.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: extend user config for interactive shell"
```

### Task 2: Add A Testable Terminal Adapter

**Files:**
- Create: `src/specgate/shell_terminal.py`
- Create: `tests/test_shell_terminal.py`
- Create: `tests/shell_support.py`
- Modify: `pyproject.toml:10-19`
- Modify: `tests/test_imports.py`

- [ ] **Step 1: Write terminal contract tests**

```python
class FakeSession:
    def __init__(self):
        self.calls = []

    def prompt(self, message, *, is_password=False):
        self.calls.append((message, is_password))
        return "secret-value" if is_password else "answer"

class ShellTerminalTests(unittest.TestCase):
    def test_color_requires_tty_and_honors_no_color(self):
        self.assertTrue(color_enabled(is_tty=True, environ={}))
        self.assertFalse(color_enabled(is_tty=False, environ={}))
        self.assertFalse(color_enabled(is_tty=True, environ={"NO_COLOR": "1"}))

    def test_secret_prompt_uses_password_mode_and_not_history(self):
        session = FakeSession()
        secret_session = FakeSession()
        terminal = PromptToolkitTerminal(
            session=session,
            secret_session=secret_session,
            is_tty=True,
            environ={},
        )

        self.assertEqual(terminal.read("API key: ", secret=True), "secret-value")

        self.assertEqual(session.calls, [])
        self.assertEqual(secret_session.calls, [("API key: ", True)])
```

- [ ] **Step 2: Run the focused test and verify failure**

Run: `python -m unittest discover -s tests -p "test_shell_terminal.py" -v`

Expected: FAIL because `specgate.shell_terminal` does not exist.

- [ ] **Step 3: Declare the dependency and implement the adapter**

Add `"prompt-toolkit>=3.0,<4"` to `project.dependencies` and assert it in `RuntimeDependencyTests`.

Implement this injectable contract:

```python
class ShellTerminal(Protocol):
    def read(self, prompt: str, *, secret: bool = False) -> str: ...
    def write(self, text: str, *, style: str | None = None) -> None: ...
    def clear(self) -> None: ...

def color_enabled(*, is_tty: bool, environ: Mapping[str, str]) -> bool:
    return is_tty and "NO_COLOR" not in environ

class PromptToolkitTerminal:
    def __init__(
        self,
        *,
        session=None,
        secret_session=None,
        output=None,
        is_tty=None,
        environ=None,
    ):
        values = os.environ if environ is None else environ
        self._session = session or PromptSession(history=InMemoryHistory())
        self._secret_session = secret_session or PromptSession(history=DummyHistory())
        self._output = output
        detected_tty = sys.stdout.isatty() if is_tty is None else is_tty
        self._color = color_enabled(is_tty=detected_tty, environ=values)
        self._lock = Lock()

    def read(self, prompt: str, *, secret: bool = False) -> str:
        session = self._secret_session if secret else self._session
        return session.prompt(prompt, is_password=secret)

    def write(self, text: str, *, style: str | None = None) -> None:
        rendered = _ansi(text, style) if self._color else text
        with self._lock:
            print_formatted_text(ANSI(rendered), output=self._output)

    def clear(self) -> None:
        clear()
```

Map only the approved categories and prompt color; do not add animation or persist `FileHistory`. Import `DummyHistory` and route password prompts through the separate secret session so their contents can never enter `InMemoryHistory`.

Create the shared test doubles used by later tasks:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ReadCall:
    prompt: str
    secret: bool

class ScriptedTerminal:
    def __init__(self, inputs):
        self.inputs = list(inputs)
        self.read_calls = []
        self.lines = []
        self.clear_calls = 0

    @property
    def output(self):
        return "\n".join(self.lines)

    def read(self, prompt, *, secret=False):
        self.read_calls.append(ReadCall(prompt, secret))
        value = self.inputs.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    def write(self, text, *, style=None):
        del style
        self.lines.append(text)

    def clear(self):
        self.clear_calls += 1

class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        self.events.append((context, event_type, payload, step, phase))

class FailingSink:
    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        del context, event_type, payload, step, phase
        raise RuntimeError("observer failed")

class NeverCancelled:
    def check(self):
        return None

    def remaining_seconds(self):
        return float("inf")
```

Later Shell tests import these names with `from shell_support import FailingSink, NeverCancelled, RecordingSink, ScriptedTerminal`; do not duplicate or import production behavior into the fakes.

- [ ] **Step 4: Run terminal and dependency tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_shell_terminal.py" -v
python -m unittest discover -s tests -p "test_imports.py" -v
```

Expected: PASS.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- pyproject.toml src/specgate/shell_terminal.py tests/shell_support.py tests/test_shell_terminal.py tests/test_imports.py
git diff --cached --check
git commit -m "feat: add interactive terminal adapter"
```

### Task 3: Inject Each User Request Into Existing Context

**Files:**
- Modify: `src/specgate/context.py:39-79`
- Modify: `src/specgate/runner.py:1213-1252,1445-1513,2028-2187,2308-2309`
- Modify: `src/specgate/agent_service.py:751-891`
- Test: `tests/test_context.py`
- Test: `tests/test_runner.py`
- Test: `tests/test_agent_service.py`

- [ ] **Step 1: Write contributor and one-request-per-run tests**

```python
def test_user_request_contributor_renders_redacted_ephemeral_section(self):
    contributor = UserRequestContextContributor(
        "Please update index.html using sk-secret-1234567890"
    )

    title, content = contributor.render(RunState("run-1"))

    self.assertEqual(title, "User Request")
    self.assertIn("Please update index.html", content)
    self.assertNotIn("sk-secret", content)

def test_agent_runner_passes_explicit_task_to_context_and_returns_run_id(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = make_workspace(Path(tmp))
        llm = RecordingFinishLLM()
        runner = AgentRunner(root, llm, finish_only_policy(root), max_steps=1)

        result = runner.run(task="Modify the existing index.html")

        self.assertTrue(result.run_id)
        self.assertIn("## User Request\nModify the existing index.html", llm.contexts[0])
```

Retain the existing no-argument `runner.run()` regression test and assert it still uses `"Execute the configured workspace task."`.

- [ ] **Step 2: Run context and runner tests and verify failure**

Run:

```powershell
python -m unittest discover -s tests -p "test_context.py" -v
python -m unittest discover -s tests -p "test_runner.py" -v
```

Expected: FAIL because the contributor, task argument, and `RunResult.run_id` are absent.

- [ ] **Step 3: Implement the contributor and task-aware runner path**

Add:

```python
MAX_USER_REQUEST_CHARS = 8192

@dataclass(frozen=True)
class UserRequestContextContributor:
    request: str

    def __post_init__(self) -> None:
        normalized = self.request.strip()
        if not normalized or len(normalized) > MAX_USER_REQUEST_CHARS:
            raise ValueError("user request must contain 1 to 8192 characters")

    def render(self, state: RunState) -> tuple[str, str]:
        del state
        return "User Request", str(redact(self.request.strip()))
```

Add `run_id: str | None = None` as the final defaulted field on `RunResult`. Change `AgentRunner.run` and `_run_configured_service` to accept an optional task. Preserve the existing payload conversion, add `run_id=result.run_id`, and install the contributor before `service.run`:

```python
DEFAULT_AGENT_TASK = "Execute the configured workspace task."

def _run_configured_service(service: AgentService, task: str | None = None) -> RunResult:
    definition = getattr(service, "_specgate_default_definition", None)
    token = getattr(service, "_specgate_cancel_token", None)
    if definition is None or token is None:
        raise TypeError("AgentService is missing its default run configuration")
    resolved_task = DEFAULT_AGENT_TASK if task is None else task
    runtime = _configured_runtime(service)
    runtime.context_contributors = (
        () if task is None else (UserRequestContextContributor(task),)
    )
    result = service.run(definition, resolved_task, cancel_token=token)
    payload = next(
        item.payload
        for item in reversed(result.state.observations)
        if item.kind == "run_result"
    )
    return RunResult(
        passed=bool(payload.get("passed", False)),
        steps=result.state.step,
        final_gate=result.state.latest_gate,
        context_chars_max=result.state.metrics.context_chars_max,
        metrics=result.state.metrics,
        permission_decisions=[
            PermissionDecision(**item)
            for item in payload.get("permission_decisions", [])
        ],
        trust=_trust_from_payload(payload.get("trust")),
        profile=str(payload.get("profile", "strict")),
        outcome=str(payload.get("outcome", result.state.status.value)),
        pending_approval_id=result.state.pending_approval_id,
        run_id=result.run_id,
    )
```

Extract the existing trust conversion at lines 2197-2205 into `_trust_from_payload(payload: object) -> TrustSummary | None`; it returns `None` for non-dicts and otherwise constructs `TrustSummary(str(payload.get("status", "failed")), list(payload.get("reasons", [])))`. Add `context_contributors` to `_RunnerRuntime` and pass it into every single-agent `LegacyContextBuilder`. Preserve role-specific Artifact contributors by appending rather than replacing them in multi-agent paths.

Before starting an explicit task, append only a bounded redacted summary to the current Trace:

```python
def _request_summary(task: str) -> str:
    single_line = " ".join(task.split())
    return str(redact(single_line[:160]))

if task is not None:
    runtime.trace.append(
        "user_request_received",
        {"summary": _request_summary(task), "request_chars": len(task)},
    )
```

Add a test with a request longer than 160 characters containing a key sentinel; assert neither the full request nor the key sentinel appears in `trace.jsonl`.

Add an optional `id_factory` through `AgentRunner.__init__`, `AgentServiceFactory.build`, `build_resumable`, `_build`, `build_agent_service`, and `build_resumable_agent_service`, then pass it to `AgentService`. Default `None` preserves all callers. `SpecGateShellRuntime` supplies one generated ID to both the runner factory and its evidence archive; explicit legacy CLI calls continue using the AgentService default UUID factory.

- [ ] **Step 4: Run focused and service contract tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_context.py" -v
python -m unittest discover -s tests -p "test_agent_service.py" -v
python -m unittest discover -s tests -p "test_runner.py" -v
```

Expected: PASS; each explicit task appears only in its own context, and no task text is added to the persisted AgentService state file.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/context.py src/specgate/runner.py src/specgate/agent_service.py tests/test_context.py tests/test_runner.py tests/test_agent_service.py
git diff --cached --check
git commit -m "feat: inject ephemeral shell requests into agent context"
```

### Task 4: Fan Out Redacted Runtime And Governance Events

**Files:**
- Modify: `src/specgate/runtime_events.py`
- Modify: `src/specgate/action_pipeline.py:82-99,100-174`
- Modify: `src/specgate/agent_service.py:751-891`
- Modify: `src/specgate/runner.py:166-196,1213-1252,1464,2066-2101`
- Test: `tests/test_runtime_events.py`
- Test: `tests/test_action_pipeline.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write redaction, observer-failure, and Governance event tests**

```python
def test_fanout_redacts_once_and_observer_failure_does_not_block_primary(self):
    primary = RecordingSink()
    observer = FailingSink()
    errors = []
    sink = FanoutRunEventSink(primary, (observer,), errors.append)

    sink.emit(self.context, "ToolCompleted", {"token": "sk-secret-1234567890"})

    self.assertEqual(len(primary.events), 1)
    self.assertNotIn("sk-secret", str(primary.events[0]))
    self.assertEqual(len(errors), 1)

def test_pipeline_emits_governance_allowed_before_tool_execution(self):
    sink = RecordingSink()
    pipeline = make_pipeline(event_sink=sink, governance=AllowingGovernance())

    pipeline.execute(write_action(), execution_context())

    event = next(item for item in sink.events if item[1] == "GovernanceEvaluated")
    self.assertEqual(event[2]["decision"], "allowed")
    self.assertEqual(event[2]["action"], "write_file")
```

Add blocked and approval-required variants; assert payloads expose action/path/code only and never tool content.

Add an approval event assertion:

```python
approval_event = next(
    item for item in sink.events if item[1] == "ApprovalRequested"
)
self.assertEqual(approval_event[2]["approval_id"], "approval-1")
self.assertEqual(approval_event[2]["action"], "write_file")
self.assertNotIn("action_payload", approval_event[2])
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
python -m unittest discover -s tests -p "test_runtime_events.py" -v
python -m unittest discover -s tests -p "test_action_pipeline.py" -v
```

Expected: FAIL because fan-out and `GovernanceEvaluated` do not exist.

- [ ] **Step 3: Implement fail-open fan-out and structured decisions**

Add:

```python
class FanoutRunEventSink:
    def __init__(self, primary, observers=(), on_observer_error=None):
        self._primary = primary
        self._observers = tuple(observers)
        self._on_observer_error = on_observer_error or (lambda error: None)

    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        safe_payload = redact(deepcopy(payload))
        self._primary.emit(
            context, event_type, deepcopy(safe_payload), step=step, phase=phase
        )
        for observer in self._observers:
            try:
                observer.emit(
                    context, event_type, deepcopy(safe_payload), step=step, phase=phase
                )
            except Exception as exc:
                self._on_observer_error(exc)

class NullRunEventSink:
    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        del context, event_type, payload, step, phase
```

Extend `ActionPipeline.__init__` with optional `event_sink`. Emit `GovernanceEvaluated` immediately after evaluation and before any tool execution:

```python
self._event_sink.emit(
    context.event_context,
    "GovernanceEvaluated",
    {
        "action": call.definition.name,
        "path": call.args.model_dump(mode="python").get("path"),
        "decision": governance_decision.kind.value,
        "code": governance_decision.code,
        "rule_family": governance_decision.rule_family,
    },
    step=context.step,
    phase="governance",
)
```

For hook- or Governance-required approval, build `_approval_outcome` once, emit `ApprovalRequested` from its `approval_request` using only `approval_id`, `action`, `path`, `risk_level`, and redacted `reason`, then return that outcome. Never emit `action_payload` or file content.

Use a `NullRunEventSink` default to preserve existing constructors. Extend `_LegacyRunEventSink` with an optional observer and use `FanoutRunEventSink(TraceRunEventSink(trace), observers)`. Add optional `event_sink: RunEventSink | None = None` parameters to `AgentRunner.__init__`, `AgentServiceFactory`, `build_agent_service`, and `build_resumable_agent_service`; thread the value through `_ConfiguredRuntimeFactory` and `_RunnerRuntime`, then pass the resulting sink into every `ActionPipeline`.

- [ ] **Step 4: Verify Runtime Event and runner integration**

Run:

```powershell
python -m unittest discover -s tests -p "test_runtime_events.py" -v
python -m unittest discover -s tests -p "test_action_pipeline.py" -v
python -m unittest discover -s tests -p "test_runner.py" -v
```

Expected: PASS; renderer-observer failure cannot prevent Trace writes or tool execution.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/runtime_events.py src/specgate/action_pipeline.py src/specgate/runner.py src/specgate/agent_service.py tests/test_runtime_events.py tests/test_action_pipeline.py tests/test_runner.py
git diff --cached --check
git commit -m "feat: expose redacted runtime events to shell observers"
```

### Task 5: Render Concise And Verbose Progress

**Files:**
- Create: `src/specgate/shell_renderer.py`
- Create: `tests/test_shell_renderer.py`

- [ ] **Step 1: Write event mapping and leakage tests**

```python
def test_renderer_maps_core_events_without_raw_payloads(self):
    terminal = ScriptedTerminal([])
    renderer = ShellEventRenderer(terminal, verbose=False)
    context = RunEventContext("run-1", "agent-1")

    renderer.emit(context, "ContextBuilt", {"selected_files": ["TASK_SPEC.md"]})
    renderer.emit(context, "GovernanceEvaluated", {
        "action": "write_file", "path": "index.html", "decision": "allow"
    })
    renderer.emit(context, "GateCompleted", {
        "passed": True, "summary": "all checks passed"
    })

    output = "\n".join(terminal.lines)
    self.assertIn("[Context]", output)
    self.assertIn("[Governance]", output)
    self.assertIn("[Gate] Passed", output)

def test_renderer_redacts_secrets_and_verbose_never_prints_raw_content(self):
    terminal = ScriptedTerminal([])
    renderer = ShellEventRenderer(terminal, verbose=True)

    renderer.emit(RunEventContext("run-1", "agent-1"), "ToolCompleted", {
        "action": "write_file",
        "path": "index.html",
        "content": "sk-secret-1234567890",
    })

    output = "\n".join(terminal.lines)
    self.assertNotIn("sk-secret", output)
    self.assertNotIn("content", output)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest discover -s tests -p "test_shell_renderer.py" -v`

Expected: FAIL because the renderer module does not exist.

- [ ] **Step 3: Implement a whitelist renderer**

Define a fixed mapping and select only allowed keys:

```python
EVENT_CATEGORY = {
    "RunStarted": "Agent",
    "ContextBuilt": "Context",
    "LLMCompleted": "Agent",
    "GovernanceEvaluated": "Governance",
    "ToolCompleted": "Tool",
    "GateCompleted": "Gate",
    "ApprovalRequested": "Approval",
    "ApprovalClaimed": "Approval",
    "ApprovalApplied": "Approval",
    "ApprovalDenied": "Approval",
    "RunFinished": "Agent",
    "RunFailed": "Agent",
}

class ShellEventRenderer:
    def __init__(self, terminal: ShellTerminal, *, verbose: bool):
        self._terminal = terminal
        self._verbose = verbose

    def emit(self, context, event_type, payload, *, step=0, phase="runtime"):
        safe = redact(payload)
        line = render_event_line(event_type, safe)
        if line is not None:
            category = EVENT_CATEGORY[event_type]
            suffix = f" run={context.run_id} step={step} phase={phase}" if self._verbose else ""
            self._terminal.write(f"[{category}] {line}{suffix}", style=category.lower())
```

`render_event_line` must use event-specific allowlists. It may read `status`, `reason`, `action`, `path`, `decision`, `code`, `passed`, `summary`, and counts; it must ignore `content`, headers, messages, raw tool data, and unknown payload keys. Unknown event types are hidden unless verbose, where only event type, step, and phase are shown.

- [ ] **Step 4: Run renderer tests**

Run: `python -m unittest discover -s tests -p "test_shell_renderer.py" -v`

Expected: PASS.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/shell_renderer.py tests/test_shell_renderer.py
git diff --cached --check
git commit -m "feat: render redacted agent progress in terminal"
```

### Task 6: Build The Concrete Shell Runtime

**Files:**
- Create: `src/specgate/shell_runtime.py`
- Create: `tests/test_shell_runtime.py`
- Modify: `src/specgate/runner.py:1256-1260,1445-1464,2028-2040`

- [ ] **Step 1: Write run, archive, connection, and approval tests**

```python
def test_runtime_creates_independent_evidence_for_each_request(self):
    with temporary_workspace() as root:
        runtime = make_mock_shell_runtime(root)

        first = runtime.start("Generate the page", RecordingSink(), NeverCancelled())
        second = runtime.start("Modify the page", RecordingSink(), NeverCancelled())

        self.assertNotEqual(first.run_id, second.run_id)
        self.assertTrue(first.trace_path.is_file())
        self.assertTrue(first.report_path.is_file())
        self.assertTrue(second.trace_path.is_file())
        self.assertIn("User Request", runtime.recorded_contexts[1])

def test_connection_test_calls_model_without_creating_agent_run(self):
    llm = RecordingConnectionLLM()
    runtime = make_real_shell_runtime(llm=llm)

    result = runtime.test_connection()

    self.assertTrue(result.ok)
    self.assertEqual(llm.calls, 1)
    self.assertFalse(runtime.workspace.joinpath("runs").exists())

def test_decide_resumes_existing_pending_run(self):
    runtime = make_approval_shell_runtime()
    pending = runtime.start("Write index.html", RecordingSink(), NeverCancelled())

    completed = runtime.decide(pending, decision="approved", reason=None)

    self.assertEqual(completed.status, "completed")
    self.assertEqual(runtime.resume_calls, 1)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest discover -s tests -p "test_shell_runtime.py" -v`

Expected: FAIL because `specgate.shell_runtime` does not exist and `RunResult` lacks aligned identity.

- [ ] **Step 3: Align the configured runtime ID**

Change `_RunnerRuntime.run` to accept `run_id: str | None = None`, pass it to `_run_single_agent_loop`, and change `_ConfiguredRunLoop.run` to call `self._runtime.run(run_id=run_id)`. This removes the second generated legacy ID for configured single-agent runs while leaving direct legacy callers unchanged.

Expose these stable result types:

```python
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
```

Implement `SpecGateShellRuntime` with injected `llm_factory`, `mock_llm_factory`, `id_factory`, and credential reader. `start()` must:

1. validate `TASK_SPEC.md`, `CHECKLIST.md`, and workspace access;
2. create one cancellation-aware AgentRunner with the external event sink;
3. call `runner.run(task=request)` exactly once;
4. generate `reports/latest/index.html` using existing report code;
5. if terminal, archive `runs/latest` to `runs/<run_id>` and `reports/latest` to `reports/<run_id>` with `copy_workspace_tree`;
6. return absolute paths in `ShellRunOutcome`.

Use this terminal mapping:

```python
def _status_for(result: RunResult) -> str:
    if result.outcome == "needs_approval":
        return "pending_approval"
    if result.passed:
        return "completed"
    return "cancelled" if result.outcome == "cancelled" else "failed"
```

Extend the existing `VALID_RUN_OUTCOMES` and `_ConfiguredRunLoop` mapping to include `cancelled` and `timed_out`, preserving the `RunStatus` values produced by AgentLoop. In `_run_result_from_state`, return immediately for those two control states without running a final Gate, appending success Memory, or coercing the outcome to `failed`:

```python
if state.status in {RunStatus.CANCELLED, RunStatus.TIMED_OUT}:
    return RunResult(
        passed=False,
        steps=state.step,
        final_gate=state.latest_gate,
        context_chars_max=state.metrics.context_chars_max,
        metrics=state.metrics,
        permission_decisions=permission_decisions,
        trust=TrustSummary("failed", [state.status.value]),
        profile=self.governance_profile,
        outcome=state.status.value,
        run_id=state.run_id,
    )
```

`decide()` must update the existing `ApprovalStore` with its expected revision and call the same runner's `resume_from_approval()`. It must not execute an approved tool directly.

Keep only resumable in-process runners in a private `dict[str, AgentRunner]` keyed by `run_id`. `start()` inserts the runner only when the outcome is `pending_approval`; `decide()` removes it after a terminal result and archives evidence at that point. Starting a new prompt while an in-process approval is unresolved is disallowed by the synchronous REPL. `/approvals` may decide persisted external requests, but those are resumed through the existing explicit `specgate resume` path unless their runner is present in this map.

`test_connection()` calls `OpenAICompatibleLLM.complete()` with a minimal strict finish request and returns only a stable code derived from `LLMProviderError`; it does not create a runner, Trace, report, or Memory entry.

The concrete Real-mode factory must normalize the user-approved HTTPS endpoint, allow only that exact host and port through `LLMEndpointPolicy`, and construct `SafeHTTPSChatTransport(PublicDNSResolver(), request_timeout_seconds=timeout)`. Pass `cancel_token.check` and `cancel_token.remaining_seconds` into `OpenAICompatibleLLM`. `SpecGateShellRuntime.close()` shuts down its owned resolver; `InteractiveShell` calls `close()` in `finally`. This makes DNS, retries, response reads, and bounded network waits observe active cancellation without weakening the existing endpoint policy.

- [ ] **Step 4: Run runtime, runner, report, and approval tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_shell_runtime.py" -v
python -m unittest discover -s tests -p "test_runner.py" -v
python -m unittest discover -s tests -p "test_report.py" -v
python -m unittest discover -s tests -p "test_agent_service.py" -v
```

Expected: PASS; archived report links still resolve from `reports/<run_id>/index.html` to the workspace `index.html`.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/shell_runtime.py src/specgate/runner.py tests/test_shell_runtime.py tests/test_runner.py tests/test_report.py
git diff --cached --check
git commit -m "feat: add per-request shell runtime sessions"
```

### Task 7: Implement Setup And Core Configuration Commands

**Files:**
- Create: `src/specgate/shell_config.py`
- Create: `tests/test_shell_config.py`
- Modify: `src/specgate/user_config.py`

- [ ] **Step 1: Write setup, status, persistence, and keyring tests**

```python
def test_complete_config_skips_setup_and_prints_redacted_status(self):
    terminal = ScriptedTerminal([])
    controller = make_controller(terminal, complete_real_config())

    config = controller.ensure_ready()

    self.assertEqual(config.mode, "real")
    self.assertEqual(terminal.read_calls, [])
    self.assertIn("API key: securely configured", terminal.output)
    self.assertNotIn("sk-test-secret", terminal.output)

def test_api_key_command_uses_secret_input_and_preserves_old_key_on_failure(self):
    terminal = ScriptedTerminal(["new-secret"])
    store = FailingCredentialStore(existing="old-secret")
    controller = make_controller(terminal, complete_real_config(), store=store)

    result = controller.execute("api-key", None)

    self.assertFalse(result.ok)
    self.assertEqual(store.existing, "old-secret")
    self.assertEqual(terminal.read_calls[0].secret, True)
    self.assertNotIn("new-secret", terminal.output)

def test_invalid_workspace_does_not_replace_saved_workspace(self):
    controller = make_controller(ScriptedTerminal([]), complete_real_config())

    result = controller.execute("workspace", "D:/missing/path")

    self.assertFalse(result.ok)
    self.assertEqual(controller.config.workspace, "D:/valid/workspace")
```

Also cover `/mode mock`, `/mode real` with missing LLM fields, `/model`, `/url`, `/verbose on|off`, `/setup`, and environment credential source precedence.

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest discover -s tests -p "test_shell_config.py" -v`

Expected: FAIL because `specgate.shell_config` does not exist.

- [ ] **Step 3: Implement the configuration controller**

Use explicit result objects rather than integer codes:

```python
@dataclass(frozen=True)
class ConfigCommandResult:
    ok: bool
    config: UserShellConfig
    request_connection_test: bool = False

class ShellConfigController:
    def __init__(self, terminal, *, path=None, credential_store=None, environ=None):
        self._terminal = terminal
        self._path = user_config_path() if path is None else path
        self._credential_store = credential_store
        self._environ = os.environ if environ is None else environ
        self.config = load_user_shell_config(path=self._path)

    def ensure_ready(self) -> UserShellConfig:
        if self.config is None or not self._workspace_valid(self.config.workspace):
            return self.setup()
        if self.config.mode == "real" and not self._real_complete(self.config):
            return self.setup()
        self.print_status()
        return self.config
```

Use `dataclasses.replace` for one-field updates and call `save_user_shell_config` only after validation. `/url` must accept a normalized HTTPS Base URL without userinfo, query, or fragment. `/workspace` must resolve an existing accessible directory to an absolute path. `/api-key` calls `set_credential("openai-compatible", secret)` with an injected store; do not store the secret in controller fields or command history.

The complete command set is `help`, `status`, `setup`, `mode`, `workspace`, `model`, `url`, `api-key`, `verbose`, `approvals`, `clear`, and `exit`.

- [ ] **Step 4: Run configuration and credential regressions**

Run:

```powershell
python -m unittest discover -s tests -p "test_shell_config.py" -v
python -m unittest discover -s tests -p "test_user_config.py" -v
python -m unittest discover -s tests -p "test_credentials.py" -v
python -m unittest discover -s tests -p "test_cli.py" -v
```

Expected: PASS.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/shell_config.py src/specgate/user_config.py tests/test_shell_config.py tests/test_user_config.py
git diff --cached --check
git commit -m "feat: add interactive shell configuration commands"
```

### Task 8: Implement The REPL, Inline Approval, And Cancellation

**Files:**
- Create: `src/specgate/interactive_shell.py`
- Create: `tests/test_interactive_shell.py`

- [ ] **Step 1: Write parsing, lifecycle, Mock, approval, and Ctrl+C tests**

```python
def test_parse_input_preserves_argument_case_and_recognizes_exit_variants(self):
    self.assertEqual(parse_input("/MODEL DeepSeek-V4-Pro"),
                     ShellInput("command", "model", "DeepSeek-V4-Pro"))
    for value in ("exit", "ExiT", "q", "Q", "quit"):
        self.assertEqual(parse_input(value).kind, "exit")

def test_each_natural_language_input_starts_one_run(self):
    terminal = ScriptedTerminal(["first request", "second request", "q"])
    runtime = RecordingRuntime(completed_outcomes(2))

    code = make_shell(terminal, runtime).run()

    self.assertEqual(code, 0)
    self.assertEqual(runtime.requests, ["first request", "second request"])

def test_mock_request_requires_confirmation(self):
    terminal = ScriptedTerminal(["custom request", "n", "q"])
    runtime = RecordingRuntime([])

    make_shell(terminal, runtime, mode="mock").run()

    self.assertEqual(runtime.requests, [])
    self.assertIn("只能展示内置 Demo", terminal.output)

def test_inline_approval_decides_and_resumes_same_session(self):
    terminal = ScriptedTerminal(["write page", "yes", "q"])
    runtime = RecordingRuntime([pending_outcome(), completed_outcome()])

    make_shell(terminal, runtime).run()

    self.assertEqual(runtime.decisions, [("approval-1", "approved")])

def test_keyboard_interrupt_cancels_active_run_but_keeps_shell_open(self):
    terminal = ScriptedTerminal(["long request", "after cancel", "q"])
    runtime = BlockingRuntime(interrupt_wait_once=True)

    make_shell(terminal, runtime).run()

    self.assertTrue(runtime.cancel_seen)
    self.assertEqual(runtime.requests[-1], "after cancel")

def test_connection_test_runs_only_after_explicit_yes(self):
    terminal = ScriptedTerminal(["yes", "q"])
    runtime = RecordingRuntime([])
    controller = ConfigControllerRequestingConnectionTest()

    make_shell(terminal, runtime, config_controller=controller).run()

    self.assertEqual(runtime.connection_tests, 1)
    self.assertIn("可能产生少量 API 费用", terminal.output)

def test_approvals_command_lists_and_decides_selected_pending_item(self):
    terminal = ScriptedTerminal(["/approvals", "approval-2", "no", "q"])
    runtime = RecordingRuntime([])
    runtime.pending = [approval("approval-1"), approval("approval-2")]

    make_shell(terminal, runtime).run()

    self.assertEqual(runtime.external_decisions, [("approval-2", "denied")])
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest discover -s tests -p "test_interactive_shell.py" -v`

Expected: FAIL because the REPL module does not exist.

- [ ] **Step 3: Implement pure parsing and cancellable execution**

```python
EXIT_WORDS = frozenset({"exit", "quit", "q"})
COMMANDS = frozenset({
    "help", "status", "setup", "mode", "workspace", "model", "url",
    "api-key", "verbose", "approvals", "clear", "exit",
})

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
    argument = tail.strip() if separator and tail.strip() else None
    return ShellInput("command", name=name, argument=argument)

class EventCancellationToken:
    def __init__(self):
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def check(self) -> None:
        if self._cancelled.is_set():
            raise RunCancelled("run cancelled")

    def remaining_seconds(self) -> float:
        return float("inf")
```

Use a `ThreadPoolExecutor(max_workers=1)` for the active runtime call. The main thread waits in bounded intervals. On `KeyboardInterrupt`, set an event-backed cancellation token and continue waiting until AgentLoop records `RunStatus.CANCELLED`; then print `[Cancelled]` and return to the prompt. Shut down the executor before Shell exit.

Implement the control loop with these exact decisions:

- command input never creates an AgentRun;
- `/exit` has the same normal shutdown behavior as `exit`, `quit`, and `q`;
- unknown slash command prints a help hint;
- Mock natural language asks `是否运行 Mock Demo？[Y/n]` and starts only after yes;
- pending approval asks yes/no, updates through `ShellRunSession.decide`, and resumes the same session;
- `/approvals` reads existing pending items, lets the user select an ID, and decides through the runtime approval API;
- `/status` combines the persisted configuration summary with `self._last_outcome` without starting a run;
- a requested connection test first prints the possible-cost notice and runs only after explicit yes;
- completed, failed, cancelled, and pending approval are mutually exclusive displayed terminal states;
- idle `KeyboardInterrupt` exits; active cancellation does not;
- `EOFError` exits cleanly.

Do not retain prompts outside the terminal's `InMemoryHistory`.

- [ ] **Step 4: Run Shell control tests**

Run: `python -m unittest discover -s tests -p "test_interactive_shell.py" -v`

Expected: PASS with no leaked executor thread.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/interactive_shell.py tests/test_interactive_shell.py
git diff --cached --check
git commit -m "feat: add cancellable interactive agent shell"
```

### Task 9: Wire Bare `specgate` Without Breaking Existing Commands

**Files:**
- Modify: `src/specgate/cli.py:880-1055`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write entrypoint compatibility tests**

```python
def test_bare_cli_starts_interactive_shell(self):
    with patch("specgate.cli.run_interactive_shell", return_value=0) as shell:
        self.assertEqual(main([]), 0)
    shell.assert_called_once()

def test_help_does_not_start_shell(self):
    output = io.StringIO()
    with patch("specgate.cli.run_interactive_shell") as shell, redirect_stdout(output):
        with self.assertRaises(SystemExit) as raised:
            main(["--help"])
    self.assertEqual(raised.exception.code, 0)
    shell.assert_not_called()
    self.assertIn("run-mock-demo", output.getvalue())

def test_existing_run_dispatch_is_unchanged(self):
    with temporary_run_workspace() as root, \
         patch("specgate.cli.run_real_llm", return_value=0) as run, \
         patch("specgate.cli.run_interactive_shell") as shell:
        code = main(["run", str(root), "--model", "m", "--base-url", "https://x/v1"])
    self.assertEqual(code, 0)
    run.assert_called_once()
    shell.assert_not_called()
```

Add a non-TTY test asserting bare CLI prints a clear interactive-input error rather than blocking.

- [ ] **Step 2: Run CLI tests and verify failure**

Run: `python -m unittest discover -s tests -p "test_cli.py" -v`

Expected: FAIL because subparsers are currently required and no Shell entry exists.

- [ ] **Step 3: Make the subcommand optional and wire collaborators**

Change:

```python
sub = parser.add_subparsers(dest="command")
args = parser.parse_args(argv)
if args.command is None:
    return run_interactive_shell()
```

`run_interactive_shell()` constructs `PromptToolkitTerminal`, `ShellConfigController`, `ShellEventRenderer`, and `SpecGateShellRuntime`. Pass the existing `_fixed_demo_html()` response sequence as an injected MockLLM factory so CLI and Shell use one canonical demo. Pass `OpenAICompatibleLLM` through an injected real factory that receives effective URL, model, credential, timeout, and cancellation callbacks.

When `argv is None` and stdin is not a TTY, return code 2 with `interactive input is unavailable; use an explicit specgate subcommand`. Unit tests pass `[]` and inject a fake terminal, so they do not depend on the host console.

- [ ] **Step 4: Run CLI and import tests**

Run:

```powershell
python -m unittest discover -s tests -p "test_cli.py" -v
python -m unittest discover -s tests -p "test_imports.py" -v
python -m compileall -q src tests
```

Expected: PASS and compileall exits 0.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- src/specgate/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat: enter interactive shell from bare specgate"
```

### Task 10: Add End-To-End Mock And Security Regression Coverage

**Files:**
- Create: `tests/test_shell_e2e.py`
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1: Write a scripted full-Shell test**

```python
def test_mock_shell_generates_html_reports_progress_and_leaks_no_secret(self):
    with temporary_demo_workspace() as root:
        terminal = ScriptedTerminal([
            "mock",
            str(root),
            "请根据 spec 和 checklist 生成 html",
            "yes",
            "q",
        ])
        shell = build_test_shell(terminal, credential="sk-e2e-secret-1234567890")

        code = shell.run()

        output = terminal.output
        self.assertEqual(code, 0)
        self.assertTrue((root / "index.html").is_file())
        self.assertIn("[Context]", output)
        self.assertIn("[Tool]", output)
        self.assertIn("[Governance]", output)
        self.assertIn("[Gate]", output)
        self.assertIn("[Done]", output)
        self.assertNotIn("sk-e2e-secret", output)
        self.assertEqual(len(list((root / "runs").glob("*/trace.jsonl"))), 2)
```

The two traces are `runs/latest/trace.jsonl` and the immutable `runs/<run_id>/trace.jsonl` archive.

- [ ] **Step 2: Add evidence-contract assertions**

Extend `tests/test_final_evidence.py` to assert that the design, plan, README Shell entry, keyring-only statement, Mock limitation, and core command list remain present. Assert facts, not prose formatting.

- [ ] **Step 3: Run Shell and security slices**

Run:

```powershell
python -m unittest discover -s tests -p "test_shell_*.py" -v
python -m unittest discover -s tests -p "test_credentials.py" -v
python -m unittest discover -s tests -p "test_workspace_fs.py" -v
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

Expected: PASS; no output or generated JSON contains `sk-e2e-secret`.

- [ ] **Step 4: Run malformed-response, timeout, and cancellation regressions**

Run:

```powershell
python -m unittest discover -s tests -p "test_llm.py" -v
python -m unittest discover -s tests -p "test_llm_transport.py" -v
python -m unittest discover -s tests -p "test_agent_loop.py" -v
python -m unittest discover -s tests -p "test_shell_runtime.py" -v
```

Expected: PASS; malformed Action JSON is never executed and cancellation reaches a terminal state.

- [ ] **Step 5: User-executed Git checkpoint**

```powershell
git add -- tests/test_shell_e2e.py tests/test_final_evidence.py
git diff --cached --check
git commit -m "test: cover interactive shell end to end"
```

### Task 11: Synchronize v0.3.0 Version And User Documentation

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `src/specgate/__init__.py:1`
- Modify: `tests/test_imports.py`
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `SPEC_PROCESS.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Write version assertions first**

Change the expected values in `tests/test_imports.py` to `0.3.0`, then run:

```powershell
python -m unittest discover -s tests -p "test_imports.py" -v
```

Expected: FAIL because package and project metadata still report `0.2.0`.

- [ ] **Step 2: Bump package metadata**

Set both values exactly:

```toml
version = "0.3.0"
```

```python
__version__ = "0.3.0"
```

- [ ] **Step 3: Document the actual interactive workflow**

Add README examples for bare startup, first setup, Real/Mock switching, natural-language generation, `/help`, `/status`, `/workspace`, `/model`, `/url`, `/api-key`, `/verbose`, `/approvals`, `/clear`, and exit variants. State that Mock is fixed, Real mode may incur provider charges, credentials use keyring/environment precedence, and no public deployment is required.

Update `SPEC.md` and `SPEC_PROCESS.md` with the approved Shell boundary and decisions. Add v0.3.0 task rows to `PLAN.md` and chronological implementation/verification entries to `AGENT_LOG.md`; do not claim a Release, tag, PR, full-suite pass, or DeepSeek compatibility test until each has actually happened.

- [ ] **Step 4: Run the full verification gate**

Run:

```powershell
git diff --check
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

Expected: compileall exits 0; the complete suite reports `OK` with only documented skips. Record the exact test count and skip count in `AGENT_LOG.md` only after this output exists.

- [ ] **Step 5: Perform the manual Windows Shell smoke test**

Run:

```powershell
specgate
```

Verify in order:

1. blue `SpecGate >>` on a color-capable PowerShell terminal;
2. Mock request confirmation and fixed Demo completion;
3. `/mode real` restores or requests missing settings;
4. optional connection test asks before sending;
5. natural-language generation and modification show live events;
6. approval accepts `yes` and resumes;
7. active `Ctrl+C` returns to the prompt;
8. `Q` exits;
9. restarting restores non-secret settings without showing the API key.

If a DeepSeek V4 Pro OpenAI-compatible endpoint and credential are available, repeat steps 3-7 with that model and capture: connection-test result, strict JSON Action success, one Gate repair, malformed-response handling, timeout handling, and cancellation. If credentials or the named model are unavailable, record the smoke test as not run; do not infer compatibility from another model.

- [ ] **Step 6: User-executed Git checkpoint**

```powershell
git add -- pyproject.toml src/specgate/__init__.py tests/test_imports.py README.md SPEC.md SPEC_PROCESS.md PLAN.md AGENT_LOG.md
git diff --cached --check
git commit -m "docs: complete SpecGate 0.3.0 interactive shell"
```

## Final Review And Release Boundary

Before opening a PR, the user runs:

```powershell
git status --short --branch
git diff --check
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

The implementation is ready for review only if:

- all automatic tests pass;
- the worktree contains only intended v0.3.0 changes;
- API key sentinels are absent from config, Trace, report, Memory, and terminal captures;
- each natural-language input creates exactly one AgentRun;
- Gate failure never displays `[Done]`;
- Mock never claims to understand custom input;
- existing explicit CLI commands retain v0.2.0 behavior.

Release creation is a separate, user-approved operation after PR merge. Do not tag, push a Release, publish a container, or claim DeepSeek V4 Pro compatibility from implementation tests alone.
