# NJU SE Hub 真实 LLM 兼容性验证 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不泄露 API Key、不修改正式示例和不部署公网服务的前提下，验证 NJU SE Hub 的四个模型能否通过 SpecGate WebUI 与 CLI 完成真实、可审计的本地 HTML 任务。

**Architecture:** 先在独立 Web 数据目录中执行连接测试和四个相互隔离的完整 run，再用 `qwen3.7-max` 对系统临时目录执行一次 CLI 直接文件修改。验证结果只进入脱敏审计文档；如果发现协议差异，立即停止矩阵并转入系统化调试和单独的 TDD 修复流程。

**Tech Stack:** Python 3、FastAPI WebUI、SQLite、AES-256-GCM Web 凭据、OpenAI-compatible Chat Completions、`unittest`、PowerShell、静态 HTML Gate

---

## 执行结果（2026-07-17）

本节是事后执行记录。下方任务清单保留原始计划状态，不把未执行的步骤追记为已完成。

- 实际分支与 worktree 为 `njusehub-real-llm-audit` 和 `.worktrees\njusehub-real-llm-audit`；规划提交为 `cef343d`。
- 审计契约先因目标文档不存在得到 `FileNotFoundError` 红灯；写入真实审计后，单项测试得到 `Ran 1 test in 0.001s`、`OK`。
- 四个 WebUI run 均为 `completed` / `trusted`，各用 2 个 step、2 次逻辑 LLM 调用和 2 次工具调用完成；所有 run 的 `parse_errors=0`、`blocked_actions=0`、`gate_failures=0`、`finish_actions=1`、`approval_requests=0`、`artifact_count=2`。
- `qwen3.7-max` CLI 运行得到 `passed=True, steps=2`、退出码 0，`index.html`、Trace 和 HTML 报告均存在。
- 原计划要求每个模型先执行连接测试。实际首次 `qwen3.7-max` 连接按钮因硬编码 10 秒 deadline 假超时；60 秒脱敏诊断在 13.368 秒成功。其余三个模型未继续点击不可靠的旧按钮，而是用完整真实 run 证明接口、Action 与完整兼容。
- 连接测试问题经根因分析和 TDD 修复，功能 commit 为 `a5861aa`，PR #22 合并 commit 为 `3905e1e`；相关回归为 65 个测试，完整回归为 920 个测试。修复后使用 60 秒配置复测 `qwen3.7-max`，连接按钮通过。
- 当前审计分支重新验证：审计契约 1 个测试通过，最终证据 20 个测试通过，相关回归 112 个测试通过（跳过 1 个），完整套件 921 个测试通过（跳过 27 个）；`python -m compileall -q src tests` 与 `node --check src/specgate/web_static/app.js` 均退出码 0。
- API Key 已从 WebUI 和 CLI 会话清除，Web 服务已停止，敏感环境变量已删除；未部署公网服务。

四模型实际指标：

| 模型 | Run | 状态 | Trust | Steps | LLM calls | Tool calls | Parse errors | Blocked | Gate failures | Finish | Approvals | Artifacts |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `qwen3.7-max` | #1 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 |
| `kimi-k2.7-code` | #2 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 |
| `glm-5.2` | #3 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 |
| `deepseek-v4-pro` | #4 | `completed` | `trusted` | 2 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 2 |

## 执行约束

- 所有 Git 命令均由用户执行，Agent 不得运行任何 Git 命令，包括只读命令。
- API Key 只能由用户在本地 Web 设置页或隐藏 PowerShell 输入中提供。
- Agent 不得请求用户把 API Key 粘贴到聊天中。
- 不修改 `src/specgate/`。若真实失败证明必须修改生产代码，暂停本计划并进入 `superpowers:systematic-debugging`。
- 不修改 `examples/knowledge_nav`。
- 不执行公网部署。
- Web 测试数据只写入 `.specgate-web/njusehub-smoke`。
- CLI 测试数据只写入 `%TEMP%\specgate-njusehub-cli-qwen`。

## 文件边界

本计划预计只产生以下仓库变更：

