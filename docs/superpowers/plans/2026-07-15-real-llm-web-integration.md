# SpecGate Web 真实 LLM 接入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持 Web 默认 MockLLM 和现有 Harness 治理链不变的前提下，让完整配置 API Key、Base URL 与 Model 的用户通过 OpenAI-compatible Chat Completions 创建或修改 `index.html`。

**Architecture:** 使用独立 `LLMRunConfig` 冻结 run 模式，使用 `LLMEndpointPolicy`、`PublicDNSResolver` 和 `SafeHTTPSChatTransport` 封装公网 HTTPS、DNS 固定、重试、取消与响应上限，使用 `WebLLMFactory` 统一首次执行和审批恢复。真实输出仍只作为严格 JSON Action 输入现有 Runner、WorkspacePolicy、HITL、Gate 和发布 SHA-256 链路。

**Tech Stack:** Python 3.11、标准库 `http.client` / `ssl` / `socket` / `ipaddress`、SQLite WAL、FastAPI、AES-256-GCM、原生 JavaScript、`unittest`、Fake Resolver/Transport/Clock。

---

## 文件职责与依赖

新增文件：

- `src/specgate/llm_config.py`：严格 `LLMRunConfig`、规范 JSON、快照错误。
- `src/specgate/llm_transport.py`：部署网络配置、URL 规范化、DNS 公网校验、固定 IP HTTPS、重试和大小限制。
- `src/specgate/web_llm.py`：设置状态机、run 配置冻结、凭据绑定 LLM、`WebLLMFactory`、连接测试限流。
- `tests/test_llm_config.py`：快照 schema 和规范 JSON。
- `tests/test_llm_transport.py`：SSRF、DNS、TLS、重试、取消、响应上限。
- `tests/test_web_llm.py`：模式、凭据变化、Factory 和连接测试。

主要修改文件：

- `src/specgate/web_credentials.py`：不可逆凭据指纹和匹配读取。
- `src/specgate/web_db.py`：schema v5 与历史 Mock 快照迁移。
- `src/specgate/llm.py`：通过可注入 Transport 调用 Chat Completions，保持 `LLMClient` 接口。
- `src/specgate/web_runtime.py`：暴露单调时钟剩余执行时间。
- `src/specgate/web_runs.py`：冻结 LLM 配置并通过 Factory 构造 Runner。
- `src/specgate/web_settings.py`：URL/Model 设置与脱敏模式状态。
- `src/specgate/web_app.py`：Factory 装配、设置字段、连接测试 API、错误映射。
- `src/specgate/web_static/app.js`：模型配置、模式提示和测试连接交互。

依赖顺序：Task 1 → Task 2；Task 3 → Task 4 → Task 5；Task 1、3、5 → Task 6；Task 2、6 → Task 7 → Task 8；Task 6 → Task 9 → Task 10；之后执行 Task 11、12。Task 1/2 与 Task 3/4 在隔离 worktree 中理论上可并行，但本分支若采用 Inline Execution 则按编号顺序执行，避免共享文件冲突。

Git 暂存、commit、push 和 PR 均由用户执行；每个任务末尾给出建议命令，不由执行 Agent 自动运行。

---

### Task 1：严格 LLM 快照与凭据指纹

**Files:**

- Create: `src/specgate/llm_config.py`
- Create: `tests/test_llm_config.py`
- Modify: `src/specgate/web_credentials.py:20-300`
- Modify: `tests/test_web_credentials.py:1-140`

- [ ] **Step 1：写 `LLMRunConfig` 失败测试**

在 `tests/test_llm_config.py` 写入：

```python
import json
import unittest

from specgate.llm_config import LLMConfigError, LLMRunConfig


class LLMRunConfigTests(unittest.TestCase):
    def test_mock_and_real_snapshots_round_trip_canonically(self):
        mock = LLMRunConfig.mock()
        real = LLMRunConfig.real(
            "https://api.example.test/v1",
            "test-model",
            "a" * 64,
        )
        self.assertEqual(LLMRunConfig.from_json(mock.to_json()), mock)
        self.assertEqual(LLMRunConfig.from_json(real.to_json()), real)
        self.assertEqual(json.loads(mock.to_json())["source"], "created")

    def test_mock_rejects_real_fields_and_real_requires_all_fields(self):
        with self.assertRaises(LLMConfigError):
            LLMRunConfig(mode="mock", model="test-model")
        with self.assertRaises(LLMConfigError):
            LLMRunConfig(mode="openai-compatible", base_url=None)

    def test_json_rejects_unknown_missing_bool_schema_and_bad_fingerprint(self):
        valid = LLMRunConfig.mock().to_dict()
        invalid = (
            {**valid, "unknown": 1},
            {key: value for key, value in valid.items() if key != "mode"},
            {**valid, "schema_version": True},
            {
                **LLMRunConfig.real("https://api.example.test/v1", "m", "a" * 64).to_dict(),
                "credential_fingerprint": "not-a-sha256",
            },
        )
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(LLMConfigError):
                LLMRunConfig.from_json(json.dumps(payload))
```

- [ ] **Step 2：运行快照测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_llm_config -v
```

Expected: `ModuleNotFoundError: No module named 'specgate.llm_config'`。

- [ ] **Step 3：实现严格快照最小代码**

`src/specgate/llm_config.py` 使用与 `runtime_config.py` 相同的严格模式：

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Literal


class LLMConfigError(ValueError):
    code = "invalid_llm_config"

    def __init__(self, field: str):
        self.field = field
        super().__init__("LLM 配置快照无效 / Invalid LLM configuration snapshot")


@dataclass(frozen=True)
class LLMRunConfig:
    schema_version: int = 1
    source: Literal["created", "migration-v5"] = "created"
    mode: Literal["mock", "openai-compatible"] = "mock"
    base_url: str | None = None
    model: str | None = None
    credential_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise LLMConfigError("schema_version")
        if self.source not in {"created", "migration-v5"}:
            raise LLMConfigError("source")
        if self.mode == "mock":
            if any(value is not None for value in (self.base_url, self.model, self.credential_fingerprint)):
                raise LLMConfigError("mode")
            return
        if self.mode != "openai-compatible":
            raise LLMConfigError("mode")
        if not isinstance(self.base_url, str) or not self.base_url:
            raise LLMConfigError("base_url")
        if not isinstance(self.model, str) or not self.model:
            raise LLMConfigError("model")
        fingerprint = self.credential_fingerprint
        if not isinstance(fingerprint, str) or len(fingerprint) != 64:
            raise LLMConfigError("credential_fingerprint")
        if any(char not in "0123456789abcdef" for char in fingerprint):
            raise LLMConfigError("credential_fingerprint")

    @classmethod
    def mock(cls, *, source: Literal["created", "migration-v5"] = "created") -> "LLMRunConfig":
        return cls(source=source)

    @classmethod
    def real(cls, base_url: str, model: str, fingerprint: str) -> "LLMRunConfig":
        return cls(
            mode="openai-compatible",
            base_url=base_url,
            model=model,
            credential_fingerprint=fingerprint,
        )

    @classmethod
    def from_json(cls, raw: str) -> "LLMRunConfig":
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise LLMConfigError("llm_config_json") from exc
        expected = {field.name for field in fields(cls)}
        if not isinstance(payload, dict) or set(payload) != expected:
            raise LLMConfigError("llm_config_json")
        try:
            return cls(**payload)
        except TypeError as exc:
            raise LLMConfigError("llm_config_json") from exc

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
```

