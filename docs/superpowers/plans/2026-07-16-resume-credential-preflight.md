# 审批恢复前凭据预检实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在审批恢复应用任何获批动作之前验证冻结真实模型凭据，使恢复前清除 API Key 的运行以 `credential_missing` 失败关闭。

**Architecture:** `WebLLMFactory` 提供不访问 Provider 的本地凭据预检，并与 `CredentialBoundLLM.complete()` 共用相同的凭据错误映射。`_run_resume_agent()` 在构造 Runner 和认领审批前调用预检；失败由 `resume_run_once()` 的现有异常路径终结运行，不修改目标文件、审批队列或产物。

**Tech Stack:** Python 3.11、SQLite、AES-GCM 凭据服务、FastAPI Web runtime、`unittest`

**Git 约束:** 暂存、提交、推送和 PR 均由用户执行，本计划不运行 Git 写操作。

---

### Task 1：用测试锁定凭据预检契约

**Files:**

- Modify: `tests/test_web_llm.py`

- [ ] **Step 1：添加有效凭据的无网络预检测试**

在 `WebLLMFactoryTests` 中保存允许的 Base URL、Model 和测试凭据，冻结真实配置后调用：

```python
self.factory.preflight_resume(config, self.user_id)
```

断言 `self.transport.calls == []`，证明预检只读取本地加密凭据，不访问 Provider。

- [ ] **Step 2：添加清除凭据后的失败测试**

冻结真实配置后清除凭据，再调用：

```python
with self.assertRaises(WebLLMError) as missing:
    self.factory.preflight_resume(config, self.user_id)
```

断言：

```python
self.assertEqual(missing.exception.code, "credential_missing")
self.assertEqual(self.transport.calls, [])
self.assertNotIn("SENTINEL-secret", str(missing.exception))
```

- [ ] **Step 3：运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_llm.WebLLMFactoryTests.test_resume_preflight_accepts_matching_credential_without_transport tests.test_web_llm.WebLLMFactoryTests.test_resume_preflight_rejects_cleared_credential_without_transport -v
```

Expected: 两个测试因 `WebLLMFactory` 尚无 `preflight_resume` 方法而失败；不得出现测试夹具或数据库初始化错误。

---

### Task 2：实现工厂级本地凭据预检

**Files:**

- Modify: `src/specgate/web_llm.py`
- Test: `tests/test_web_llm.py`

- [ ] **Step 1：提取稳定的凭据读取与错误映射**

新增私有函数，供正常 LLM 调用和恢复预检共用：

```python
def _get_matching_api_key(
    credentials: WebCredentialService,
    user_id: int,
    fingerprint: str,
) -> str:
    try:
        return credentials.get_matching(user_id, fingerprint)
    except WebCredentialError as exc:
        code = exc.code
        if code in {
            "credential_store_unavailable",
            "invalid_credential_key",
            "credential_decryption_failed",
        }:
            code = "credential_unavailable"
        raise WebLLMError(code) from exc
```

将 `CredentialBoundLLM.complete()` 现有的 `get_matching()`/异常映射替换为该函数，保持行为不变。

- [ ] **Step 2：实现恢复预检方法**

在 `WebLLMFactory` 中增加：

```python
def preflight_resume(self, config: LLMRunConfig, user_id: int) -> None:
    if config.mode == "mock":
        return
    if self.credentials is None:
        raise WebLLMError("llm_configuration_required")
    fingerprint = config.credential_fingerprint
    if fingerprint is None:
        raise WebLLMError("invalid_llm_config")
    api_key = _get_matching_api_key(self.credentials, user_id, fingerprint)
    del api_key
```

方法不得构造 transport、发起网络请求、返回 Key 或记录 fingerprint。

- [ ] **Step 3：运行工厂测试并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_llm -v
```

Expected: 全部通过，现有按调用重新检查 fingerprint 的测试保持绿色。

---

### Task 3：用端到端单元测试复现恢复顺序缺陷

**Files:**

- Modify: `tests/test_web_runs.py`

- [ ] **Step 1：添加真实快照恢复前清除凭据测试**