- 已创建：`docs/superpowers/specs/2026-07-17-njusehub-real-llm-compatibility-design.md`
- 已创建：`docs/superpowers/plans/2026-07-17-njusehub-real-llm-compatibility.md`
- 创建：`docs/superpowers/audits/2026-07-17-njusehub-real-llm-compatibility.md`
- 修改：`tests/test_final_evidence.py`

以下内容是运行数据，不得提交：

- `.specgate-web/njusehub-smoke/`
- `%TEMP%\specgate-njusehub-cli-qwen\`
- API Key
- `SPECGATE_WEB_CREDENTIAL_KEY`
- 未经脱敏的终端输出或浏览器数据

### Task 1: 提交设计与计划并建立隔离 worktree

**Files:**
- Create: `docs/superpowers/specs/2026-07-17-njusehub-real-llm-compatibility-design.md`
- Create: `docs/superpowers/plans/2026-07-17-njusehub-real-llm-compatibility.md`

- [ ] **Step 1: 用户检查规划文件差异**

由用户在 `D:\code\NJU\SpecGate` 执行：

```powershell
git status --short --branch
git diff --check
```

Expected：状态中只看到本阶段两份未跟踪规划文档，`git diff --check` 无输出。未跟踪文件不会出现在普通 `git diff` 中，因此提交前必须使用缓存差异复核。

- [ ] **Step 2: 用户创建无 `codex/` 前缀的阶段分支**

```powershell
git switch -c njusehub-real-llm-audit
```

Expected：切换到 `njusehub-real-llm-audit`。

- [ ] **Step 3: 用户提交规划文件**

```powershell
git add -- `
  docs/superpowers/specs/2026-07-17-njusehub-real-llm-compatibility-design.md `
  docs/superpowers/plans/2026-07-17-njusehub-real-llm-compatibility.md

git diff --cached --check
git diff --cached --stat
git commit -m "docs: plan NJU SE Hub compatibility validation"
```

Expected：缓存检查无输出，统计只包含两份规划文档，提交成功。

- [ ] **Step 4: 用户把实现分支移入独立 worktree**

```powershell
git switch main
git worktree add `
  .worktrees\njusehub-real-llm-audit `
  njusehub-real-llm-audit

cd D:\code\NJU\SpecGate\.worktrees\njusehub-real-llm-audit
git status --short --branch
```

Expected：worktree 位于指定目录，分支为 `njusehub-real-llm-audit`，工作区干净。

### Task 2: 建立审计文档契约红灯

**Files:**
- Modify: `tests/test_final_evidence.py`
- Test: `tests/test_final_evidence.py`

- [ ] **Step 1: 在证据路径常量区增加 NJU 审计路径**

在 `COLD_START_AUDIT` 常量之后加入：

```python
NJU_REAL_LLM_AUDIT = (
    ROOT
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-07-17-njusehub-real-llm-compatibility.md"
)
```

- [ ] **Step 2: 在 `FinalEvidenceTests` 末尾增加完整性与脱敏测试**

在 `test_reflection_remains_student_owned` 之前加入：

```python
    def test_njusehub_real_llm_audit_is_complete_and_redacted(self):
        audit = NJU_REAL_LLM_AUDIT.read_text(encoding="utf-8")

        required_phrases = (
            "https://njusehub.info/v1",
            "qwen3.7-max",
            "kimi-k2.7-code",
            "glm-5.2",
            "deepseek-v4-pro",
            "接口兼容",
            "Action 兼容",
            "完整兼容",
            "WebUI",
            "CLI",
            "llm_mode",
            "llm_calls",
            "tool_calls",
            "parse_errors",
            "blocked_actions",
            "gate_failures",
            "finish_actions",
            "approval_requests",
            "artifact_count",
            "人工操作",
            "未部署公网服务",
        )
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, audit)

        for forbidden in (
            "TBD",
            "TODO",
            "待补充",
            "Authorization: Bearer",
            "OPENAI_COMPATIBLE_API_KEY=",
            "SPECGATE_WEB_CREDENTIAL_KEY=",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, audit)

        self.assertIsNone(re.search(r"\bsk-[A-Za-z0-9_-]{8,}", audit))
```

- [ ] **Step 3: 运行单项测试确认红灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_njusehub_real_llm_audit_is_complete_and_redacted
```