- [ ] **Step 4：写凭据指纹与匹配读取失败测试**

在 `tests/test_web_credentials.py` 增加：

```python
def test_fingerprint_changes_on_reentry_and_matching_get_fails_closed(self):
    db_path, user_id = self.make_database_user()
    service = WebCredentialService.from_key_value(db_path, TEST_KEY)
    service.put(user_id, "SENTINEL_secret")
    first = service.snapshot(user_id)
    self.assertEqual(len(first.fingerprint), 64)
    self.assertEqual(service.get_matching(user_id, first.fingerprint), "SENTINEL_secret")

    service.put(user_id, "SENTINEL_secret")
    second = service.snapshot(user_id)
    self.assertNotEqual(first.fingerprint, second.fingerprint)
    with self.assertRaises(CredentialChanged):
        service.get_matching(user_id, first.fingerprint)

def test_missing_credential_has_no_fingerprint(self):
    db_path, user_id = self.make_database_user()
    service = WebCredentialService.from_key_value(db_path, TEST_KEY)
    snapshot = service.snapshot(user_id)
    self.assertFalse(snapshot.exists)
    self.assertIsNone(snapshot.fingerprint)
```

- [ ] **Step 5：运行凭据测试确认 RED**

Run: `python -m unittest tests.test_web_credentials -v`

Expected: FAIL，缺少 `snapshot`、`get_matching` 和 `CredentialChanged`。

- [ ] **Step 6：实现指纹与原子匹配读取**

在 `web_credentials.py` 增加 `CredentialSnapshot`、`CredentialMissing`、`CredentialChanged`。指纹对 provider、status、ciphertext、nonce、key_version、key_id、updated_at 做带字段名和长度的 SHA-256；使用 `hmac.compare_digest` 比较。`snapshot(user_id, conn=None)` 必须允许复用外部事务连接；`get_matching()` 从同一行计算指纹后再解密，不先调用独立的 `status()`。

核心接口固定为：

```python
@dataclass(frozen=True)
class CredentialSnapshot:
    exists: bool
    configured: bool
    requires_reentry: bool
    store_available: bool
    fingerprint: str | None

class CredentialMissing(WebCredentialError):
    code = "credential_missing"

class CredentialChanged(WebCredentialError):
    code = "credential_changed"

def snapshot(self, user_id: int, *, conn=None) -> CredentialSnapshot:
    owned = conn is None
    active = connect_db(self.db_path) if owned else conn
    try:
        row = self._load_from_connection(active, user_id)
        if row is None:
            return CredentialSnapshot(False, False, False, self.cipher is not None, None)
        status = self._status_from_row(row)
        return CredentialSnapshot(
            True,
            status.configured,
            status.requires_reentry,
            status.store_available,
            _credential_fingerprint(row),
        )
    finally:
        if owned:
            active.close()

def get_matching(self, user_id: int, expected_fingerprint: str) -> str:
    row = self._load(user_id)
    if row is None:
        raise CredentialMissing("credential_missing")
    actual = _credential_fingerprint(row)
    if not hmac.compare_digest(actual, expected_fingerprint):
        raise CredentialChanged("credential_changed")
    return self._decrypt_row(user_id, row)
```

- [ ] **Step 7：运行 Task 1 测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_llm_config tests.test_web_credentials -v
```

Expected: PASS，且 canary secret 不出现在异常文本。

- [ ] **Step 8：建议用户提交 Task 1**

```powershell
git add src/specgate/llm_config.py src/specgate/web_credentials.py tests/test_llm_config.py tests/test_web_credentials.py
git commit -m "feat: 增加 LLM 快照与凭据指纹"
```

---

### Task 2：数据库 schema v5 与历史 Mock 迁移

**Files:**

- Modify: `src/specgate/web_db.py:1-260`
- Modify: `tests/test_web_db.py:1-520`

- [ ] **Step 1：写 v5 新库和迁移失败测试**

在 `tests/test_web_db.py` 更新旧版本断言并增加：

```python
def test_new_database_uses_schema_v5_llm_columns(self):
    db_path = self.make_database_path()
    init_db(db_path)
    with closing(connect_db(db_path)) as conn:
        self.assertEqual(conn.execute("pragma user_version").fetchone()[0], 5)
        settings = self.table_columns(conn, "user_settings")
        runs = self.table_columns(conn, "runs")
    self.assertIn("llm_base_url", settings)
    self.assertIn("llm_model", settings)
    self.assertIn("llm_config_json", runs)

def test_v4_migration_marks_all_historical_runs_as_mock(self):
    db_path = self.create_version_four_database_with_run()
    init_db(db_path)
    with closing(connect_db(db_path)) as conn:
        raw = conn.execute("select llm_config_json from runs").fetchone()[0]
    config = LLMRunConfig.from_json(raw)
    self.assertEqual(config.mode, "mock")
    self.assertEqual(config.source, "migration-v5")
