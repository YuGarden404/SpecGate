# SpecGate 最终使用文档与 v0.1.1 发布实施计划

> **面向 Agent 执行者：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤使用复选框（`- [ ]`）跟踪。

**目标：** 将教师使用文档和项目事实记录同步到 PR #27，准备 `0.1.1` 包版本，并将 `v0.1.0` 保留为不可变的历史发布证据。

**架构：** 阶段 A 在一个发布准备 PR 中更新版本声明、可执行用户流程、源码基线证据及其确定性文档契约。该 PR 合并后由用户创建 `v0.1.1`；只有 GHCR 发布成功后才进入阶段 B，并通过独立证据 PR 记录真实 workflow URL、digest、匿名 smoke 和截图。

**技术栈：** Python 3.11+、`unittest`、Markdown、PowerShell、GitHub Actions、Docker/GHCR、GitHub Pages、NJU GitLab CI。

---

### 任务 1：冻结 v0.1.1 版本契约

**文件：**
- 修改：`tests/test_imports.py`
- 修改：`pyproject.toml`
- 修改：`src/specgate/__init__.py`

- [ ] **步骤 1：修改导入测试，使其要求 v0.1.1**

将现有断言修改为：

```python
self.assertEqual(specgate.__version__, "0.1.1")
```

- [ ] **步骤 2：运行导入测试并确认 RED**

运行：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s tests -p "test_imports.py" -v
```

预期：FAIL，因为 `specgate.__version__` 仍是 `0.1.0`。

- [ ] **步骤 3：更新两处版本声明**

将 `pyproject.toml` 设置为：

```toml
version = "0.1.1"
```

将 `src/specgate/__init__.py` 设置为：

```python
__version__ = "0.1.1"
```

- [ ] **步骤 4：验证 GREEN 与包元数据**

运行：

```powershell
python -m unittest discover -s tests -p "test_imports.py" -v
python -c "import pathlib, sys, tomllib; sys.path.insert(0, str(pathlib.Path('src').resolve())); import specgate; project=tomllib.load(open('pyproject.toml','rb'))['project']['version']; print(project, specgate.__version__); raise SystemExit(project != specgate.__version__)"
```

预期：1 项测试通过，命令输出 `0.1.1 0.1.1`，退出码为 0。

- [ ] **步骤 5：用户提交版本契约**

```powershell
git add -- pyproject.toml src/specgate/__init__.py tests/test_imports.py
git diff --cached --check
git commit -m "chore: 准备 SpecGate 0.1.1 版本"
```

### 任务 2：先更新事实契约，再修改文档

**文件：**
- 修改：`tests/test_final_evidence.py`

- [ ] **步骤 1：替换过期的当前运行结果提取器**

将 `extract_current_final_run` 重命名为 `extract_teacher_verified_run`，并让它只解析一条符合以下格式的记录：

```text
- 教师已验证源码基线（2026-07-19）：`Ran 954 tests in 213.679s`、`OK (skipped=27)`，退出码 0。
```

使用以下正则表达式：

```python
pattern = re.compile(
    r"^- 教师已验证源码基线（2026-07-19）：`"
    r"(?P<result>Ran 954 tests in (?P<duration>[0-9]+(?:\.[0-9]+)?)s)`、"
    r"`OK \(skipped=27\)`，退出码 0。$",
    re.MULTILINE,
)
```

保留耗时必须大于 0 的校验。

- [ ] **步骤 2：重新绑定当前源码基线断言**

将 `test_final_snapshot_uses_pr25_main_and_latest_verification` 重命名为 `test_final_snapshot_uses_pr27_teacher_verified_baseline`，并要求：

```python
self.assertIn("main@6dbaa75", snapshot)
self.assertIn("PR #27", snapshot)
self.assertEqual(teacher_run, "Ran 954 tests in 213.679s")
self.assertIn("CI #67", snapshot)
self.assertIn("Pages #38", snapshot)
self.assertIn("Pipeline #313088", snapshot)
self.assertIn("job #596503", snapshot)
```

保留相关断言，确保 PR #25、CI #63、Pages #36、GHCR #1、`v0.1.0` digest 和五张现有图片继续作为历史证据存在。

- [ ] **步骤 3：扩展快速开始契约**

更新 `test_cli_quickstart_and_ghcr_release_boundary_are_documented`，要求 README 与部署文档的组合文本包含：

```python
for phrase in (
    "https://github.com/YuGarden404/SpecGate.git",
    "https://git.nju.edu.cn/YuyuanLiang/specgate.git",
    "python -m venv .venv",
    ".\\.venv\\Scripts\\Activate.ps1",
    "python -m pip install -e .",
    "TASK_SPEC.md",
    "CHECKLIST.md",
    "specgate run-mock-demo",
    "specgate configure",
    "specgate run <工作区>",
    "specgate credentials clear openai-compatible",
    "specgate-web --host 127.0.0.1 --port 8000",
    "docker build -t specgate:local .",
    "ghcr.io/yugarden404/specgate:0.1.0",
    "v0.1.1",
    "发布镜像不等于部署服务",
):
    self.assertIn(phrase, combined)