Expected：ERROR，原因是 `2026-07-17-njusehub-real-llm-compatibility.md` 尚不存在。不得通过创建空文档消除红灯。

### Task 3: 验证现有真实 LLM 单元测试并启动隔离 WebUI

**Files:**
- Read: `src/specgate/llm.py`
- Read: `src/specgate/llm_transport.py`
- Read: `src/specgate/web_llm.py`
- Runtime only: `.specgate-web/njusehub-smoke/`

- [ ] **Step 1: 运行无网络基线测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_llm `
  tests.test_llm_transport `
  tests.test_web_llm `
  tests.test_web_app
```

Expected：全部通过。若失败，停止真实 API 调用，先按 `superpowers:systematic-debugging` 处理本地基线。

- [ ] **Step 2: 检查 8000 端口没有被其他程序占用**

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
```

Expected：无输出。若有输出，先识别现有进程，不直接终止未知进程。

- [ ] **Step 3: 在当前 PowerShell 会话生成独立 Web 主密钥**

```powershell
$bytes = New-Object byte[] 32
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
  $rng.GetBytes($bytes)
} finally {
  $rng.Dispose()
}
$env:SPECGATE_WEB_CREDENTIAL_KEY = `
  [Convert]::ToBase64String($bytes).Replace("+", "-").Replace("/", "_")
Remove-Variable bytes, rng
```

Expected：命令不打印主密钥。不要运行会回显该环境变量的命令。

- [ ] **Step 4: 设置隔离目录、主机白名单和请求上限**

```powershell
$env:PYTHONPATH="src"
$env:SPECGATE_WEB_DATA="D:\code\NJU\SpecGate\.specgate-web\njusehub-smoke"
$env:SPECGATE_LLM_ALLOWED_HOSTS="njusehub.info"
$env:SPECGATE_LLM_MAX_OUTPUT_TOKENS="4096"
$env:SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS="60"
$env:SPECGATE_WEB_RUN_TIMEOUT_SECONDS="240"
```

Expected：测试数据位于主仓库根目录下已忽略的 `.specgate-web` 隔离目录；单次模型请求最多 60 秒，完整 run 最多 240 秒。

- [ ] **Step 5: 启动本地 WebUI**

```powershell
python -m specgate.web --host 127.0.0.1 --port 8000
```

Expected：进程保持运行，浏览器可以打开 `http://127.0.0.1:8000`。保留该 PowerShell 窗口，不要关闭或清除主密钥。

### Task 4: 执行 `qwen3.7-max` Web 基线

**Files:**
- Runtime only: `.specgate-web/njusehub-smoke/`
- Evidence source: WebUI Debug/Audit 原始 JSON

- [ ] **Step 1: 用户创建隔离 Web 账号**

打开 `http://127.0.0.1:8000`，创建只用于本轮测试的本地账号。密码由用户自行保存，不发送到聊天，不进入截图。

Expected：成功登录全新的空项目列表。

- [ ] **Step 2: 用户保存 qwen 配置和 API Key**

在设置页填写：

```text
Base URL: https://njusehub.info/v1
Model: qwen3.7-max
API Key: 由用户在本地输入
```

Expected：保存后 API Key 输入框清空，状态显示凭据已加密配置。

- [ ] **Step 3: 用户执行一次连接测试**

点击“测试连接”一次。

Expected：显示连接成功。若出现认证、拒绝、网络、DNS、TLS 或超时错误，停止本任务后续步骤，保存不含 Key 的错误代码并进入 Task 9 的失败记录路径。

- [ ] **Step 4: 用户创建 qwen 最小项目**

项目名：

```text
NJU API Smoke - qwen3.7-max
```

SPEC 输入：

```markdown
# NJU SE Hub qwen3.7-max 兼容性验证

创建单文件、离线的中文 `index.html`。

页面必须满足：

- `<title>` 和 `<h1>` 均为 `NJU School API Smoke Test`。
- 页面正文包含 `qwen3.7-max compatibility verified`。
- 包含 UTF-8 charset、移动端 viewport 和 `type="search"` 搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成文件并通过 Gate 后请求 `finish`。
```

Checklist 输入：

```markdown
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 qwen3.7-max compatibility verified
```

