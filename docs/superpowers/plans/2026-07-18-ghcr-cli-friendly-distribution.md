# SpecGate CLI 易用性与 GHCR 公开镜像分发实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户一次执行 `specgate configure` 后可用 `specgate run <工作区>`，并通过版本标签把 CLI-first 镜像公开发布到 `ghcr.io/yugarden404/specgate`。

**Architecture:** 新增只保存非敏感字段的用户配置模块，CLI 负责交互配置、优先级解析和工作区预检，现有 credential store 继续独占 API key。Docker 默认入口改为 `specgate`，GitHub 版本标签工作流负责校验版本、推送 GHCR 和运行确定性 smoke；远端发布成功后再用独立证据提交更新最终交付状态。

**Tech Stack:** Python 3.11、`argparse`、`dataclasses`、JSON、OS keyring、`unittest`、Docker、GitHub Actions、GHCR。

---

## 文件职责

- `src/specgate/user_config.py`：跨平台用户配置路径、非敏感配置校验、原子读写和运行参数优先级。
- `src/specgate/cli.py`：`configure` 交互、工作区预检、简化后的 `run` 编排和友好输出。
- `tests/test_user_config.py`：用户配置模块的独立单元测试。
- `tests/test_cli.py`：CLI 交互、兼容性、失败关闭和运行路径测试。
- `Dockerfile`：CLI-first 镜像入口，同时保留显式 WebUI 入口能力。
- `.github/workflows/ci.yml`：每次 push/PR 的容器 build 与 CLI/WebUI smoke。
- `.github/workflows/ghcr.yml`：版本标签校验、GHCR 登录、标签生成、推送和远端镜像 smoke。
- `tests/test_workflows.py`：Dockerfile、CI 与 GHCR workflow 的静态契约测试。
- `README.md`、`docs/DEPLOYMENT.md`：本机与容器用户操作说明。
- `PLAN.md`、`AGENT_LOG.md`、`docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md`、`docs/REFLECTION_FACT_CHECK.md`：实现阶段和远端发布阶段的事实边界。
- `tests/test_final_evidence.py`：防止在匿名拉取验证前提前宣称公开 registry 完成，并在证据阶段绑定最终 URL、截图与 digest。

---

### Task 1: 用户级非敏感 LLM 配置

**Files:**
- Create: `src/specgate/user_config.py`
- Create: `tests/test_user_config.py`

- [ ] **Step 1: 写跨平台路径和配置读写失败测试**

创建 `tests/test_user_config.py`：

```python
import json
import tempfile
import unittest
from pathlib import Path

from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    load_user_llm_config,
    resolve_user_llm_config,
    save_user_llm_config,
    user_config_path,
)


class UserConfigTests(unittest.TestCase):
    def test_config_home_override_isolated_from_real_profile(self):
        path = user_config_path(
            environ={"SPECGATE_CONFIG_HOME": "D:/isolated/specgate"},
            home=Path("D:/Users/example"),
            platform="win32",
        )
        self.assertEqual(path, Path("D:/isolated/specgate/config.json"))

    def test_windows_uses_appdata(self):
        path = user_config_path(
            environ={"APPDATA": "D:/Profiles/example/AppData/Roaming"},
            home=Path("D:/Profiles/example"),
            platform="win32",
        )
        self.assertEqual(path, Path("D:/Profiles/example/AppData/Roaming/SpecGate/config.json"))

    def test_linux_uses_xdg_then_home_fallback(self):
        self.assertEqual(
            user_config_path(
                environ={"XDG_CONFIG_HOME": "/tmp/xdg"},
                home=Path("/home/example"),
                platform="linux",
            ),
            Path("/tmp/xdg/specgate/config.json"),
        )
        self.assertEqual(
            user_config_path(environ={}, home=Path("/home/example"), platform="linux"),
            Path("/home/example/.config/specgate/config.json"),
        )

    def test_round_trip_writes_only_non_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            config = UserLLMConfig(
                provider="openai-compatible",
                base_url="https://api.example.test/v1",
                model="gpt-test",
            )
            save_user_llm_config(config, path=path)
            raw = path.read_text(encoding="utf-8")
            self.assertEqual(load_user_llm_config(path=path), config)
            self.assertNotIn("api_key", raw.lower())
            self.assertNotIn("secret", raw.lower())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_missing_config_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_user_llm_config(path=Path(tmp) / "missing.json"))

    def test_malformed_or_sensitive_config_fails_closed(self):
        invalid_payloads = (
            "{",
            json.dumps({"schema_version": 99, "provider": "openai-compatible", "base_url": "https://api.test/v1", "model": "m"}),
            json.dumps({"schema_version": 1, "provider": "openai-compatible", "base_url": "https://api.test/v1", "model": "m", "api_key": "sk-secret"}),
            json.dumps({"schema_version": 1, "provider": "anthropic", "base_url": "https://api.test/v1", "model": "m"}),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(UserConfigError):
                    load_user_llm_config(path=path)

    def test_resolution_priority_is_cli_then_environment_then_file(self):
        saved = UserLLMConfig("openai-compatible", "https://saved.test/v1", "saved-model")
        resolved = resolve_user_llm_config(
            provider="openai-compatible",
            model="cli-model",
            base_url=None,
            environ={"SPECGATE_LLM_BASE_URL": "https://env.test/v1", "SPECGATE_LLM_MODEL": "env-model"},
            saved=saved,
        )
        self.assertEqual(resolved.model, "cli-model")
        self.assertEqual(resolved.base_url, "https://env.test/v1")

    def test_resolution_reports_configure_command_when_incomplete(self):
        with self.assertRaisesRegex(UserConfigError, "specgate configure"):
            resolve_user_llm_config(
                provider="openai-compatible",
                model=None,
                base_url=None,
                environ={},
                saved=None,
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试并确认因模块缺失而失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_user_config -v
```