```

同时要求文档声明：`v0.1.0` 是历史版本，阶段 A 尚未声称 `v0.1.1` 已经发布。

- [ ] **步骤 4：扩展跨文档事实一致性契约**

在证据矩阵、提交清单、反思事实清单、`PLAN.md` 和 `AGENT_LOG.md` 的最新追加章节中要求以下事实：

```python
teacher_facts = (
    "main@6dbaa75",
    "PR #27",
    "Ran 954 tests in 213.679s",
    "OK (skipped=27)",
    "CI #67",
    "Pages #38",
    "Pipeline #313088",
    "job #596503",
    "glm-5.2",
    "passed=True, steps=2",
    "v0.1.1",
)
```

继续要求每份权威事实文档保留 `v0.1.0` 镜像、digest、GHCR #1 和原始截图，但不得再把 PR #25 称为最新源码基线。

- [ ] **步骤 5：运行文档契约并确认 RED**

运行：

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：失败信息指出旧 PR #25/当前运行表述、缺失的克隆安装流程和缺失的阶段 A 事实。失败必须是过期文档导致的断言失败，不能是语法或导入错误。

### 任务 3：将 README 重写为可执行的教师与用户入口

**文件：**
- 修改：`README.md`

- [ ] **步骤 1：在顶部附近增加仓库职责和克隆命令**

说明两个仓库的职责，但不得暗示 GitHub Actions 元数据会迁移到 GitLab：

```powershell
git clone https://git.nju.edu.cn/YuyuanLiang/specgate.git SpecGate
cd .\SpecGate
```

同时列出 GitHub 开发仓库的克隆方式：

```powershell
git clone https://github.com/YuGarden404/SpecGate.git SpecGate
```

- [ ] **步骤 2：用干净的 Windows 流程替换安装章节**

包含以下准确顺序：

```powershell
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -c "import specgate.workspace_fs as m; print(m.__file__)"
specgate --help
```

说明用户不能在 `.venv` 已激活时重新创建它；Python 必须至少为 3.11；打印出的导入路径必须属于当前克隆。

- [ ] **步骤 3：记录工作区契约和 Mock Demo 边界**

说明 CLI 工作区必须使用可移植的准确文件名 `TASK_SPEC.md` 和 `CHECKLIST.md`；`index.html` 是可选输入，也会成为输出。解释 `run-mock-demo` 使用固定、确定性的知识图谱响应来验证 harness，而任意任务生成需要配置真实 provider 后使用 `specgate run`。

提供：

```powershell
specgate run-mock-demo D:\path\to\workspace
```

列出三个输出路径，并解释 `Gate`、`trusted`、`parse_errors` 和退出码 0。

- [ ] **步骤 4：记录安全的真实模型使用方式**

提供交互式配置流程：

```powershell
specgate configure
specgate credentials status openai-compatible
specgate run <工作区> --max-steps 5 --timeout 120 --governance-profile strict
specgate credentials clear openai-compatible
```

仅将 `https://njusehub.info/v1` 和 `glm-5.2` 作为已验证示例。绝不写入 API key。说明 provider 失败不会降级到 MockLLM，并说明 PowerShell 5.1 查看 trace 时应使用 `Get-Content -Encoding UTF8`。

- [ ] **步骤 5：整合 WebUI、Docker、Pages 和 GHCR 边界**

为每个入口保留一条简洁命令：