初始 `index.html` 留空。

- [ ] **Step 5: 固定运行设置并发起 qwen run**

设置：

```text
governance_profile: review
context_strategy: injection-safe
max_steps: 4
```

任务提示：

```text
请严格按照 TASK_SPEC 和 CHECKLIST 创建 index.html，完成后请求 finish。
```

Expected：正常基线为两步完成；允许在四步内完成一次修复。

- [ ] **Step 6: 用户把脱敏结果交给 Agent 核对**

在 Debug/Audit 页面复制原始 JSON，确认其中没有 API Key 后发送到当前 Codex 任务。至少核对：

```text
status=completed
trust_level=trusted
llm_mode=openai-compatible
llm_model=qwen3.7-max
parse_errors=0
blocked_actions=0
gate_failures=0
finish_actions=1
approval_requests=0
artifact_count=2
```

Expected：全部满足。若不满足，记录实际值，不把失败写成通过，并停止后续模型付费 run。

### Task 5: 执行 `kimi-k2.7-code` Web 验证

**Files:**
- Runtime only: `.specgate-web/njusehub-smoke/`
- Evidence source: WebUI Debug/Audit 原始 JSON

- [ ] **Step 1: 用户把设置页 Model 改为 `kimi-k2.7-code`**

Base URL 和 API Key 保持不变，只修改：

```text
Model: kimi-k2.7-code
```

Expected：设置状态显示真实模型 `kimi-k2.7-code`。

- [ ] **Step 2: 用户执行一次连接测试**

Expected：连接成功。失败时记录错误并停止该模型的完整 run。

- [ ] **Step 3: 用户创建独立 kimi 项目**

项目名：

```text
NJU API Smoke - kimi-k2.7-code
```

SPEC 输入：

```markdown
# NJU SE Hub kimi-k2.7-code 兼容性验证

创建单文件、离线的中文 `index.html`。

页面必须满足：

- `<title>` 和 `<h1>` 均为 `NJU School API Smoke Test`。
- 页面正文包含 `kimi-k2.7-code compatibility verified`。
- 包含 UTF-8 charset、移动端 viewport 和 `type="search"` 搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成文件并通过 Gate 后请求 `finish`。
```

Checklist 输入：

```markdown
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 kimi-k2.7-code compatibility verified
```

初始 `index.html` 留空。

- [ ] **Step 4: 使用固定设置发起 kimi run**

设置保持 `review`、`injection-safe`、`max_steps=4`，任务提示固定为：

```text
请严格按照 TASK_SPEC 和 CHECKLIST 创建 index.html，完成后请求 finish。
```

- [ ] **Step 5: 核对并保存脱敏结果**

核对 `llm_model=kimi-k2.7-code` 以及 Task 4 Step 6 中同一组指标。发送前确认原始 JSON 不含 API Key。

### Task 6: 执行 `glm-5.2` Web 验证

**Files:**
- Runtime only: `.specgate-web/njusehub-smoke/`
- Evidence source: WebUI Debug/Audit 原始 JSON

- [ ] **Step 1: 用户把设置页 Model 改为 `glm-5.2` 并测试连接一次**

```text
Model: glm-5.2
```

Expected：连接成功；失败时记录错误并停止该模型的完整 run。

- [ ] **Step 2: 用户创建独立 GLM 项目**

项目名：

```text
NJU API Smoke - glm-5.2
```

SPEC 输入：

```markdown
# NJU SE Hub glm-5.2 兼容性验证

创建单文件、离线的中文 `index.html`。

页面必须满足：

- `<title>` 和 `<h1>` 均为 `NJU School API Smoke Test`。
- 页面正文包含 `glm-5.2 compatibility verified`。
- 包含 UTF-8 charset、移动端 viewport 和 `type="search"` 搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成文件并通过 Gate 后请求 `finish`。
```

Checklist 输入：

```markdown
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 glm-5.2 compatibility verified
```

初始 `index.html` 留空。

- [ ] **Step 3: 使用固定设置发起 GLM run**

设置保持 `review`、`injection-safe`、`max_steps=4`，提示仍为：

```text
请严格按照 TASK_SPEC 和 CHECKLIST 创建 index.html，完成后请求 finish。
```