Expected: FAIL，包含 `ModuleNotFoundError: No module named 'specgate.user_config'`。

- [ ] **Step 3: 实现配置路径、校验、原子读写和优先级**

创建 `src/specgate/user_config.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Mapping


SCHEMA_VERSION = 1
SUPPORTED_PROVIDER = "openai-compatible"
MAX_CONFIG_VALUE_CHARS = 2048


class UserConfigError(ValueError):
    pass


@dataclass(frozen=True)
class UserLLMConfig:
    provider: str
    base_url: str
    model: str


def user_config_path(
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    values = os.environ if environ is None else environ
    override = values.get("SPECGATE_CONFIG_HOME")
    if override:
        return Path(override).expanduser() / "config.json"
    user_home = Path.home() if home is None else home
    current_platform = sys.platform if platform is None else platform
    if current_platform == "win32":
        base = Path(values.get("APPDATA", user_home / "AppData" / "Roaming"))
        return base / "SpecGate" / "config.json"
    xdg = values.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else user_home / ".config"
    return base / "specgate" / "config.json"


def _config_value(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise UserConfigError(f"invalid user config: {name}")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_CONFIG_VALUE_CHARS
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise UserConfigError(f"invalid user config: {name}")
    return normalized


def _from_payload(payload: object) -> UserLLMConfig:
    if not isinstance(payload, dict):
        raise UserConfigError("invalid user config: root")
    expected = {"schema_version", "provider", "base_url", "model"}
    if set(payload) != expected or payload.get("schema_version") != SCHEMA_VERSION:
        raise UserConfigError("invalid user config: schema")
    provider = _config_value("provider", payload["provider"])
    if provider != SUPPORTED_PROVIDER:
        raise UserConfigError("invalid user config: provider")
    return UserLLMConfig(
        provider=provider,
        base_url=_config_value("base_url", payload["base_url"]),
        model=_config_value("model", payload["model"]),
    )


def load_user_llm_config(*, path: Path | None = None) -> UserLLMConfig | None:
    target = user_config_path() if path is None else path
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise UserConfigError(f"invalid user config: {target}") from exc
    return _from_payload(payload)


def save_user_llm_config(config: UserLLMConfig, *, path: Path | None = None) -> None:
    normalized = _from_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "provider": config.provider,
            "base_url": config.base_url,
            "model": config.model,
        }
    )
    target = user_config_path() if path is None else path
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "provider": normalized.provider,
        "base_url": normalized.base_url,
        "model": normalized.model,
    }
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, target)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise UserConfigError(f"could not save user config: {target}") from exc


def resolve_user_llm_config(
    *,
    provider: str,
    model: str | None,
    base_url: str | None,
    environ: Mapping[str, str] | None = None,
    saved: UserLLMConfig | None = None,
) -> UserLLMConfig:
    values = os.environ if environ is None else environ
    resolved_model = model or values.get("SPECGATE_LLM_MODEL") or (saved.model if saved else None)
    resolved_base_url = base_url or values.get("SPECGATE_LLM_BASE_URL") or (saved.base_url if saved else None)
    if provider != SUPPORTED_PROVIDER:
        raise UserConfigError(f"unsupported provider: {provider}")
    if not resolved_model or not resolved_base_url:
        raise UserConfigError("LLM configuration is incomplete; run: specgate configure")
    return _from_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "provider": provider,
            "base_url": resolved_base_url,
            "model": resolved_model,
        }
    )
```

- [ ] **Step 4: 运行配置模块测试并确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_user_config -v
```

Expected: `Ran 8 tests`，`OK`。

- [ ] **Step 5: 手动提交配置模块**

```powershell
git add -- src/specgate/user_config.py tests/test_user_config.py
git diff --cached --check
git commit -m "feat(cli): 添加用户级 LLM 配置"
```

---

### Task 2: `specgate configure` 安全交互

**Files:**
- Modify: `src/specgate/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 写 configure 成功、保留凭据和失败关闭测试**

在 `tests/test_cli.py` 的 `CliTests` 中加入：

```python
    def test_configure_saves_non_secret_defaults_and_hidden_credential(self):
        store = MemoryCredentialStore()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": tmp}, clear=True),
                patch("specgate.credentials.KeyringCredentialStore", return_value=store),
                patch("builtins.input", side_effect=["https://api.example.test/v1", "gpt-test"]),
                patch("specgate.cli.getpass.getpass", return_value="sk-configure-secret") as secret_prompt,
                redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["configure"])
            self.assertEqual(code, 0)
            secret_prompt.assert_called_once()
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["model"], "gpt-test")
            self.assertEqual(payload["base_url"], "https://api.example.test/v1")
            self.assertNotIn("api_key", payload)
            self.assertEqual(store.values["openai-compatible"], "sk-configure-secret")
            self.assertNotIn("sk-configure-secret", output.getvalue())

    def test_configure_keeps_existing_values_and_credential_on_empty_input(self):
        store = MemoryCredentialStore()
        store.set("openai-compatible", "sk-existing")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps({
                    "schema_version": 1,
                    "provider": "openai-compatible",
                    "base_url": "https://saved.test/v1",
                    "model": "saved-model",
                }),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": tmp}, clear=True),
                patch("specgate.credentials.KeyringCredentialStore", return_value=store),
                patch("builtins.input", side_effect=["", ""]),
                patch("specgate.cli.getpass.getpass", return_value=""),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(["configure"]), 0)
            self.assertEqual(store.values["openai-compatible"], "sk-existing")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["model"], "saved-model")

    def test_configure_fails_closed_without_new_or_existing_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": tmp}, clear=True),
                patch("specgate.credentials.KeyringCredentialStore", return_value=MemoryCredentialStore()),
                patch("builtins.input", side_effect=["https://api.example.test/v1", "gpt-test"]),
                patch("specgate.cli.getpass.getpass", return_value=""),
                redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["configure"])
            self.assertEqual(code, 1)
            self.assertIn("API key", output.getvalue())
            self.assertFalse((Path(tmp) / "config.json").exists())

    def test_configure_handles_unavailable_keyring_without_traceback(self):
        class UnavailableStore(MemoryCredentialStore):
            def get(self, provider):
                raise CredentialStoreUnavailable("unavailable")

            def set(self, provider, secret):
                raise CredentialStoreUnavailable("unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": tmp}, clear=True),
                patch("specgate.credentials.KeyringCredentialStore", return_value=UnavailableStore()),
                patch("builtins.input", side_effect=["https://api.example.test/v1", "gpt-test"]),
                patch("specgate.cli.getpass.getpass", return_value="sk-hidden"),
                redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["configure"])
            self.assertEqual(code, 1)
            self.assertIn("credential store is unavailable", output.getvalue())
            self.assertNotIn("sk-hidden", output.getvalue())
            self.assertFalse((Path(tmp) / "config.json").exists())
```