```powershell
specgate-web --host 127.0.0.1 --port 8000
docker build -t specgate:local .
docker run --rm specgate:local --help
docker run --rm specgate:local run-mock-demo /opt/specgate/examples/knowledge_nav
```

阶段 A 继续将 `ghcr.io/yugarden404/specgate:0.1.0` 作为已验证的历史公开镜像。声明源码版本 `0.1.1` 已准备，但在标签 workflow 和匿名 smoke 完成前不声称新镜像已经发布。

- [ ] **步骤 6：运行 README 相关契约子集**

运行：

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -k "quickstart" -v
```

预期：快速开始断言通过；源码证据断言在后续任务完成前可以继续保持 RED。

### 任务 4：对齐部署与讲解文档

**文件：**
- 修改：`docs/DEPLOYMENT.md`
- 修改：`docs/PROJECT_WALKTHROUGH.md`

- [ ] **步骤 1：修正部署文档中的 GHCR 状态**

删除“GHCR 公开可见性仍待完成”的过期表述。声明：

- `v0.1.0` 已公开，并已使用现有 digest 完成匿名验证。
- `v0.1.1` 在阶段 A 完成发布准备，但尚未发布。
- 新标签存在前，使用本地源码构建验证 PR #27。
- 已发布镜像是 CLI-first；WebUI 需要 `--entrypoint specgate-web`。
- 公开 registry 不等于已部署 Web 后端。

- [ ] **步骤 2：增加安全的 CLI 凭据生命周期命令**

记录 `specgate configure`、`credentials status`、`specgate run` 和 `credentials clear`，同时保留部署专用环境变量和 Web 主密钥要求。

- [ ] **步骤 3：替换讲解稿中的演示脚本**

默认使用已经安装的 `specgate` CLI，不再依赖仓库 `PYTHONPATH`。讲解稿必须覆盖：

1. 空目录克隆和 editable install。
2. `TASK_SPEC.md` 与 `CHECKLIST.md` 输入。
3. Mock Demo 输出和报告。
4. 教师基线 `Ran 954 tests in 213.679s`。
5. 可选的 `glm-5.2` 两步真实运行和凭据清除。
6. PR #27 Windows 竞态案例。
7. 源码构建、历史 `v0.1.0` 镜像与待发布 `v0.1.1` 的区别。

- [ ] **步骤 4：运行文档契约**

运行：

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：快速开始和部署断言通过；最终材料断言在任务 5 完成前保持 RED。

### 任务 5：同步最终证据与提交材料

**文件：**
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`docs/REFLECTION_FACT_CHECK.md`

- [ ] **步骤 1：更新矩阵快照，但不改写历史**

在矩阵顶部记录：

```text
- 教师已验证源码基线：PR #27 合并后的 `main@6dbaa75`。
- 教师已验证源码基线（2026-07-19）：`Ran 954 tests in 213.679s`、`OK (skipped=27)`，退出码 0。
- 远端源码基线：CI #67、Pages #38、NJU Pipeline #313088 / job #596503 均成功。
- 发布边界：`v0.1.0` 是已验证历史镜像；项目版本已准备为 `0.1.1`，但 Stage A 不声称新镜像已发布。
```

将 PR #27 加入来源链表格。在历史发布章节中保留 PR #25、CI #63、Pages #36、GHCR #1、原 digest 和五张现有图片。

- [ ] **步骤 2：更新最终提交清单**

增加以下条目：

- PR #27 Windows 锁竞态修复。
- 教师空目录克隆安装和 954 项测试验证。
- Mock 工作区 smoke。
- `glm-5.2` 真实 CLI smoke，且 keyring 凭据已清除。
- `v0.1.1` 发布准备，明确尚未完成远端发布。

修改“检查前改为 Public”的过期表述，因为 NJU 仓库已经可以公开克隆，并已用于教师流程。

- [ ] **步骤 3：只更新反思事实清单**

在 `docs/REFLECTION_FACT_CHECK.md` 中，用 PR #27 和教师验证事实替换过期的最终证据条目。保留学生拥有 `REFLECTION.md` 正文的说明；不得修改 `REFLECTION.md`。

- [ ] **步骤 4：运行最终证据测试**

运行：

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：其余事实断言通过，或只指向 `PLAN.md` 和 `AGENT_LOG.md` 中尚未增加的最新章节。

### 任务 6：追加过程记录，但不改写历史计划

**文件：**
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`