```

同时为 `_migrate_v4_to_v5` 注入失败，断言 user version 仍为 4 且没有半回填快照。

- [ ] **Step 2：运行数据库测试确认 RED**

Run: `python -m unittest tests.test_web_db -v`

Expected: FAIL，当前版本为 4 且缺少三列。

- [ ] **Step 3：实现 v5 schema 和事务迁移**

修改：

```python
LATEST_SCHEMA_VERSION = 5
```

新库 schema 增加：

```sql
llm_base_url text,
llm_model text
```

以及：

```sql
llm_config_json text
```

新增 `_migrate_v4_to_v5()`，使用 `LLMRunConfig.mock(source="migration-v5").to_json()` 回填每个历史 run，检查空值后才设置版本 5。`init_db()` 在 v4 后继续调用 v5 迁移。

- [ ] **Step 4：运行全量迁移组合确认 GREEN**

Run: `python -m unittest tests.test_web_db tests.test_llm_config -v`

Expected: v1/v2/v3/v4 升级、新库、幂等和未来版本拒绝测试全部 PASS。

- [ ] **Step 5：建议用户提交 Task 2**

```powershell
git add src/specgate/web_db.py tests/test_web_db.py
git commit -m "feat: 迁移 Web 数据库至 LLM 配置快照 v5"
```

---

### Task 3：部署网络配置、URL 白名单与公网 DNS

本任务先完成 SSRF 静态与解析边界；Task 4 使用这里返回的已验证 IP 固定连接，从而关闭 DNS Rebinding 窗口。

**Files:**

- Create: `src/specgate/llm_transport.py`
- Create: `tests/test_llm_transport.py`

- [ ] **Step 1：写部署配置和 URL 失败测试**

测试至少包含：

```python
class LLMEndpointPolicyTests(unittest.TestCase):
    def test_empty_allowlist_is_mock_only(self):
        config = load_llm_network_config({})
        with self.assertRaisesRegex(LLMTransportError, "llm_host_not_allowed"):
            config.endpoint_policy.normalize("https://api.example.test/v1")

    def test_exact_https_host_and_explicit_port_are_required(self):
        policy = LLMEndpointPolicy.from_csv("api.example.test,alt.example.test:8443")
        endpoint = policy.normalize("https://API.EXAMPLE.TEST/v1/")
        self.assertEqual(endpoint.base_url, "https://api.example.test/v1")
        self.assertEqual(endpoint.chat_path, "/v1/chat/completions")
        with self.assertRaises(LLMTransportError):
            policy.normalize("http://api.example.test/v1")
        with self.assertRaises(LLMTransportError):
            policy.normalize("https://api.example.test:8443/v1")

    def test_rejects_userinfo_query_fragment_ip_literal_and_dot_segments(self):
        policy = LLMEndpointPolicy.from_csv("api.example.test")
        for value in (
            "https://user:pass@api.example.test/v1",
            "https://api.example.test/v1?key=value",
            "https://api.example.test/v1#fragment",
            "https://127.0.0.1/v1",
            "https://api.example.test/v1/../admin",
        ):
            with self.subTest(value=value), self.assertRaises(LLMTransportError):
                policy.normalize(value)
```

- [ ] **Step 2：写 DNS 分类失败测试**

使用注入的 `getaddrinfo` 返回 IPv4/IPv6，断言全部公网才成功；`127.0.0.1`、`10.0.0.1`、`169.254.169.254`、`::1`、保留地址及“公网 + 私网”整体拒绝。断言错误文本只含稳定 code，不含底层 resolver reason。

- [ ] **Step 3：运行 Transport 测试确认 RED**

Run: `python -m unittest tests.test_llm_transport -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 4：实现配置、Endpoint 与 Resolver**

核心类型：

```python
class LLMTransportError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False, status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.status = status
        super().__init__(code)

@dataclass(frozen=True)
class LLMNetworkConfig:
    endpoint_policy: "LLMEndpointPolicy"
    max_output_tokens: int = 4096
    request_timeout_seconds: int = 30
    max_response_bytes: int = 1024 * 1024

@dataclass(frozen=True)
class NormalizedEndpoint:
    base_url: str
    host: str
    port: int
    chat_path: str
    authority: str
```

`load_llm_network_config()` 严格解析三个 `SPECGATE_LLM_*` 环境变量。Resolver 使用 `ThreadPoolExecutor(max_workers=4, thread_name_prefix="specgate-llm-dns")`，返回去重且排序稳定的公网 IP tuple；容量或 timeout 失败返回 `llm_dns_resolution_failed`。

- [ ] **Step 5：运行 URL/DNS 测试确认 GREEN**

Run: `python -m unittest tests.test_llm_transport -v`

Expected: URL、IDNA、端口、IP 分类和混合解析测试 PASS，无真实 DNS 请求。

- [ ] **Step 6：建议用户提交 Task 3**

```powershell
git add src/specgate/llm_transport.py tests/test_llm_transport.py
git commit -m "feat: 加固 LLM 地址与公网 DNS 边界"
```

---

### Task 4：固定 IP HTTPS、响应上限、重试与取消

**Files:**

- Modify: `src/specgate/llm_transport.py`
- Modify: `tests/test_llm_transport.py`
- Modify: `src/specgate/web_runtime.py:70-100`
- Modify: `tests/test_web_runtime.py`

- [ ] **Step 1：写 `RunControl.remaining_seconds()` 失败测试**

```python
def test_run_control_reports_non_negative_remaining_seconds(self):
    now = [10.0]
    control = RunControl(Event(), "deadline", 15.0, lambda: now[0])
    self.assertEqual(control.remaining_seconds(), 5.0)
    now[0] = 16.0
    self.assertEqual(control.remaining_seconds(), 0.0)
```

- [ ] **Step 2：实现剩余时间并确认 GREEN**

```python
def remaining_seconds(self) -> float:
    return max(0.0, self.deadline_monotonic - self.monotonic_clock())
```

Run: `python -m unittest tests.test_web_runtime -v`

- [ ] **Step 3：写固定连接和禁止重定向失败测试**

Fake Connection 必须记录：连接 IP、TLS server hostname、`Host`、path、timeout。断言域名只由 Fake Resolver 解析一次，Transport 连接已验证 IP；`301/302/303/307/308` 均返回 `llm_redirect_forbidden` 且不读取 `Location`。

- [ ] **Step 4：写响应大小和错误正文失败测试**

覆盖：

- `Content-Length` 大于 1 MiB 立即拒绝。
- 无长度时分块越界关闭连接。
- `401/403/404/429/500` 的 response body 中放入唯一 canary，断言异常、日志和 `repr` 均不含 canary。
- 成功响应 UTF-8/JSON 留给上层解析，Transport 只返回受限 bytes。

- [ ] **Step 5：写重试、deadline 和取消失败测试**

表驱动断言：

```python
retryable = (408, 429, 500, 503)
non_retryable = (400, 401, 403, 404, 422, 301)
```

Fake sleeper 记录约 0.5、1.0 秒；总调用不超过 3。`stop_check` 在退避和读取时抛 `RunCancelled` 应立即停止；`remaining_seconds()` 小于下一次尝试所需时间时抛 `RunTimedOut`，不再连接。

- [ ] **Step 6：实现 `_PinnedHTTPSConnection` 和有界读取**

核心连接方式：

```python
class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, connect_ip: str, *, timeout: float, context):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self.connect_ip = connect_ip

    def connect(self) -> None:
        raw = socket.create_connection((self.connect_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise
```

请求显式传 `Host: endpoint.authority`，使用默认 `ssl.create_default_context()`，不调用 urllib proxy handler。读取循环每次最多 64 KiB，并在每块前后调用 stop check。