- [ ] **Step 4: 核对并保存脱敏结果**

核对 `llm_model=glm-5.2` 以及 Task 4 Step 6 中同一组指标。发送前确认原始 JSON 不含 API Key。

### Task 7: 执行 `deepseek-v4-pro` Web 验证

**Files:**
- Runtime only: `.specgate-web/njusehub-smoke/`
- Evidence source: WebUI Debug/Audit 原始 JSON

- [ ] **Step 1: 用户把设置页 Model 改为 `deepseek-v4-pro` 并测试连接一次**

```text
Model: deepseek-v4-pro
```

Expected：连接成功；失败时记录错误并停止该模型的完整 run。

- [ ] **Step 2: 用户创建独立 DeepSeek 项目**

项目名：

```text
NJU API Smoke - deepseek-v4-pro
```

SPEC 输入：

```markdown
# NJU SE Hub deepseek-v4-pro 兼容性验证

创建单文件、离线的中文 `index.html`。

页面必须满足：

- `<title>` 和 `<h1>` 均为 `NJU School API Smoke Test`。
- 页面正文包含 `deepseek-v4-pro compatibility verified`。
- 包含 UTF-8 charset、移动端 viewport 和 `type="search"` 搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成文件并通过 Gate 后请求 `finish`。
```

Checklist 输入：

```markdown
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 deepseek-v4-pro compatibility verified
```

初始 `index.html` 留空。

- [ ] **Step 3: 使用固定设置发起 DeepSeek run**

设置保持 `review`、`injection-safe`、`max_steps=4`，提示仍为：

```text
请严格按照 TASK_SPEC 和 CHECKLIST 创建 index.html，完成后请求 finish。
```

- [ ] **Step 4: 核对并保存脱敏结果**

核对 `llm_model=deepseek-v4-pro` 以及 Task 4 Step 6 中同一组指标。发送前确认原始 JSON 不含 API Key。

### Task 8: 执行 `qwen3.7-max` CLI 直接文件验证

**Files:**
- Runtime only: `%TEMP%\specgate-njusehub-cli-qwen\TASK_SPEC.md`
- Runtime only: `%TEMP%\specgate-njusehub-cli-qwen\CHECKLIST.md`
- Runtime output: `%TEMP%\specgate-njusehub-cli-qwen\index.html`

- [ ] **Step 1: 用户在新的 PowerShell 窗口创建 CLI 临时工作区**

```powershell
cd D:\code\NJU\SpecGate\.worktrees\njusehub-real-llm-audit
$env:PYTHONPATH="src"
$cliRoot = Join-Path $env:TEMP "specgate-njusehub-cli-qwen"
New-Item -ItemType Directory -Force -Path $cliRoot | Out-Null
```

Expected：`$cliRoot` 指向系统临时目录，不在 Git 仓库中。

- [ ] **Step 2: 写入固定 SPEC**

```powershell
@'
# NJU SE Hub qwen3.7-max CLI 兼容性验证

创建单文件、离线的中文 `index.html`。

页面必须满足：

- `<title>` 和 `<h1>` 均为 `NJU School API Smoke Test`。
- 页面正文包含 `qwen3.7-max compatibility verified`。
- 包含 UTF-8 charset、移动端 viewport 和 `type="search"` 搜索框。
- 不使用任何外部脚本、样式、字体或图片。
- 完成文件并通过 Gate 后请求 `finish`。
'@ | Set-Content -Encoding utf8 (Join-Path $cliRoot "TASK_SPEC.md")
```

- [ ] **Step 3: 写入固定 Checklist**

```powershell
@'
# 验收清单

- 必须包含 NJU School API Smoke Test
- 必须包含 qwen3.7-max compatibility verified
'@ | Set-Content -Encoding utf8 (Join-Path $cliRoot "CHECKLIST.md")
```

- [ ] **Step 4: 确认不存在旧 `index.html` 和旧运行目录**

```powershell
Test-Path (Join-Path $cliRoot "index.html")
Test-Path (Join-Path $cliRoot "runs")
Test-Path (Join-Path $cliRoot "reports")
```

Expected：三行均为 `False`。若不是，停止并改用新的空临时目录，不删除来源不明的数据。