- [ ] **步骤 1：追加 PLAN 阶段**

追加标题：

```markdown
# 2026-07-19 最终使用文档与 v0.1.1 发布准备
```

记录两阶段边界、影响文件、TDD 顺序、教师基线、阶段 A 验收条件和阶段 B 发布证据门禁。明确说明历史计划复选框和 `v0.1.0` 证据保持不变。

- [ ] **步骤 2：追加 AGENT_LOG 阶段**

追加标题：

```markdown
## 2026-07-19 最终使用文档与 v0.1.1 发布准备
```

记录：

- 设计批准与隔离工作树。
- PR #27 基线与 Windows 竞态根因。
- 教师克隆、954 项测试输出、Mock Demo 和 `glm-5.2` 两步结果。
- keyring 凭据清除。
- 版本升级 RED/GREEN 证据。
- 文档契约 RED/GREEN 证据。
- 最终验证命令和实际结果。
- 所有 Git add/commit/push/tag/PR 操作继续由用户执行。

- [ ] **步骤 3：运行事实契约直至 GREEN**

运行：

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：`test_final_evidence.py` 中所有测试通过。

- [ ] **步骤 4：用户提交文档主体**

```powershell
git add -- README.md docs/DEPLOYMENT.md docs/PROJECT_WALKTHROUGH.md docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 同步最终使用流程与发布边界"
```

### 任务 7：端到端验证阶段 A

**文件：**
- 实际结果需要同步时修改：`tests/test_final_evidence.py`
- 实际结果需要同步时修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 实际结果需要同步时修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 实际结果需要同步时修改：`docs/REFLECTION_FACT_CHECK.md`
- 实际结果需要同步时修改：`PLAN.md`
- 实际结果需要同步时修改：`AGENT_LOG.md`

- [ ] **步骤 1：运行聚焦测试套件**

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s tests -p "test_imports.py" -v
python -m unittest discover -s tests -p "test_cli.py"
python -m unittest discover -s tests -p "test_workflows.py" -v
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：所有聚焦测试套件通过。