基于 `test_real_llm_approval_resume_uses_frozen_endpoint` 创建带初始 `index.html` 的项目和真实 LLM factory。脚本 transport 的首次响应请求 `replace_file(index.html)`，使运行进入 `needs_approval`。

通过 `approve_web_approval()` 正常批准数据库和队列中的审批，记录批准后的 queue revision 与原始 workspace `index.html` 字节，然后调用：

```python
credentials.clear(user["id"])
updated = resume_run_once(
    db_path,
    data_root,
    user["id"],
    run["id"],
    llm_factory=factory,
    remaining_seconds=lambda: 30.0,
)
```

测试断言：

```python
self.assertEqual(updated["status"], "failed")
self.assertEqual(updated["error_message"], "credential_missing")
self.assertEqual((paths.workspace / "index.html").read_bytes(), original_index)
self.assertEqual(queue_after.revision, approved_revision)
self.assertEqual(queue_after.approvals[0].status, "approved")
self.assertEqual(len(transport.contexts), 1)
self.assertIsNone(updated["index_artifact_path"])
self.assertIsNone(updated["zip_artifact_path"])
```

同时断言 Trace 不含 `approval_claimed`、`approval_applied`、测试 Key 或冻结 fingerprint，artifact 表中 run 对应行数为 0，SQLite 审批状态仍为 `approved`。

- [ ] **Step 2：运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs.WebRunsTests.test_resume_preflight_fails_before_approved_action_when_credential_was_cleared -v
```

Expected: 当前实现会先应用 `replace_file`，因此原文件或审批状态断言失败；测试必须同时观察到 `credential_missing`，证明失败原因正确。

---

### Task 4：在 Runner 恢复前接入预检

**Files:**

- Modify: `src/specgate/web_runs.py`
- Test: `tests/test_web_runs.py`

- [ ] **Step 1：在 `_run_resume_agent()` 调用预检**

复用同一个配置对象并在构造 Runner 之前执行：

```python
factory = llm_factory or WebLLMFactory.mock_only(mock_factory=MockLLM)
resolved_llm_config = llm_config or LLMRunConfig.mock()
factory.preflight_resume(resolved_llm_config, user_id)
llm = factory.build(
    resolved_llm_config,
    user_id,
    mock_responses=responses,
    stop_check=stop_check or (lambda: None),
    remaining_seconds=remaining_seconds or (lambda: 60.0),
)
```

调用位置必须在 `AgentRunner(...)` 和 `runner.resume_from_approval()` 之前。初始运行 `_run_mock_agent()` 不增加预检。

- [ ] **Step 2：运行恢复缺失凭据测试并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs.WebRunsTests.test_resume_preflight_fails_before_approved_action_when_credential_was_cleared -v
```

Expected: PASS；运行 `failed / credential_missing`，原文件和 approved queue 未变化，无产物和恢复动作 Trace。

- [ ] **Step 3：运行正常真实 HITL 回归**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs.WebRunsTests.test_real_llm_approval_resume_uses_frozen_endpoint tests.test_web_runs.WebRunsTests.test_resume_gate_failure_does_not_publish_artifacts -v
```

Expected: 两个测试通过；有效凭据仍使用冻结 endpoint 完成恢复，Gate 失败场景仍不发布产物。

---

### Task 5：完整相关回归与静态检查

**Files:**

- Test: `tests/test_web_llm.py`
- Test: `tests/test_web_runs.py`
- Test: `tests/test_web_approvals.py`
- Test: `tests/test_web_app.py`
- Test: `tests/test_web_debug.py`
- Test: `tests/test_web_static.py`

- [ ] **Step 1：运行完整相关测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_llm tests.test_web_runs tests.test_web_approvals tests.test_web_app tests.test_web_debug tests.test_web_static -v
```

Expected: 全部通过；Windows 符号链接权限相关 skip 可接受。

- [ ] **Step 2：运行编译和差异检查**

Run:

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
git status --short --branch
```

Expected: Python 编译和 JavaScript 语法检查退出码为 0；diff 无空白错误；Git 状态只包含用户已有改动、本轮补丁和审计文档。