- [ ] **Step 7：实现有界三次尝试状态机**

`SafeHTTPSChatTransport.post_json()` 参数固定为 Endpoint、headers、body、stop check 和 remaining seconds。HTTP 映射：401/403 → `llm_authentication_failed`；400/404/422 → `llm_request_rejected`；429 → `llm_rate_limited`；5xx → `llm_provider_unavailable`；408/网络 timeout → `llm_request_timeout`。redirect 和 TLS 使用专用 code。

- [ ] **Step 8：运行 Task 4 测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_llm_transport tests.test_web_runtime -v
```

Expected: 所有 Fake 测试 PASS，运行时间不包含真实退避或网络等待。

- [ ] **Step 9：建议用户提交 Task 4**

```powershell
git add src/specgate/llm_transport.py src/specgate/web_runtime.py tests/test_llm_transport.py tests/test_web_runtime.py
git commit -m "feat: 实现有界安全 LLM HTTPS 传输"
```

---

### Task 5：通过可注入 Transport 加固 Chat Completions 客户端

**Files:**

- Modify: `src/specgate/llm.py:1-110`
- Modify: `tests/test_llm.py:1-140`

- [ ] **Step 1：写 Transport 注入和响应校验失败测试**

新增 Fake Transport：

```python
class FakeChatTransport:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = []

    def post_json(self, endpoint, headers, body, *, stop_check, remaining_seconds):
        self.calls.append((endpoint, headers, json.loads(body)))
        return self.payload
```

断言：

- body 只含 `model`、`messages`、`temperature`、`max_tokens`。
- system prompt 要求一个严格 JSON Action。
- 正确提取 content。
- 非 UTF-8、非法 JSON、空 choices、非字符串 content 均返回 `llm_response_invalid`。
- `repr(llm)`、异常和 Fake 日志不含 API Key。

- [ ] **Step 2：运行 LLM 测试确认 RED**

Run: `python -m unittest tests.test_llm -v`

Expected: FAIL，构造器不支持安全 Transport 或错误 code。

- [ ] **Step 3：重构 `OpenAICompatibleLLM`**

保持：

```python
class LLMClient(Protocol):
    def complete(self, context: str) -> str:
        raise NotImplementedError
```

构造器保持现有前三个位置参数以兼容 CLI，并增加仅供安全 Web 路径使用的关键字参数：

```python
def __init__(
    self,
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int = 4096,
    timeout: float = 60,
    user_agent: str = "SpecGate/0.1 OpenAI-Compatible",
    opener=request.urlopen,
    *,
    endpoint: NormalizedEndpoint | None = None,
    transport: SafeHTTPSChatTransport | None = None,
    stop_check: Callable[[], None] = lambda: None,
    remaining_seconds: Callable[[], float] = lambda: 60.0,
):
    if transport is not None and endpoint is None:
        raise ValueError("endpoint is required with safe transport")
```

Web Factory 必须同时注入 `endpoint` 与 `SafeHTTPSChatTransport`。只有 `transport is None` 时才使用现有 opener adapter，以保持 CLI 和旧测试兼容；Web Factory 不得调用该 adapter。`LLMProviderError` 增加稳定 `code`，`str(exc)` 只返回 code 或固定安全消息。

- [ ] **Step 4：运行 LLM 与 CLI 回归确认 GREEN**

Run:

```powershell
python -m unittest tests.test_llm tests.test_cli -v
```

Expected: 新 Transport 测试和现有 CLI `run-real` 脱敏测试全部 PASS。

- [ ] **Step 5：建议用户提交 Task 5**

```powershell
git add src/specgate/llm.py tests/test_llm.py tests/test_cli.py
git commit -m "feat: 接通安全 Chat Completions 客户端"
```

---

### Task 6：模式冻结、凭据绑定与 `WebLLMFactory`

**Files:**

- Create: `src/specgate/web_llm.py`
- Create: `tests/test_web_llm.py`
- Modify: `src/specgate/web_credentials.py`

- [ ] **Step 1：写模式冻结失败测试**

构造临时数据库用户，覆盖：

```python
def test_freeze_config_defaults_to_mock_without_credential(self):
    config = factory.freeze_config(conn, user_id)
    self.assertEqual(config, LLMRunConfig.mock())

def test_freeze_config_uses_real_mode_when_all_fields_exist(self):
    save_llm_settings(conn, user_id, "https://api.example.test/v1", "test-model")
    credentials.put(user_id, "secret")
    config = factory.freeze_config(conn, user_id)
    self.assertEqual(config.mode, "openai-compatible")
    self.assertEqual(config.model, "test-model")

def test_present_key_with_missing_model_fails_instead_of_mock(self):
    credentials.put(user_id, "secret")
    with self.assertRaisesRegex(WebLLMError, "llm_configuration_required"):
        factory.freeze_config(conn, user_id)
```

另测 requires_reentry、store unavailable、URL 不在白名单和只有 URL/Model 无 Key。

- [ ] **Step 2：写真实 LLM 每次调用重新检查 fingerprint 测试**

Fake Transport 返回合法 choices。第一次 `complete()` 成功；重新保存相同 Key 后第二次抛 `credential_changed`，Transport call 数不增加。清除 Key 后返回 `credential_missing`。异常文本不含 Key/fingerprint。

- [ ] **Step 3：运行 Factory 测试确认 RED**

Run: `python -m unittest tests.test_web_llm -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 4：实现设置状态机和 Factory**

接口固定为：

```python
class WebLLMError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)

class WebLLMFactory:
    def __init__(
        self,
        credentials,
        endpoint_policy,
        transport_factory,
        *,
        max_output_tokens: int = 4096,
        monotonic_clock: Callable[[], float] = monotonic,
    ):
        self.credentials = credentials
        self.endpoint_policy = endpoint_policy
        self.transport_factory = transport_factory
        self.max_output_tokens = max_output_tokens
        self.monotonic_clock = monotonic_clock

    @classmethod
    def mock_only(cls) -> "WebLLMFactory":
        return cls(None, LLMEndpointPolicy.from_csv(""), None)

    def freeze_config(self, conn, user_id: int) -> LLMRunConfig:
        row = conn.execute(
            "select llm_base_url, llm_model from user_settings where user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise WebLLMError("llm_configuration_required")
        snapshot = self.credentials.snapshot(user_id, conn=conn)
        if not snapshot.exists:
            return LLMRunConfig.mock()
        if not snapshot.configured or snapshot.fingerprint is None:
            raise WebLLMError(
                "credential_requires_reentry"
                if snapshot.requires_reentry
                else "credential_unavailable"
            )
        if not row["llm_base_url"] or not row["llm_model"]:
            raise WebLLMError("llm_configuration_required")
        endpoint = self.endpoint_policy.normalize(row["llm_base_url"])
        model = validate_llm_model(row["llm_model"])
        return LLMRunConfig.real(endpoint.base_url, model, snapshot.fingerprint)

    def build(
        self,
        config: LLMRunConfig,
        user_id: int,
        *,
        mock_responses: list[dict],
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> LLMClient:
        if config.mode == "mock":
            return MockLLM(mock_responses)
        if self.credentials is None or self.transport_factory is None:
            raise WebLLMError("llm_configuration_required")
        return self._build_real(
            config,
            user_id,
            stop_check=stop_check,
            remaining_seconds=remaining_seconds,
            max_attempts=3,
            max_output_tokens=self.max_output_tokens,
        )

    def _build_real(
        self,
        config: LLMRunConfig,
        user_id: int,
        *,
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
        max_attempts: int,
        max_output_tokens: int,
    ) -> LLMClient:
        endpoint = self.endpoint_policy.normalize(config.base_url)
        return CredentialBoundLLM(
            user_id=user_id,
            config=config,
            endpoint=endpoint,
            credentials=self.credentials,
            transport=self.transport_factory(max_attempts=max_attempts),
            max_output_tokens=max_output_tokens,
            stop_check=stop_check,
            remaining_seconds=remaining_seconds,
        )
```