- [ ] **步骤 2：运行语法与安全检查**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
```

扫描已跟踪实现和当前材料中的真实密钥模式，同时排除历史测试夹具和实施计划。不得出现真实凭据。

运行：

```powershell
git grep -n -E "sk-[A-Za-z0-9_-]{20,}" -- src .github Dockerfile README.md docs/DEPLOYMENT.md docs/PROJECT_WALKTHROUGH.md docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md
```

预期：无输出且退出码为 1，表示没有找到该模式。

- [ ] **步骤 3：运行完整测试套件**

```powershell
python -m unittest discover -s tests
```

预期：退出码为 0。记录本次全新运行的准确测试数量、耗时和跳过数量。

- [ ] **步骤 4：如果阶段 A 结果与教师基线不同，则同步新结果**

如果阶段 A 的测试数量或耗时不同于 `Ran 954 tests in 213.679s`，则在证据矩阵、提交清单、反思事实清单、PLAN 最新章节和 AGENT_LOG 最新章节中增加独立的“阶段 A 发布准备分支验证”记录。不得修改教师基线记录。将相应测试契约更新为准确的新结果，然后重新运行 `test_final_evidence.py` 和完整套件。

- [ ] **步骤 5：审查最终工作树**

用户运行：

```powershell
git diff --check
git status --short --branch
git diff --stat
```

预期：只有计划中的版本、文档、计划/日志和契约测试文件发生修改。

- [ ] **步骤 6：用户提交最终验证同步**

如果步骤 4 或审查清理修改了文件：

```powershell
git add -- tests/test_final_evidence.py docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md
git diff --cached --check
git commit -m "docs: 冻结 v0.1.1 发布准备证据"
```

### 任务 8：审查、推送并合并阶段 A

**文件：**
- 除非审查发现经过验证的问题，否则不再修改文件。

- [ ] **步骤 1：请求代码与文档审查**

审查从 `main@6dbaa75` 到分支 HEAD 的完整范围。优先查找事实矛盾、凭据泄露、版本不一致、过期的“当前”表述，以及无法在干净 Windows 克隆中执行的命令。

- [ ] **步骤 2：用户推送分支**

```powershell
git push -u origin final-docs-v011-prep
```

- [ ] **步骤 3：创建阶段 A PR**

PR 必须说明 `v0.1.1` 已准备但尚未发布。等待 CI 和 Pages 成功后再合并。

- [ ] **步骤 4：将合并后的 main 同步到 NJU GitLab**

合并后，用户更新本地 main，验证 GitHub/NJU commit 一致，并将 `main:main` 推送到 `nju`。

```powershell
cd D:\code\NJU\SpecGate
git switch main
git pull --ff-only origin main
git push nju main:main
git fetch --prune origin
git fetch --prune nju
git rev-parse main
git rev-parse origin/main
git rev-parse nju/main
```

预期：最后三个 commit ID 完全一致。

### 任务 9：通过阶段 B 发布门禁

**文件：**
- 远端事实存在后，阶段 B 使用新的工作树和新的证据同步计划。

- [ ] **步骤 1：确认 v0.1.1 标签尚未使用**

用户检查本地、GitHub 和 NJU 标签命名空间。不得移动现有标签。

```powershell
git tag --list v0.1.1
git ls-remote --tags origin refs/tags/v0.1.1
git ls-remote --tags nju refs/tags/v0.1.1
```

预期：三个命令都不输出标签结果。

- [ ] **步骤 2：创建并推送 v0.1.1**

在阶段 A merge commit 上创建 annotated `v0.1.1` 标签并推送到 GitHub。GHCR workflow 完成前不得声称发布成功。

```powershell
git tag -a v0.1.1 -m "release: SpecGate 0.1.1"
git push origin v0.1.1
git rev-list -n 1 v0.1.1
git rev-parse main
```

预期：标签 commit 与 `main` 完全一致。

- [ ] **步骤 3：运行匿名 GHCR smoke**

使用全新的空 `DOCKER_CONFIG`，拉取 `ghcr.io/yugarden404/specgate:0.1.1`，运行 CLI help、Mock Demo 和 `specgate-web --help`，然后检查 RepoDigests 与 OCI revision。每个命令的退出码都必须为 0，revision 必须等于带标签的 merge commit。

```powershell
$previousDockerConfig = $env:DOCKER_CONFIG
$anonymousDockerConfig = Join-Path `
  $env:TEMP `
  ("specgate-v011-anonymous-" + [guid]::NewGuid())

New-Item -ItemType Directory -Path $anonymousDockerConfig | Out-Null

try {
  $env:DOCKER_CONFIG = $anonymousDockerConfig

  docker pull ghcr.io/yugarden404/specgate:0.1.1
  Write-Host "Pull exit code: $LASTEXITCODE"

  docker run --rm ghcr.io/yugarden404/specgate:0.1.1 --help
  Write-Host "CLI help exit code: $LASTEXITCODE"

  docker run --rm `
    ghcr.io/yugarden404/specgate:0.1.1 `
    run-mock-demo /opt/specgate/examples/knowledge_nav
  Write-Host "Mock demo exit code: $LASTEXITCODE"

  docker run --rm `
    --entrypoint specgate-web `
    ghcr.io/yugarden404/specgate:0.1.1 `
    --help
  Write-Host "Web help exit code: $LASTEXITCODE"

  docker image inspect `
    ghcr.io/yugarden404/specgate:0.1.1 `
    --format '{{json .RepoDigests}}'

  docker image inspect `
    ghcr.io/yugarden404/specgate:0.1.1 `
    --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
}
finally {
  if ($null -eq $previousDockerConfig) {
    Remove-Item Env:\DOCKER_CONFIG -ErrorAction SilentlyContinue
  } else {
    $env:DOCKER_CONFIG = $previousDockerConfig
  }

  Remove-Item -Recurse -Force -LiteralPath $anonymousDockerConfig
}
```

预期：四个打印出的退出码均为 0，RepoDigests 包含 `specgate@sha256:...`，OCI revision 等于 `git rev-parse main`。

- [ ] **步骤 4：归档远端证据**

截取成功的 GHCR run、Public Package 标签、匿名 smoke 和不可变 digest，不得包含凭据或无关账户数据。

- [ ] **步骤 5：启动独立的阶段 B 证据同步分支**

只有此时才能更新 README、部署文档和当前发布事实，加入新截图，在测试中绑定真实 digest 与 run URL，并同步 GitHub/NJU `main` 和 `v0.1.1`。