并在 `tests/test_cli.py` 顶部加入：

```python
from specgate.credential_store import CredentialStoreUnavailable
```

- [ ] **Step 2: 运行测试并确认 configure 子命令缺失**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli.CliTests.test_configure_saves_non_secret_defaults_and_hidden_credential tests.test_cli.CliTests.test_configure_keeps_existing_values_and_credential_on_empty_input tests.test_cli.CliTests.test_configure_fails_closed_without_new_or_existing_credential tests.test_cli.CliTests.test_configure_handles_unavailable_keyring_without_traceback -v
```

Expected: FAIL，`argparse` 报告 `configure` 是无效命令。

- [ ] **Step 3: 实现 configure helper**

在 `src/specgate/cli.py` 增加导入：

```python
from specgate.credential_store import CredentialStoreUnavailable
from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    load_user_llm_config,
    save_user_llm_config,
    user_config_path,
)
```

在 `main` 前增加：

```python
def configure_user() -> int:
    path = user_config_path()
    try:
        current = load_user_llm_config(path=path)
    except UserConfigError:
        print(f"user config is invalid: {path}; remove it and run: specgate configure")
        return 1

    base_default = current.base_url if current else ""
    model_default = current.model if current else ""
    base_prompt = f"Base URL [{base_default}]: " if base_default else "Base URL: "
    model_prompt = f"Model [{model_default}]: " if model_default else "Model: "
    base_url = input(base_prompt).strip() or base_default
    model = input(model_prompt).strip() or model_default
    if not base_url or not model:
        print("Base URL and Model are required")
        return 1

    status = credential_status("openai-compatible")
    prompt = "API key [configured; press Enter to keep]: " if status.safe_to_run else "API key: "
    secret = getpass.getpass(prompt)
    if secret:
        try:
            set_credential("openai-compatible", secret)
        except ValueError:
            print("API key is invalid")
            return 1
        except CredentialStoreUnavailable:
            print("credential store is unavailable; set OPENAI_COMPATIBLE_API_KEY instead")
            return 1
    elif not status.safe_to_run:
        print("API key is required; alternatively set OPENAI_COMPATIBLE_API_KEY")
        return 1

    try:
        save_user_llm_config(
            UserLLMConfig("openai-compatible", base_url, model),
            path=path,
        )
    except UserConfigError as exc:
        print(str(exc))
        return 1
    print(f"configuration saved: {path}; API key value hidden")
    return 0
```

- [ ] **Step 4: 注册 configure 命令**

在 `main` 的 parser 构造区加入：

```python
    sub.add_parser("configure", help="保存默认 Base URL、Model 和隐藏的 API key")
```

在 `parse_args` 后的 dispatch 最前面加入：

```python
    if args.command == "configure":
        return configure_user()
```

- [ ] **Step 5: 运行 configure 与现有 credentials 测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli.CliTests.test_configure_saves_non_secret_defaults_and_hidden_credential tests.test_cli.CliTests.test_configure_keeps_existing_values_and_credential_on_empty_input tests.test_cli.CliTests.test_configure_fails_closed_without_new_or_existing_credential tests.test_cli.CliTests.test_configure_handles_unavailable_keyring_without_traceback tests.test_cli.CliTests.test_credentials_cli_status_set_and_clear tests.test_cli.CliTests.test_credentials_cli_never_echoes_invalid_secret -v
```

Expected: `Ran 6 tests`，`OK`。

- [ ] **Step 6: 手动提交 configure**

```powershell
git add -- src/specgate/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat(cli): 添加安全配置向导"
```

---

### Task 3: 简化 `run` 并增加工作区预检