- [ ] **Step 5: 用户通过隐藏输入设置当前会话 API Key**

```powershell
$secureKey = Read-Host "NJU SE Hub API Key" -AsSecureString
$keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
  $env:OPENAI_COMPATIBLE_API_KEY = `
    [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)
} finally {
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
}
Remove-Variable secureKey, keyPointer
```

Expected：输入内容不回显，Key 不进入命令历史。不要打印该环境变量。

- [ ] **Step 6: 运行 qwen CLI**

```powershell
python -m specgate.cli run $cliRoot `
  --provider openai-compatible `
  --model qwen3.7-max `
  --base-url https://njusehub.info/v1 `
  --max-steps 4 `
  --timeout 60 `
  --governance-profile review

$cliExitCode = $LASTEXITCODE
"CLI exit code: $cliExitCode"
```

Expected：`CLI exit code: 0`。失败时保留脱敏错误代码，不立即重试。

- [ ] **Step 7: 验证本地文件和报告存在**

```powershell
Test-Path (Join-Path $cliRoot "index.html")
Test-Path (Join-Path $cliRoot "runs\latest\trace.jsonl")
Test-Path (Join-Path $cliRoot "reports\latest\index.html")
```

Expected：三行均为 `True`。

- [ ] **Step 8: 在不打印 Key 的情况下扫描明文泄漏**

```powershell
@'
import os
import pathlib
import sys

secret = os.environ["OPENAI_COMPATIBLE_API_KEY"].encode("utf-8")
roots = [
    pathlib.Path(os.environ["SPECGATE_CLI_SMOKE_ROOT"]),
    pathlib.Path(os.environ["SPECGATE_WEB_SMOKE_ROOT"]),
]
hits = []
for root in roots:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if secret in path.read_bytes():
                hits.append(str(path.relative_to(root)))
        except OSError:
            hits.append("<unreadable-file>")
print(f"plaintext secret leak files: {len(hits)}")
sys.exit(1 if hits else 0)
'@ | Set-Content -Encoding utf8 (Join-Path $env:TEMP "specgate_secret_scan.py")

$env:SPECGATE_CLI_SMOKE_ROOT = $cliRoot
$env:SPECGATE_WEB_SMOKE_ROOT = `
  "D:\code\NJU\SpecGate\.specgate-web\njusehub-smoke"
python (Join-Path $env:TEMP "specgate_secret_scan.py")
```

Expected：`plaintext secret leak files: 0`，退出码为 0。脚本只打印数量，不打印 Key 或命中文件内容。

- [ ] **Step 9: 立即清除 CLI Key 和扫描辅助变量**

```powershell
Remove-Item Env:OPENAI_COMPATIBLE_API_KEY
Remove-Item Env:SPECGATE_CLI_SMOKE_ROOT
Remove-Item Env:SPECGATE_WEB_SMOKE_ROOT
Remove-Item (Join-Path $env:TEMP "specgate_secret_scan.py")
```

Expected：当前 PowerShell 会话不再持有 API Key。

### Task 9: 写入真实审计结果并让契约测试转绿

**Files:**
- Create: `docs/superpowers/audits/2026-07-17-njusehub-real-llm-compatibility.md`
- Modify: `tests/test_final_evidence.py`
- Test: `tests/test_final_evidence.py`

- [ ] **Step 1: 汇总每个模型的真实证据**

只使用已经核对的 Web 原始 JSON 和 CLI 输出。每个模型必须有以下字段：

```text
连接测试结果
Run ID
status
trust_level
llm_mode
llm_model
steps
llm_calls
tool_calls
parse_errors
blocked_actions
gate_failures
finish_actions
approval_requests
artifact_count
接口兼容结论
Action 兼容结论
完整兼容结论
```

若某模型在连接阶段失败，后续字段明确写“未执行”，并记录结构化错误代码和没有继续付费 run 的人工决定。不得推测缺失数字。

- [ ] **Step 2: 创建审计文档并写入实际结果**

文档必须包含且只包含以下事实章节：