真实模式返回 `CredentialBoundLLM`，其 `complete()` 每次调用 `credentials.get_matching()`，随后构造只存活一次请求的 `OpenAICompatibleLLM`。Mock-only Factory 遇到真实快照必须返回 `llm_configuration_required`，不能回退 Mock。

`CredentialBoundLLM` 的调用边界固定为：

```python
class CredentialBoundLLM:
    def __init__(
        self,
        *,
        user_id: int,
        config: LLMRunConfig,
        endpoint: NormalizedEndpoint,
        credentials: WebCredentialService,
        transport: SafeHTTPSChatTransport,
        max_output_tokens: int,
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ):
        self.user_id = user_id
        self.config = config
        self.endpoint = endpoint
        self.credentials = credentials
        self.transport = transport
        self.max_output_tokens = max_output_tokens
        self.stop_check = stop_check
        self.remaining_seconds = remaining_seconds

    def complete(self, context: str) -> str:
        self.stop_check()
        fingerprint = self.config.credential_fingerprint
        if fingerprint is None or self.config.model is None:
            raise WebLLMError("invalid_llm_config")
        api_key = self.credentials.get_matching(self.user_id, fingerprint)
        try:
            client = OpenAICompatibleLLM(
                self.endpoint.base_url,
                api_key,
                self.config.model,
                max_tokens=self.max_output_tokens,
                endpoint=self.endpoint,
                transport=self.transport,
                stop_check=self.stop_check,
                remaining_seconds=self.remaining_seconds,
            )
            return client.complete(context)
        finally:
            del api_key
```

- [ ] **Step 5：实现脱敏设置状态辅助函数**

`describe_llm_settings(base_url, model, credential_snapshot)` 返回：

```python
{
    "llm_mode": "mock | openai-compatible | configuration_required",
    "llm_configuration_complete": True | False,
}
```

不包含 fingerprint。Model 校验长度 1–256、禁止控制字符；空字符串规范为 `None`。

- [ ] **Step 6：运行 Factory 测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_llm tests.test_web_credentials tests.test_llm -v
```

Expected: 模式表、凭据变化、Mock-only fail closed 和 canary 测试全部 PASS。

- [ ] **Step 7：建议用户提交 Task 6**

```powershell
git add src/specgate/web_llm.py src/specgate/web_credentials.py tests/test_web_llm.py tests/test_web_credentials.py
git commit -m "feat: 实现 Web LLM Factory 与模式冻结"
```

---

### Task 7：创建 run 时原子冻结 LLM 配置

**Files:**

- Modify: `src/specgate/web_runs.py:157-312`
- Modify: `tests/test_web_runs.py`
- Modify: `src/specgate/web_app.py:120-240`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写创建快照失败测试**

新增测试：

- 默认 Factory 创建 run，`llm_config_json` 为 Mock。
- 完整真实设置创建 real 快照。
- Key 存在但 Model 缺失时 `create_run` 抛 `llm_configuration_required`。
- 阻断后 `runs` 行数不变、run storage 不存在、runtime reservation 被释放。
- URL/Model 和 Key 在 `BEGIN IMMEDIATE` 快照内读取。

核心断言：

```python
run = create_run(
    db_path,
    project_id,
    user_id,
    "请按 Spec 创建页面",
    data_root=data_root,
    llm_config_resolver=factory.freeze_config,
)
config = LLMRunConfig.from_json(run["llm_config_json"])
self.assertEqual(config.mode, "openai-compatible")
self.assertNotIn("SECRET_SENTINEL", config.to_json())
```

- [ ] **Step 2：运行创建测试确认 RED**

Run: `python -m unittest tests.test_web_runs tests.test_web_app -v`

Expected: FAIL，run 没有 `llm_config_json` 或不接受 resolver。

- [ ] **Step 3：扩展 `create_run()` 与 `_reserve_initializing_run()`**

新增可选参数：

```python
llm_config_resolver: Callable[[sqlite3.Connection, int], LLMRunConfig] | None = None
```

事务内在插入 run 之前调用：

```python
llm_config = (
    llm_config_resolver(conn, user_id)
    if llm_config_resolver is not None
    else LLMRunConfig.mock()
)
```

INSERT 同时写 `runtime_config_json` 与 `llm_config_json`。Web app 必须传 `app.state.web_llm_factory.freeze_config`；直接调用的旧测试默认保持 Mock。

- [ ] **Step 4：增加创建 API 安全错误映射**

配置不完整、凭据缺失/变化/重录映射为 HTTP 409；URL/主机本地错误映射为 400。失败响应只含 code、固定双语 message 和必要 field，不返回 URL、Model 之外的内部信息。

- [ ] **Step 5：运行创建与迁移测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_runs tests.test_web_app tests.test_web_db -v
```

Expected: 创建竞争、配额、初始化恢复和新 LLM 快照测试全部 PASS。