**Files:**
- Modify: `src/specgate/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: 写用户配置解析、环境覆盖和预检测试**

在 `tests/test_cli.py` 增加：

```python
    def test_run_uses_saved_user_defaults_without_model_flags(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as config_tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- [ ] ok", encoding="utf-8")
            Path(config_tmp, "config.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "provider": "openai-compatible",
                    "base_url": "https://saved.test/v1",
                    "model": "saved-model",
                }),
                encoding="utf-8",
            )
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": config_tmp, "OPENAI_COMPATIBLE_API_KEY": "sk-test"}, clear=True),
                patch("specgate.cli.run_real_llm", return_value=0) as run,
            ):
                self.assertEqual(main(["run", str(root)]), 0)
            self.assertEqual(run.call_args.kwargs["model"], "saved-model")
            self.assertEqual(run.call_args.kwargs["base_url"], "https://saved.test/v1")

    def test_run_environment_overrides_saved_defaults(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as config_tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- [ ] ok", encoding="utf-8")
            Path(config_tmp, "config.json").write_text(
                json.dumps({"schema_version": 1, "provider": "openai-compatible", "base_url": "https://saved/v1", "model": "saved"}),
                encoding="utf-8",
            )
            env = {
                "SPECGATE_CONFIG_HOME": config_tmp,
                "OPENAI_COMPATIBLE_API_KEY": "sk-test",
                "SPECGATE_LLM_BASE_URL": "https://env.test/v1",
                "SPECGATE_LLM_MODEL": "env-model",
            }
            with patch.dict(os.environ, env, clear=True), patch("specgate.cli.run_real_llm", return_value=0) as run:
                self.assertEqual(main(["run", str(root)]), 0)
            self.assertEqual(run.call_args.kwargs["model"], "env-model")
            self.assertEqual(run.call_args.kwargs["base_url"], "https://env.test/v1")

    def test_run_fails_before_provider_when_workspace_inputs_are_missing(self):
        cases = (
            (False, False, "workspace directory"),
            (True, False, "TASK_SPEC.md"),
            (True, True, "CHECKLIST.md"),
        )
        for create_root, create_spec, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "workspace"
                if create_root:
                    root.mkdir()
                if create_spec:
                    (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
                with (
                    patch.dict(os.environ, {"SPECGATE_LLM_BASE_URL": "https://api.test/v1", "SPECGATE_LLM_MODEL": "m"}, clear=True),
                    patch("specgate.cli.run_real_llm") as run,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    code = main(["run", str(root)])
                self.assertEqual(code, 1)
                self.assertIn(expected, output.getvalue())
                run.assert_not_called()

    def test_run_incomplete_defaults_points_to_configure(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as config_tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- [ ] ok", encoding="utf-8")
            with (
                patch.dict(os.environ, {"SPECGATE_CONFIG_HOME": config_tmp}, clear=True),
                patch("specgate.cli.run_real_llm") as run,
                redirect_stdout(io.StringIO()) as output,
            ):
                code = main(["run", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("specgate configure", output.getvalue())
            run.assert_not_called()
```

- [ ] **Step 2: 运行测试并确认 `--model` / `--base-url` 仍被 argparse 强制**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli.CliTests.test_run_uses_saved_user_defaults_without_model_flags tests.test_cli.CliTests.test_run_environment_overrides_saved_defaults tests.test_cli.CliTests.test_run_fails_before_provider_when_workspace_inputs_are_missing tests.test_cli.CliTests.test_run_incomplete_defaults_points_to_configure -v
```

Expected: FAIL，至少包含 `the following arguments are required: --model, --base-url`。

- [ ] **Step 3: 实现工作区预检和配置解析 helper**

补充 `src/specgate/cli.py` 导入：

```python
from specgate.user_config import resolve_user_llm_config
```

增加：

```python
def _validate_run_workspace(root: Path) -> str | None:
    if not root.is_dir():
        return f"workspace directory does not exist: {root}"
    missing = [name for name in ("TASK_SPEC.md", "CHECKLIST.md") if not (root / name).is_file()]
    if missing:
        return "workspace is missing required file(s): " + ", ".join(missing)
    return None


def _resolve_cli_run_config(provider: str, model: str | None, base_url: str | None):
    environment_model = os.environ.get("SPECGATE_LLM_MODEL")
    environment_base_url = os.environ.get("SPECGATE_LLM_BASE_URL")
    saved = None
    if not (model or environment_model) or not (base_url or environment_base_url):
        saved = load_user_llm_config()
    return resolve_user_llm_config(
        provider=provider,
        model=model,
        base_url=base_url,
        saved=saved,
    )
```

- [ ] **Step 4: 让 `run` 参数可省略并在 dispatch 中预检**

把 parser 参数改为：

```python
    real_run.add_argument("--model")
    real_run.add_argument("--base-url")
```

把 `if args.command == "run":` 分支替换为：

```python
    if args.command == "run":
        root = Path(args.workspace)
        workspace_error = _validate_run_workspace(root)
        if workspace_error:
            print(workspace_error)
            return 1
        try:
            resolved = _resolve_cli_run_config(args.provider, args.model, args.base_url)
        except UserConfigError as exc:
            print(str(exc))
            return 1
        return run_real_llm(
            root=root,
            provider=resolved.provider,
            model=resolved.model,
            base_url=resolved.base_url,
            max_steps=args.max_steps,
            user_agent=args.user_agent,
            timeout=args.timeout,
            governance_profile=args.governance_profile,
        )
```

- [ ] **Step 5: 在成功运行后输出产物位置**

在 `run_real_llm` 的完成输出后、返回前加入：

```python
    print(f"HTML: {root / 'index.html'}")
    print(f"Report: {root / 'reports' / 'latest' / 'index.html'}")
    print(f"Trace: {root / 'runs' / 'latest' / 'trace.jsonl'}")
```

- [ ] **Step 6: 运行新增测试和原有真实 provider 测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_user_config tests.test_cli.CliTests.test_run_uses_saved_user_defaults_without_model_flags tests.test_cli.CliTests.test_run_environment_overrides_saved_defaults tests.test_cli.CliTests.test_run_fails_before_provider_when_workspace_inputs_are_missing tests.test_cli.CliTests.test_run_incomplete_defaults_points_to_configure tests.test_cli.CliTests.test_real_run_fails_closed_without_credential tests.test_cli.CliTests.test_real_run_uses_provider_inside_existing_runner tests.test_cli.CliTests.test_real_run_reports_provider_error_without_traceback -v
```

Expected: 全部通过，`OK`。

- [ ] **Step 7: 手动提交简化 run**

```powershell
git add -- src/specgate/cli.py tests/test_cli.py
git diff --cached --check
git commit -m "feat(cli): 简化工作区运行流程"
```

---

### Task 4: CLI-first Docker 镜像与常规 CI smoke

**Files:**
- Modify: `Dockerfile`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_workflows.py`

- [ ] **Step 1: 写 Dockerfile 和 CI 入口契约测试**

在 `tests/test_workflows.py` 加入：

```python
    def test_dockerfile_defaults_to_specgate_cli(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('WORKDIR /workspace', dockerfile)
        self.assertIn('ENTRYPOINT ["specgate"]', dockerfile)
        self.assertIn('CMD ["--help"]', dockerfile)
        self.assertNotIn('CMD ["specgate-web"', dockerfile)

    def test_github_ci_smokes_cli_and_explicit_web_entrypoints(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("docker run --rm specgate:ci --help", workflow)
        self.assertIn("docker run --rm specgate:ci run-mock-demo /opt/specgate/examples/knowledge_nav", workflow)
        self.assertIn("docker run --rm --entrypoint specgate-web specgate:ci --help", workflow)
```

- [ ] **Step 2: 运行测试并确认默认入口断言失败**

Run:

```powershell
python -m unittest tests.test_workflows.WorkflowTests.test_dockerfile_defaults_to_specgate_cli tests.test_workflows.WorkflowTests.test_github_ci_smokes_cli_and_explicit_web_entrypoints -v
```

Expected: FAIL，当前 Dockerfile 仍以 `specgate-web` 为 CMD。

- [ ] **Step 3: 将 Dockerfile 改为 CLI-first**

用以下内容替换 `Dockerfile`：

```dockerfile
FROM python:3.11-slim

WORKDIR /opt/specgate

COPY pyproject.toml README.md /opt/specgate/
COPY src /opt/specgate/src
COPY examples /opt/specgate/examples

RUN python -m pip install --no-cache-dir -e . \
    && mkdir -p /workspace /data/specgate-web

ENV SPECGATE_WEB_DATA=/data/specgate-web

WORKDIR /workspace

ENTRYPOINT ["specgate"]
CMD ["--help"]
```

- [ ] **Step 4: 更新 GitHub CI 容器 smoke**

把 `.github/workflows/ci.yml` 的 Docker smoke step 替换为：

```yaml
      - name: Smoke test Docker CLI entrypoint
        run: |
          docker run --rm specgate:ci --help
          docker run --rm specgate:ci run-mock-demo /opt/specgate/examples/knowledge_nav

      - name: Smoke test explicit WebUI entrypoint
        run: docker run --rm --entrypoint specgate-web specgate:ci --help
```

- [ ] **Step 5: 运行 workflow 测试**

Run:

```powershell
python -m unittest tests.test_workflows -v
```

Expected: 全部通过，`OK`。

- [ ] **Step 6: 若 Docker 可用，构建并运行本地 smoke**

Run:

```powershell
docker build -t specgate:ghcr-local .
docker run --rm specgate:ghcr-local --help
docker run --rm specgate:ghcr-local run-mock-demo /opt/specgate/examples/knowledge_nav
docker run --rm --entrypoint specgate-web specgate:ghcr-local --help
```

Expected: build exit code 0；CLI help 显示 `configure` 和 `run`；Mock Demo exit code 0；WebUI help exit code 0。若本机 Docker daemon 不可用，在 `AGENT_LOG.md` 如实记录，并由 GitHub `docker-build` job 完成验证。

- [ ] **Step 7: 手动提交 Docker 调整**

```powershell
git add -- Dockerfile .github/workflows/ci.yml tests/test_workflows.py
git diff --cached --check
git commit -m "feat(docker): 默认启动 SpecGate CLI"
```

---

### Task 5: GHCR 版本发布工作流

**Files:**
- Create: `.github/workflows/ghcr.yml`
- Modify: `tests/test_workflows.py`

- [ ] **Step 1: 写 GHCR 触发、权限、标签和 smoke 契约测试**

在 `tests/test_workflows.py` 加入：

```python
    def test_ghcr_release_is_versioned_minimal_and_cli_first(self):
        workflow = (ROOT / ".github" / "workflows" / "ghcr.yml").read_text(encoding="utf-8")
        required = (
            'tags: ["v*.*.*"]',
            "workflow_dispatch:",
            "contents: read",
            "packages: write",
            "ghcr.io/yugarden404/specgate",
            "docker/login-action@v3",
            "docker/setup-buildx-action@v3",
            "docker/build-push-action@v6",
            "platforms: linux/amd64",
            "push: true",
            "${{ steps.version.outputs.version }}",
            "${{ steps.version.outputs.minor }}",
            "latest",
            "sha-${{ steps.version.outputs.short_sha }}",
            "docker run --rm $IMAGE:$VERSION --help",
            "run-mock-demo /opt/specgate/examples/knowledge_nav",
            "--entrypoint specgate-web",
        )
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, workflow)
        self.assertNotIn("OPENAI_COMPATIBLE_API_KEY", workflow)
        self.assertNotIn("pull_request:", workflow)
```

- [ ] **Step 2: 运行测试并确认 workflow 文件缺失**

Run:

```powershell
python -m unittest tests.test_workflows.WorkflowTests.test_ghcr_release_is_versioned_minimal_and_cli_first -v
```

Expected: FAIL，包含 `FileNotFoundError`。

- [ ] **Step 3: 创建 GHCR workflow**

创建 `.github/workflows/ghcr.yml`：

```yaml
name: GHCR

on:
  push:
    tags: ["v*.*.*"]
  workflow_dispatch:
    inputs:
      version:
        description: Existing release version without the v prefix
        required: true
        type: string

permissions:
  contents: read
  packages: write

env:
  IMAGE: ghcr.io/yugarden404/specgate

jobs:
  publish:
    name: publish-ghcr
    runs-on: ubuntu-latest

    steps:
      - name: Check out release tag
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event_name == 'workflow_dispatch' && format('refs/tags/v{0}', inputs.version) || github.ref }}

      - name: Validate release version
        id: version
        shell: bash
        env:
          EVENT_NAME: ${{ github.event_name }}
          REF_NAME: ${{ github.ref_name }}
          INPUT_VERSION: ${{ inputs.version }}
        run: |
          set -euo pipefail
          project_version="$(python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')"
          requested_version="$project_version"
          if [ "$EVENT_NAME" = "push" ]; then
            test "$REF_NAME" = "v$project_version"
          else
            test "$INPUT_VERSION" = "$project_version"
            requested_version="$INPUT_VERSION"
          fi
          minor="${requested_version%.*}"
          short_sha="$(git rev-parse --short=12 HEAD)"
          echo "version=$requested_version" >> "$GITHUB_OUTPUT"
          echo "minor=$minor" >> "$GITHUB_OUTPUT"
          echo "short_sha=$short_sha" >> "$GITHUB_OUTPUT"
          echo "full_sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push versioned image
        id: push
        uses: docker/build-push-action@v6
        with:
          context: .
          platforms: linux/amd64
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ steps.version.outputs.version }}
            ${{ env.IMAGE }}:${{ steps.version.outputs.minor }}
            ${{ env.IMAGE }}:latest
            ${{ env.IMAGE }}:sha-${{ steps.version.outputs.short_sha }}
          labels: |
            org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}
            org.opencontainers.image.version=${{ steps.version.outputs.version }}
            org.opencontainers.image.revision=${{ steps.version.outputs.full_sha }}
            org.opencontainers.image.description=SpecGate CLI-first Coding Agent Harness
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke test published image
        shell: bash
        env:
          VERSION: ${{ steps.version.outputs.version }}
        run: |
          set -euo pipefail
          docker pull $IMAGE:$VERSION
          docker run --rm $IMAGE:$VERSION --help
          docker run --rm $IMAGE:$VERSION run-mock-demo /opt/specgate/examples/knowledge_nav
          docker run --rm --entrypoint specgate-web $IMAGE:$VERSION --help

      - name: Record immutable digest
        run: |
          echo "Image: $IMAGE:${{ steps.version.outputs.version }}" >> "$GITHUB_STEP_SUMMARY"
          echo "Digest: ${{ steps.push.outputs.digest }}" >> "$GITHUB_STEP_SUMMARY"
```

- [ ] **Step 4: 运行 workflow 契约测试**

Run:

```powershell
python -m unittest tests.test_workflows -v
```

Expected: 全部通过，`OK`。

- [ ] **Step 5: 手动提交 GHCR workflow**

```powershell
git add -- .github/workflows/ghcr.yml tests/test_workflows.py
git diff --cached --check
git commit -m "ci: 添加 GHCR 版本镜像发布"
```

---

### Task 6: 用户文档与发布前事实边界

**Files:**
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1: 写 CLI 使用和“远端待验证”事实测试**

在 `tests/test_final_evidence.py` 增加：

```python
    def test_cli_quickstart_and_ghcr_release_boundary_are_documented(self):
        readme = read_text("README.md")
        deployment = read_text("docs/DEPLOYMENT.md")
        combined = "\n".join((readme, deployment))
        for phrase in (
            "specgate configure",
            "specgate run <工作区>",
            "SPECGATE_LLM_BASE_URL",
            "SPECGATE_LLM_MODEL",
            "OPENAI_COMPATIBLE_API_KEY",
            "ghcr.io/yugarden404/specgate:0.1.0",
            "--entrypoint specgate-web",
            "发布镜像不等于部署服务",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

        factual = "\n".join(
            read_text(path)
            for path in (
                "PLAN.md",
                "AGENT_LOG.md",
                "docs/FINAL_EVIDENCE_MATRIX.md",
                "docs/FINAL_SUBMISSION_CHECKLIST.md",
                "docs/REFLECTION_FACT_CHECK.md",
            )
        )
        self.assertIn("GHCR 发布工作流已实现，远端公开性待验证", factual)
        self.assertNotIn("GHCR 公开镜像已完成匿名拉取验证", factual)
```

- [ ] **Step 2: 运行测试并确认缺少新命令和镜像说明**

Run:

```powershell
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_cli_quickstart_and_ghcr_release_boundary_are_documented -v
```

Expected: FAIL，缺少 `specgate configure` 或 GHCR 地址。

- [ ] **Step 3: 更新 README 和部署文档**

在 `README.md` 的安装后增加“首次配置与日常运行”，明确包含：

```markdown
## 首次配置与日常运行

首次使用真实 OpenAI-compatible provider 时执行：

```powershell
specgate configure
```

Base URL 与 Model 保存到当前用户配置，API key 通过隐藏输入保存到系统 keyring。之后每个单目录工作区只需包含 `TASK_SPEC.md`、`CHECKLIST.md` 和可选 `index.html`，并运行：

```powershell
specgate run <工作区>
```

命令行参数优先于 `SPECGATE_LLM_BASE_URL` / `SPECGATE_LLM_MODEL`，环境变量优先于用户配置；API key 仍按 `OPENAI_COMPATIBLE_API_KEY`、系统 keyring 的顺序读取。
```

在 `README.md` 和 `docs/DEPLOYMENT.md` 的 Docker 部分把默认启动改为 CLI，并加入：

```powershell
docker pull ghcr.io/yugarden404/specgate:0.1.0
docker run --rm ghcr.io/yugarden404/specgate:0.1.0 --help
docker run --rm `
  --env-file "$HOME\.specgate.env" `
  -v "D:\Projects\my-page:/workspace" `
  ghcr.io/yugarden404/specgate:0.1.0 `
  run /workspace
docker run --rm -p 8000:8000 `
  --entrypoint specgate-web `
  ghcr.io/yugarden404/specgate:0.1.0 `
  --host 0.0.0.0 --port 8000
```

紧随命令说明：`--env-file` 由 Docker 读取，应位于仓库外且不得提交；SpecGate 本身仍不读取 `.env`。发布镜像不等于部署服务。

- [ ] **Step 4: 更新实现阶段事实文档**

在 `PLAN.md`、`AGENT_LOG.md`、证据矩阵、提交清单和事实核对文档新增 2026-07-18 小节，统一使用：

```text
GHCR 发布工作流已实现，远端公开性待验证
```

此阶段继续把“公开容器 registry”表格状态保留为“待完成”，并明确需要版本标签、成功 workflow、Public Package 页面和匿名 pull 后才能改为“已完成”。不得加入“GHCR 公开镜像已完成匿名拉取验证”。

- [ ] **Step 5: 运行文档与目标测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows tests.test_user_config tests.test_cli -v
```

Expected: 全部通过，`OK`。

- [ ] **Step 6: 手动提交发布前文档**

```powershell
git add -- `
  README.md `
  docs/DEPLOYMENT.md `
  PLAN.md `
  AGENT_LOG.md `
  docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/REFLECTION_FACT_CHECK.md `
  tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 说明 CLI 快速运行与 GHCR 发布边界"
```

---

### Task 7: 本地完整验证与发布 PR

**Files:**
- Verify only; do not change evidence status to complete.

- [ ] **Step 1: 运行完整 Python 测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: exit code 0，`OK`；记录实际测试数、耗时和 skipped 数，不沿用旧数字。

- [ ] **Step 2: 运行差异与敏感信息检查**

由用户执行：

```powershell
git diff --check
git status --short --branch
git grep -n -E "sk-[A-Za-z0-9_-]{8,}|OPENAI_COMPATIBLE_API_KEY=.+" -- . ":(exclude)docs/evidence/*"
```

Expected: `git diff --check` 无错误；敏感信息扫描不出现真实 key。测试夹具中的明显假值应逐项确认。

- [ ] **Step 3: 推送并创建 GitHub PR**

由用户执行：

```powershell
git push -u origin ghcr-cli-distribution
```

PR 标题：

```text
feat: 改进 CLI 配置并发布 GHCR 镜像
```

PR 正文必须说明：CLI 配置、Docker 默认入口、GHCR 版本发布、测试结果，以及“当前 workflow 已实现但镜像公开性要等标签发布后验证”。

- [ ] **Step 4: 核对 PR checks 后合并**

Expected: GitHub CI 的 `unit-test`、`docker-build` 和 Pages 全部成功。合并前不得创建 `v0.1.0`。

---

### Task 8: 版本标签、公开 Package 与匿名验证

**Files:**
- Remote operations first; evidence files are created only after success.

- [ ] **Step 1: 更新本地 main 并确认发布 commit**

由用户在主工作区执行：

```powershell
git switch main
git pull --ff-only
git log -1 --oneline
git status --short --branch
```

Expected: clean `main` 与 `origin/main` 对齐，HEAD 是 GHCR 功能 PR 的 merge commit。

- [ ] **Step 2: 创建并推送版本标签**

由用户执行：

```powershell
git tag -a v0.1.0 -m "release: SpecGate 0.1.0"
git push origin v0.1.0
```

Expected: GitHub `GHCR` workflow 被触发；标签与 `pyproject.toml` 的 `0.1.0` 一致。

- [ ] **Step 3: 等待 GHCR workflow 成功并记录 digest**

Expected: `publish-ghcr` 完成版本校验、push、CLI help、Mock Demo 和显式 WebUI help；Actions summary 显示镜像地址和 `sha256:` digest。

- [ ] **Step 4: 将 GitHub Package visibility 改为 Public**

在 GitHub Package settings 中将 `specgate` 容器包设为 Public。不要修改仓库 Actions 权限或添加 PAT。

- [ ] **Step 5: 使用未登录浏览器和匿名 Docker 验证**

使用一次性空 Docker 配置执行，避免修改用户现有的 GHCR 登录状态：

```powershell
$previousDockerConfig = $env:DOCKER_CONFIG
$anonymousDockerConfig = Join-Path $env:TEMP ("specgate-docker-anonymous-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $anonymousDockerConfig | Out-Null
$env:DOCKER_CONFIG = $anonymousDockerConfig
docker pull ghcr.io/yugarden404/specgate:0.1.0
docker run --rm ghcr.io/yugarden404/specgate:0.1.0 --help
docker run --rm ghcr.io/yugarden404/specgate:0.1.0 run-mock-demo /opt/specgate/examples/knowledge_nav
docker image inspect ghcr.io/yugarden404/specgate:0.1.0 --format '{{json .RepoDigests}}'
if ($null -eq $previousDockerConfig) {
  Remove-Item Env:\DOCKER_CONFIG
} else {
  $env:DOCKER_CONFIG = $previousDockerConfig
}
Remove-Item -Recurse -Force -LiteralPath $anonymousDockerConfig
```

Expected: 不登录即可 pull；help 包含 `configure` 和 `run`；Mock Demo exit code 0；inspect 输出 `ghcr.io/yugarden404/specgate@sha256:...`。

- [ ] **Step 6: 保存截图与 URL**

需要用户提供：

- GHCR Actions 成功详情页截图和地址栏 URL；
- Package 页面显示 Public、`0.1.0`、`0.1`、`latest` 的截图和 URL；
- 匿名 pull、help、Mock Demo 和 digest 的终端截图；
- 功能 PR、merge commit、CI、Pages URL。

截图不得显示 API key、环境变量值、个人 token 或未遮蔽凭据。

---

### Task 9: 发布后证据同步与双仓库对齐

**Files:**
- Create: `docs/evidence/github-actions-ghcr-v0.1.0-success.png`
- Create: `docs/evidence/github-package-specgate-public.png`
- Create: `docs/evidence/ghcr-anonymous-pull-smoke.png`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1: 新建证据同步分支并写失败测试**

从已更新的 `main` 新建 `ghcr-evidence-sync`。把 `test_submission_docs_do_not_claim_public_backend_or_registry` 重命名为 `test_submission_docs_distinguish_public_registry_from_backend`，并把预期状态改为：

```python
        expected_delivery_statuses = {
            "公开静态评审入口": "已完成",
            "本地交互式 WebUI": "已完成",
            "公网交互式 Web 后端": "待完成",
            "Docker 本地与 CI 构建": "已完成",
            "公开容器 registry": "已完成",
        }
```

在 `test_delivery_docs_distinguish_github_source_and_nju_gitlab_mirror` 中，把旧断言：

```python
        self.assertNotIn("公开容器 registry | 已完成", combined)
```

替换为两个独立边界：

```python
        self.assertIn("公开容器 registry | 已完成", combined)
        self.assertNotIn("公网交互式 Web 后端 | 已完成", combined)
```

在 `test_pr20_remote_evidence_is_structurally_bound` 的 `current_delivery_sections` 循环中，旧断言要求 backend 和 registry 都没有肯定性声明。发布后将它替换为只允许固定的 registry/GHCR 声明：

```python
                claims = find_affirmative_public_deployment_claims(section)
                for claim in claims:
                    normalized = claim.lower()
                    self.assertTrue(
                        "registry" in normalized or "ghcr" in normalized,
                        msg=f"unexpected public backend claim: {claim}",
                    )
```

这保留旧证据段的否定声明检测，同时不再把已经验证的公开镜像误判为公网 Web 后端部署。

另加：

```python
    def test_public_ghcr_evidence_is_bound_without_claiming_backend_deployment(self):
        combined = "\n".join(
            read_text(path)
            for path in (
                "README.md",
                "PLAN.md",
                "AGENT_LOG.md",
                "docs/FINAL_EVIDENCE_MATRIX.md",
                "docs/FINAL_SUBMISSION_CHECKLIST.md",
                "docs/REFLECTION_FACT_CHECK.md",
            )
        )
        for phrase in (
            "ghcr.io/yugarden404/specgate:0.1.0",
            "GHCR 公开镜像已完成匿名拉取验证",
            "sha256:",
            "docs/evidence/github-actions-ghcr-v0.1.0-success.png",
            "docs/evidence/github-package-specgate-public.png",
            "docs/evidence/ghcr-anonymous-pull-smoke.png",
            "公网交互式 Web 后端未部署",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertNotIn("公网交互式 Web 后端 | 已完成", combined)
```

- [ ] **Step 2: 运行测试并确认因证据尚未同步而失败**

Run:

```powershell
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_submission_docs_distinguish_public_registry_from_backend tests.test_final_evidence.FinalEvidenceTests.test_public_ghcr_evidence_is_bound_without_claiming_backend_deployment -v
```

Expected: FAIL，公开 registry 仍为“待完成”且缺少截图路径、URL 或 digest。

- [ ] **Step 3: 保存三张脱敏截图并更新事实材料**

将用户提供的三张截图按本任务指定文件名保存。更新六份事实材料，统一加入：

```text
GHCR 公开镜像已完成匿名拉取验证
```

同时记录真实的：

- `v0.1.0` tag commit；
- GHCR Actions URL；
- Package URL；
- `sha256:` digest；
- 对应 CI 与 Pages URL；
- 三张截图路径。

把表格中的“公开容器 registry”改为“已完成”，但保持“公网交互式 Web 后端”为“待完成”，并写明“公网交互式 Web 后端未部署”。

- [ ] **Step 4: 运行目标与完整测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence -v
python -m unittest discover -s tests -v
```

Expected: 两条命令均 exit code 0，`OK`。

- [ ] **Step 5: 手动提交并通过 PR 合并证据**

```powershell
git add -- `
  README.md `
  PLAN.md `
  AGENT_LOG.md `
  docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/REFLECTION_FACT_CHECK.md `
  docs/evidence/github-actions-ghcr-v0.1.0-success.png `
  docs/evidence/github-package-specgate-public.png `
  docs/evidence/ghcr-anonymous-pull-smoke.png `
  tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 记录 GHCR 公开镜像发布证据"
git push -u origin ghcr-evidence-sync
```

PR 合并后更新本地 `main`，再把 `main` 与 tags 推送到 NJU GitLab，并核对 GitHub `main`、`origin/main`、`nju/main` 指向同一最终 commit。NJU GitLab 仍按既定计划在检查前改为 Public；GHCR 发布不改变 GitLab unit-test-only Pipeline 边界。

---

## 最终完成定义

- `specgate configure` 隐藏输入并安全保存配置。
- `specgate run <工作区>` 无需重复输入 Model 和 Base URL。
- 配置优先级、工作区预检、旧参数和凭据边界有自动测试。
- Docker 默认入口为 CLI，显式 WebUI 入口仍可运行。
- `v0.1.0` 触发的 GHCR workflow 成功并记录 digest。
- Package 为 Public，匿名 pull、help 和 Mock Demo 均成功。
- 文档只在远端证据成立后把公开 registry 标为已完成。
- 公网交互式 Web 后端始终明确为未部署。
- GitHub 与 NJU GitLab 最终 main 和 tags 同步。