```markdown
# NJU SE Hub 真实 LLM 兼容性验证审计

## 1. 范围与安全边界
## 2. 接口契约
## 3. WebUI 四模型兼容性矩阵
## 4. qwen3.7-max Web 运行证据
## 5. kimi-k2.7-code Web 运行证据
## 6. glm-5.2 Web 运行证据
## 7. deepseek-v4-pro Web 运行证据
## 8. qwen3.7-max CLI 直接文件证据
## 9. 失败、重试与人工操作
## 10. 结论
```

第 3 节使用以下列名，并为四个模型各写一行实际结果：

```markdown
| 模型 | 连接测试 | 接口兼容 | Action 兼容 | 完整兼容 | Run ID | 状态 | Trust |
| --- | --- | --- | --- | --- | ---: | --- | --- |
```

第 9 节必须明确记录：API Key 由用户本地输入、没有发送给 Agent、没有部署公网服务、是否发生重试，以及所有 Git 操作由用户执行。

审计还必须明确说明：`llm_calls` 是逻辑模型调用数，当前公开 Trace 不提供精确 HTTP 传输尝试次数，因此不能把 `llm_calls` 写成实际 HTTP 请求数；无法直接观测的传输重试次数如实写为“不可从当前公开证据确定”。

- [ ] **Step 3: 运行审计契约测试确认绿灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_njusehub_real_llm_audit_is_complete_and_redacted
```

Expected：PASS。

- [ ] **Step 4: 用户提交审计契约与真实证据**

```powershell
git add -- `
  tests/test_final_evidence.py `
  docs/superpowers/audits/2026-07-17-njusehub-real-llm-compatibility.md

git diff --cached --check
git diff --cached --stat
git commit -m "test: audit NJU SE Hub model compatibility"
```

Expected：只提交契约测试和脱敏审计文档；缓存差异检查无输出。

### Task 10: 完整验证与分支收尾

**Files:**
- Verify: `tests/test_final_evidence.py`
- Verify: `src/specgate/`
- Verify: `src/specgate/web_static/app.js`

- [ ] **Step 1: 停止 WebUI 并清除 Web 敏感环境变量**

在运行 WebUI 的原 PowerShell 窗口按 `Ctrl+C`，确认服务停止后执行：

```powershell
Remove-Item Env:SPECGATE_WEB_CREDENTIAL_KEY
Remove-Item Env:SPECGATE_WEB_DATA
Remove-Item Env:SPECGATE_LLM_ALLOWED_HOSTS
Remove-Item Env:SPECGATE_LLM_MAX_OUTPUT_TOKENS
Remove-Item Env:SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS
Remove-Item Env:SPECGATE_WEB_RUN_TIMEOUT_SECONDS
```

Expected：WebUI 停止，当前 PowerShell 不再持有主密钥或 NJU 运行配置。保留隔离数据目录供审计复核，不在此时删除。

- [ ] **Step 2: 运行相关测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_llm `
  tests.test_llm_transport `
  tests.test_web_llm `
  tests.test_web_app `
  tests.test_final_evidence
```

Expected：全部通过。

- [ ] **Step 3: 运行完整测试套件**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -p "test*.py"
```

Expected：退出码 0。记录实际测试数量、耗时和 skipped 数量，不沿用历史数字。

- [ ] **Step 4: 运行静态检查**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
```

Expected：两条命令均退出码 0 且无错误输出。

- [ ] **Step 5: 用户检查最终 Git 状态与差异**

```powershell
git status --short --branch
git diff --check
git log -3 --oneline
```

Expected：工作区干净；阶段分支只包含规划提交和审计提交。`.specgate-web` 与系统临时目录不出现在状态中。

- [ ] **Step 6: 用户推送无 `codex/` 前缀的分支**

```powershell
git push -u origin njusehub-real-llm-audit
```

Expected：远端创建同名分支。

- [ ] **Step 7: 创建 PR 前执行人工安全复核**

用户确认以下内容后再创建 PR：

```text
审计文档没有 API Key 或主密钥
截图和原始 JSON没有凭据
没有提交 SQLite 或临时项目
没有生产代码修改
没有公网部署声明
失败结果没有被写成成功
```

Expected：全部确认。随后进入 `superpowers:finishing-a-development-branch` 生成 PR 内容和合并选项。