- [ ] **Step 6：建议用户提交 Task 7**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_web_runs.py tests/test_web_app.py
git commit -m "feat: 原子冻结 Web run 模型配置"
```

---

### Task 8：首次执行与审批恢复统一接入真实 LLM

**Files:**

- Modify: `src/specgate/web_runs.py:527-790,950-1085`
- Modify: `src/specgate/web_app.py:120-210`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_approvals.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写真实首次运行失败测试**

使用真实模式快照和 Fake Transport 返回两次 Action：写 `index.html`、finish。断言 SPEC、Checklist 和不存在 artifact 的说明进入 user context；完成后 Gate 通过、产物发布、run 返回冻结的 `llm_mode`/`llm_model`。

- [ ] **Step 2：写已有 HTML 审批恢复失败测试**

导入现有 `index.html`，Fake Transport 首次返回 `replace_file`：

- run 进入 `needs_approval`。
- 审批前 sentinel HTML 不变且无发布产物。
- approve 后恢复使用原 run URL/Model。
- 修改 Settings URL/Model 不影响恢复。
- 重存 Key 后恢复以 `credential_changed` 失败，不执行后续 Action、不发布。

- [ ] **Step 3：运行执行链测试确认 RED**

Run:

```powershell
python -m unittest tests.test_web_runs tests.test_web_approvals tests.test_web_app -v
```

Expected: FAIL，首次和恢复仍固定构造 `MockLLM`。

- [ ] **Step 4：统一 Runner 构造**

将 `_run_mock_agent()` 和 `_run_resume_agent()` 中重复的 Policy/Config/Runner 构造提取为以下固定接口，保持只读/只写白名单原样，不修改 Action schema：

```python
def _build_web_runner(
    paths: RunPaths,
    config: RunRuntimeConfig,
    llm: LLMClient,
    *,
    review_existing_writes: bool,
    stop_check: Callable[[], None] | None,
    reset_audit: bool,
) -> AgentRunner:
    governance = GovernanceConfig(
        profile=config.governance_profile,
        review_existing_writes=review_existing_writes,
    )
    policy = WorkspacePolicy(
        root=paths.workspace,
        allowed_actions={"read_file", "list_files", "write_file", "replace_file", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )
    return AgentRunner(
        paths.workspace,
        llm,
        policy,
        max_steps=config.max_steps,
        context_strategy=config.context_strategy,
        governance_config=governance,
        context_budget_chars=config.context_budget_chars,
        retrieval_config=RetrievalConfig(
            top_k=config.retrieval_top_k,
            budget_chars=config.retrieval_budget_chars,
        ),
        compression_config=CompressionConfig(
            max_tool_result_chars=config.compression_max_tool_result_chars,
        ),
        audit_dir=paths.audit,
        approval_queue_file=paths.approval_queue,
        reset_audit=reset_audit,
        stop_check=stop_check,
    )
```

`execute_run_once()` 与 `resume_run_once()` 接收：

```python
llm_factory: WebLLMFactory | None = None
remaining_seconds: Callable[[], float] | None = None
```

读取并严格解析 `llm_config_json`，通过 Factory build。缺省使用 `WebLLMFactory.mock_only()`，因此旧 Mock 测试兼容但真实快照不会降级。

- [ ] **Step 5：从 Coordinator 传入 stop/deadline**

`create_app.execute_runtime_task()` 同时传：

```python
stop_check=control.check,
remaining_seconds=control.remaining_seconds,
deadline_at=control.deadline_at,
llm_factory=web_llm_factory,
```

首次执行和 resume 使用同一 app-level Factory。

- [ ] **Step 6：规范化 LLM 错误停止状态**

`WebLLMError`、`LLMTransportError` 和 `LLMProviderError` 在 run 边界只保存 `exc.code`。取消仍进入 `cancelled`，总 deadline 仍进入 `timed_out`，Provider 单次 timeout 在重试耗尽后进入 `failed` + `llm_request_timeout`。

- [ ] **Step 7：运行 Runner/HITL/Gate 组合确认 GREEN**

Run:

```powershell
python -m unittest tests.test_runner tests.test_web_runs tests.test_web_approvals tests.test_web_app -v
```

Expected: 真实 Stub 创建、已有 HTML 审批、恢复、凭据变化、stale Gate 和发布哈希测试全部 PASS。

- [ ] **Step 8：建议用户提交 Task 8**

```powershell
git add src/specgate/web_runs.py src/specgate/web_app.py tests/test_runner.py tests/test_web_runs.py tests/test_web_approvals.py tests/test_web_app.py
git commit -m "feat: 接通真实 LLM 执行与审批恢复"
```

---

### Task 9：设置 API 与独立测试连接

**Files:**

- Modify: `src/specgate/web_settings.py`
- Modify: `src/specgate/web_llm.py`
- Modify: `src/specgate/web_app.py:90-225,602-665`
- Modify: `tests/test_web_settings.py`
- Modify: `tests/test_web_llm.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1：写设置读写失败测试**

覆盖：

- GET 返回 mode、URL、Model、完整性和现有 Key 状态。
- 不返回 fingerprint、ciphertext、nonce、key_id 或 secret。
- PUT URL/Model 只做静态校验，Fake Transport call 数为 0。
- Runtime 与 LLM 字段任一非法时全部不更新。
- 清除 Key 后 mode 恢复 Mock，URL/Model 可以保留。

- [ ] **Step 2：实现设置事务**

扩展 `SettingsRequest`：

```python
llm_base_url: str | None = None
llm_model: str | None = None
```

`update_settings()` 先构造 `RunRuntimeConfig`，再调用 EndpointPolicy/Model validator，全部成功后一次 UPDATE。`get_settings()` 使用 credential snapshot 和 `describe_llm_settings()`，不返回 fingerprint。

- [ ] **Step 3：写测试连接失败测试**

API 测试断言：

- `POST /api/settings/llm/test` 不接受 request body 中的 URL/Key。
- 无 Key/半配置返回 409。
- 成功返回 `{"ok": true, "mode": "openai-compatible", "message": "连接成功，模型服务可用。"}`。
- Provider 401 返回应用 HTTP 502 + `llm_authentication_failed`，不触发客户端登出。
- timeout 返回 504，应用限流返回 429。
- 不创建 run、message、approval、artifact 或项目文件。
- 返回中不包含 Provider content。

- [ ] **Step 4：实现连接测试服务和有界限流**

在 `web_llm.py` 增加：

```python
class LLMConnectionTestLimiter:
    def __init__(
        self,
        max_concurrent: int = 4,
        cooldown_seconds: float = 5.0,
        monotonic_clock: Callable[[], float] = monotonic,
    ):
        self._slots = BoundedSemaphore(max_concurrent)
        self._cooldown = cooldown_seconds
        self._clock = monotonic_clock
        self._lock = Lock()
        self._active: set[int] = set()
        self._last_finished: dict[int, float] = {}

    @contextmanager
    def acquire(self, user_id: int):
        if not self._slots.acquire(blocking=False):
            raise WebLLMError("llm_test_rate_limited")
        try:
            with self._lock:
                now = self._clock()
                last = self._last_finished.get(user_id)
                if user_id in self._active or (
                    last is not None and now - last < self._cooldown
                ):
                    raise WebLLMError("llm_test_rate_limited")
                self._active.add(user_id)
            try:
                yield
            finally:
                with self._lock:
                    self._active.discard(user_id)
                    self._last_finished[user_id] = self._clock()
        finally:
            self._slots.release()

class LLMConnectionTestService:
    def __init__(self, factory: WebLLMFactory, limiter: LLMConnectionTestLimiter):
        self.factory = factory
        self.limiter = limiter

    def test(self, user_id: int) -> dict[str, object]:
        with self.limiter.acquire(user_id):
            self.factory.test_connection(user_id, timeout_seconds=10.0)
        return {
            "ok": True,
            "mode": "openai-compatible",
            "message": "连接成功，模型服务可用。",
        }
```

同时给 `WebLLMFactory` 增加真实连接测试入口，确保它与正式 build 复用同一凭据、Endpoint 和 Transport：

```python
def test_connection(self, user_id: int, *, timeout_seconds: float) -> None:
    with closing(connect_db(self.credentials.db_path)) as conn:
        config = self.freeze_config(conn, user_id)
    if config.mode != "openai-compatible":
        raise WebLLMError("llm_configuration_required")
    deadline = self.monotonic_clock() + timeout_seconds
    llm = self._build_real(
        config,
        user_id,
        stop_check=lambda: None,
        remaining_seconds=lambda: max(0.0, deadline - self.monotonic_clock()),
        max_attempts=1,
        max_output_tokens=8,
    )
    llm.complete("连接测试：请只返回 OK。")
```

连接测试不把返回 content 交给 Action Parser。

测试调用 hard deadline 10 秒、不重试、极小 max tokens，只验证标准 response envelope，不执行 content。limiter 使用一个全局 Semaphore、用户 active set 和可注入 monotonic clock；退出路径必须释放。

- [ ] **Step 5：实现 API 与稳定错误映射**

新增严格空 body model，确保客户端不能把临时 URL、Model 或 Key 塞进连接测试：

```python
from pydantic import BaseModel, ConfigDict

class LLMConnectionTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

@app.post("/api/settings/llm/test")
def test_llm_connection(
    payload: LLMConnectionTestRequest = LLMConnectionTestRequest(),
    user=Depends(current_user),
) -> dict[str, Any]:
    del payload
    return app.state.llm_connection_tests.test(int(user["id"]))
```

配置/凭据 409，URL 400，上游认证/拒绝/不可用/响应错误 502，上游 timeout 504，应用 test limiter 429。安全 logger 只写 user ID、endpoint.host、model、code，不写完整 URL path、Prompt、content 或 Key。

- [ ] **Step 6：运行设置与 API 测试确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_settings tests.test_web_llm tests.test_web_app -v
```

Expected: 设置事务、无网络保存、连接测试、限流和错误映射全部 PASS。

- [ ] **Step 7：建议用户提交 Task 9**

```powershell
git add src/specgate/web_settings.py src/specgate/web_llm.py src/specgate/web_app.py tests/test_web_settings.py tests/test_web_llm.py tests/test_web_app.py
git commit -m "feat: 增加真实模型设置与连接测试"
```

---

### Task 10：前端模型状态与连接测试交互

**Files:**

- Modify: `src/specgate/web_static/app.js:1-1700`
- Modify: `src/specgate/web_static/styles.css`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1：写静态契约失败测试**

`tests/test_web_static.py` 增加断言：

```python
def test_settings_contains_real_llm_controls_and_test_action(self):
    app_js = read_static("app.js")
    for snippet in (
        "llm_base_url",
        "llm_model",
        "llm_configuration_complete",
        "模型服务",
        "保存模型设置",
        "测试连接",
        "/api/settings/llm/test",
        "async function testLLMConnection",
    ):
        self.assertIn(snippet, app_js)

def test_api_key_is_cleared_and_never_rendered_from_settings(self):
    app_js = read_static("app.js")
    self.assertIn('apiKeyInput.value = ""', app_js)
    self.assertNotIn("settings.api_key_value", app_js)
    self.assertNotIn("credential_fingerprint", app_js)
```

- [ ] **Step 2：运行静态测试确认 RED**

Run: `python -m unittest tests.test_web_static -v`

Expected: FAIL，缺少模型设置与连接测试函数。

- [ ] **Step 3：实现状态标签和设置表单**

新增 `llmModeLabel(settings)`，中文展示 Mock、真实 Model、配置未完成、凭据重录和存储不可用。Settings 卡片分成“运行配置”和“模型服务”，Base URL/Model 输入使用已保存值，API Key 始终为空密码框。

保存普通设置时 body 同时包含 URL/Model；Key 继续使用独立接口。连接测试按钮在请求期间 disabled，结果只显示固定中文 message，不显示 content。

- [ ] **Step 4：在运行入口与详情展示冻结模式**

运行按钮附近显示 `将使用 MockLLM`、`将使用真实模型：<model>` 或配置阻断提示。`llm_configuration_complete=false` 时禁用运行并提供设置入口。run detail/audit 只显示 `llm_mode` 和 `llm_model`。

- [ ] **Step 5：运行前端静态与语法验证确认 GREEN**

Run:

```powershell
python -m unittest tests.test_web_static -v
node --check src/specgate/web_static/app.js
```

Expected: unittest PASS，Node exit code 0。

- [ ] **Step 6：建议用户提交 Task 10**

```powershell
git add src/specgate/web_static/app.js src/specgate/web_static/styles.css tests/test_web_static.py
git commit -m "feat: 展示 Web 模型模式与连接状态"
```

---

### Task 11：全链路安全回归与无真实网络保证

**Files:**

- Modify: `tests/test_llm_transport.py`
- Modify: `tests/test_web_llm.py`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1：增加 canary 泄漏组合测试**

使用不匹配常见 key 正则的 `REAL_LLM_CANARY_7c92`，让它同时出现在 Key、Provider 错误正文和底层异常 reason 中。收集：异常字符串/`repr`、HTTP JSON、run `error_message`、Trace、report、debug API 和捕获日志，逐项断言不含 canary。

- [ ] **Step 2：增加未注入网络即失败的测试守卫**

在真实模式测试中 patch `socket.create_connection` 和 `socket.getaddrinfo` 为抛错，只允许显式 Fake Resolver/Connection 通过。全量测试不得依赖公网 DNS、真实 TLS 或 API Key。

- [ ] **Step 3：增加模式不降级和重试不重复工具测试**

- 真实配置认证失败后，断言 Mock response 未消费、workspace 未写入、无 artifact。
- Provider 前两次 503、第三次合法 Action，断言只产生一次 write/approval。
- 第三次仍失败，断言 run failed 且没有发布。

- [ ] **Step 4：增加取消、超时和恢复组合测试**

- DNS 等待、response 分块读取和 backoff 三处取消。
- 总 deadline 到期优先 `timed_out`。
- 进程重启恢复 queued real run 时继续读取冻结快照。
- approval 等待不消耗运行窗口，resume 获取新 deadline。

- [ ] **Step 5：更新最终材料契约测试**

将 `tests/test_final_evidence.py` 的 schema v4 事实更新为 v5，并要求 `SPEC.md`、README、部署文档出现默认 Mock、真实模式 fail closed、`SPECGATE_LLM_ALLOWED_HOSTS` 和无网络测试边界；不得要求尚未获得的 PR/CI 编号。

- [ ] **Step 6：运行高风险组合测试**

Run:

```powershell
python -m unittest tests.test_llm_config tests.test_llm_transport tests.test_llm tests.test_web_credentials tests.test_web_llm tests.test_web_db tests.test_web_settings tests.test_web_runtime tests.test_web_runs tests.test_web_approvals tests.test_web_app tests.test_runner tests.test_gate -v
```

Expected: PASS；输出不得含 canary 或真实网络错误。

- [ ] **Step 7：建议用户提交 Task 11**

```powershell
git add tests/test_llm_transport.py tests/test_web_llm.py tests/test_web_runs.py tests/test_web_app.py tests/test_final_evidence.py
git commit -m "test: 覆盖真实 LLM 安全与恢复边界"
```

---

### Task 12：课程材料、部署说明与最终验证

**Files:**

- Modify: `SPEC.md`
- Modify: `PLAN.md`
- Modify: `SPEC_PROCESS.md`
- Modify: `AGENT_LOG.md`
- Modify: `README.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/PROJECT_WALKTHROUGH.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1：先写材料事实契约失败测试**

要求文档包含：

- Web 默认 Mock、配置完整后真实调用、失败不降级。
- Chat Completions 只是决策源，Harness 机制仍由代码实现。
- API Key 的 AES-256-GCM、录入/更新/清除和 fingerprint 语义。
- `SPECGATE_LLM_ALLOWED_HOSTS`、output tokens、request timeout。
- GitHub Pages 只静态展示，真实模式需要 Web 后端。
- 自动测试 Fake/Stub 且不访问网络。

同时断言旧句“WebUI 仍只运行 MockLLM”“保存凭据不会启用真实 LLM”不再存在于当前事实章节。

- [ ] **Step 2：运行材料测试确认 RED**

Run: `python -m unittest tests.test_final_evidence -v`

Expected: FAIL，现有材料仍描述 Web Mock-only 或 schema v4。

- [ ] **Step 3：同步课程主材料**

`SPEC.md` 更新问题、用户故事、功能规约、安全威胁模型、架构、数据模型、Provider 技术选型和客观验收；强调真实 LLM 不是 Harness 机制本身。`SPEC_PROCESS.md` 记录本轮 brainstorming 的关键选择：默认 Mock、fail closed、HITL、凭据冻结、SSRF、连接测试和测试策略。`PLAN.md`/`AGENT_LOG.md` 按实际 RED/GREEN 输出和用户 commit hash 更新，不预填虚构结果。

- [ ] **Step 4：同步 README 与部署说明**

提供：

```powershell
$env:SPECGATE_LLM_ALLOWED_HOSTS="api.example.com"
$env:SPECGATE_LLM_MAX_OUTPUT_TOKENS="4096"
$env:SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS="30"
```

说明这些变量不是 API Key。`SPECGATE_WEB_CREDENTIAL_KEY` 通过平台 Secret、Docker Secret 或权限受限且不提交 Git 的环境文件注入；不在命令历史写明文。Docker 示例区分默认 Mock-only 与真实 Provider 部署。

- [ ] **Step 5：同步 walkthrough 与证据矩阵**

增加 `SPEC/Checklist/index → LLM Action → Parser/Policy/HITL → Gate → SHA-256` 数据流。只记录本地已运行命令和已有远端证据；新 PR、merge commit、CI run URL 和截图留给用户在真实产生后补充，不写假值。`REFLECTION.md` 继续由学生本人维护，只更新事实核对指南。

- [ ] **Step 6：运行材料测试确认 GREEN**

Run: `python -m unittest tests.test_final_evidence tests.test_workflows -v`

Expected: PASS，且没有要求不存在的 PR/CI 编号。

- [ ] **Step 7：执行全量验证**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
git status --short --branch
```

Expected:

- unittest：`OK`，只允许仓库既有的显式 skip。
- compileall：无输出、exit code 0。
- Node：无输出、exit code 0。
- `git diff --check`：无输出。
- Git 状态只包含本计划范围文件，不包含 `.env`、数据库、凭据或临时产物。

- [ ] **Step 8：人工凭据泄漏复核**

Run:

```powershell
rg -n "sk-[A-Za-z0-9]|REAL_LLM_CANARY_7c92|SPECGATE_WEB_CREDENTIAL_KEY=.*[^<]" . --glob "!docs/superpowers/plans/2026-07-15-real-llm-web-integration.md"
```

Expected: 只命中明确的测试哨兵或变量名说明，不出现真实 Key、主密钥值、`.env` 或 Provider 响应正文。

- [ ] **Step 9：建议用户提交最终任务**

```powershell
git add SPEC.md PLAN.md SPEC_PROCESS.md AGENT_LOG.md README.md docs/DEPLOYMENT.md `
  docs/PROJECT_WALKTHROUGH.md docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md `
  docs/superpowers/specs/2026-07-15-real-llm-web-integration-design.md `
  docs/superpowers/plans/2026-07-15-real-llm-web-integration.md `
  tests/test_final_evidence.py
git commit -m "docs: 同步真实 LLM 接入材料与验证证据"
```

---

## 实施期间的强制检查点

每个 Task 都必须遵循：

1. 先写一个能因当前缺失行为而失败的测试。
2. 运行并保存 RED 的具体失败原因。
3. 只写让当前测试通过的最小实现。
4. 运行目标测试确认 GREEN。
5. 运行受影响模块回归。
6. 先做 spec 合规审查，再做代码质量审查。
7. 在 `PLAN.md` 与 `AGENT_LOG.md` 记录实际命令、结果和用户 commit hash。

禁止事项：

- 不使用真实 Provider 作为自动测试前提。
- 不在测试、日志或文档中写真实 Key。
- 不让真实模式失败后构造 MockLLM。
- 不为了“兼容”宽松提取 Markdown 中的 JSON。
- 不绕过 `WebRuntimeCoordinator` 创建后台任务。
- 不修改 Action、WorkspacePolicy、HITL、Gate 或发布绑定来迁就模型输出。
- 不提前填写 PR、CI、部署截图或测试数字。
