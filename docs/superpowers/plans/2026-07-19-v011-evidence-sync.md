# v0.1.1 发布证据同步实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将已经真实成立的 `v0.1.1` 标签、GHCR 发布、匿名 smoke、GitHub/NJU 同步状态写入权威材料，并用自动化契约和截图形成可复核的 Stage B 证据包。

**架构：** 以 `tests/test_final_evidence.py` 作为发布事实契约，先要求精确的 commit、tag object、workflow、digest、OCI revision 和截图路径并确认 RED，再归档原始截图并更新当前事实章节。历史 `v0.1.0` 证据和 Stage A 当时的“尚未发布”记录保持原样；所有当前状态材料必须继续区分公开 CLI 镜像和未部署的公网交互式 Web 后端。

**技术栈：** Python `unittest`、Markdown、PNG 结构校验、PowerShell、Git、Docker/GHCR、GitHub Actions、NJU GitLab CI。

---

## 文件结构

- 创建 `docs/evidence/github-actions-ghcr-v0.1.1-success.png`：GHCR #2 成功运行截图。
- 创建 `docs/evidence/github-package-specgate-v0.1.1-public.png`：Public Package 与 `0.1.1` 标签截图。
- 创建 `docs/evidence/ghcr-v0.1.1-anonymous-smoke.png`：匿名 pull、四项 smoke、digest、revision 与临时配置清理截图。
- 修改 `tests/test_final_evidence.py`：新增 Stage B 精确事实、图片存在性、历史保留与部署边界契约。
- 修改 `README.md`：将当前发布状态更新为已验证的 `v0.1.1`，保留 `v0.1.0` 历史链。
- 修改 `docs/DEPLOYMENT.md`：给出当前公开镜像、不可变 digest、匿名验证和 Web 部署边界。
- 修改 `docs/PROJECT_WALKTHROUGH.md`：把教师演示中的发布证据更新到 PR #28 / GHCR #2。
- 修改 `docs/FINAL_EVIDENCE_MATRIX.md`：加入 Stage B 精确远端事实和三张截图。
- 修改 `docs/FINAL_SUBMISSION_CHECKLIST.md`：冻结标签、镜像和双远端验收状态。
- 修改 `docs/REFLECTION_FACT_CHECK.md`：只同步事实核对项，不修改学生正文 `REFLECTION.md`。
- 修改 `PLAN.md`：追加 Stage B 当前状态章节，不改写 Stage A 历史章节。
- 修改 `AGENT_LOG.md`：追加证据来源、RED/GREEN、验证和审查记录。

### 任务 1：建立 Stage B 失败契约

**文件：**
- 修改：`tests/test_final_evidence.py`

- [ ] **步骤 1：新增精确发布常量和当前材料范围**

在测试中绑定以下不可互换的事实：

```python
V011_RELEASE_FACTS = (
    "PR #28",
    "main@9cf9093",
    "CI #69",
    "29678498485",
    "Pages #39",
    "29678498457",
    "GHCR #2",
    "29679264248",
    "Pipeline #313118",
    "job #596642",
    "v0.1.1",
    "adb74ca0586b20e3cb5e32767bb409370e70c2ef",
    "sha256:8cb8e5b9c9483a7f6bb70cc27fc3f3053b48be2f4a69374865e7bcbbaca4fd0f",
    "9cf909341cd1a5feb8ed2b244ce31f0495016c4c",
)
```

当前权威材料范围为 `README.md`、`docs/DEPLOYMENT.md`、`docs/PROJECT_WALKTHROUGH.md`、`docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md`、`docs/REFLECTION_FACT_CHECK.md`、`PLAN.md` 最新章节和 `AGENT_LOG.md` 最新章节。

- [ ] **步骤 2：新增三张截图与历史证据保留断言**

要求以下文件存在、是可完整解析且 CRC 正确的 PNG：

```python
V011_EVIDENCE_IMAGES = (
    "docs/evidence/github-actions-ghcr-v0.1.1-success.png",
    "docs/evidence/github-package-specgate-v0.1.1-public.png",
    "docs/evidence/ghcr-v0.1.1-anonymous-smoke.png",
)
```

同时继续要求五张 `v0.1.0` 历史图片、`GHCR #1`、`main@44b236f` 和历史 digest 原样存在。

- [ ] **步骤 3：新增状态边界断言**

当前材料必须声明 `v0.1.1` 已发布且匿名验证通过，并明确：

```text
发布公开 CLI 镜像不等于部署公网交互式 Web 后端；公网交互式 Web 后端未部署。
```

测试只在“当前状态”章节排除“`v0.1.1` 尚未发布”等过期陈述，不扫描并改写 Stage A 的日期化历史记录。

- [ ] **步骤 4：运行契约并确认 RED**

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：失败原因仅为三张 Stage B 图片缺失和当前材料仍记录 Stage A 状态；不得出现语法、导入或 PNG 校验器错误。

### 任务 2：归档原始发布证据

**文件：**
- 创建：`docs/evidence/github-actions-ghcr-v0.1.1-success.png`
- 创建：`docs/evidence/github-package-specgate-v0.1.1-public.png`
- 创建：`docs/evidence/ghcr-v0.1.1-anonymous-smoke.png`

- [ ] **步骤 1：从用户提供的原始附件复制三张图片**

使用二进制复制，不重新编码、不裁剪、不生成替代图：

```powershell
Copy-Item -LiteralPath <GHCR-run-附件> -Destination docs/evidence/github-actions-ghcr-v0.1.1-success.png
Copy-Item -LiteralPath <Public-Package-附件> -Destination docs/evidence/github-package-specgate-v0.1.1-public.png
Copy-Item -LiteralPath <匿名-smoke-附件> -Destination docs/evidence/ghcr-v0.1.1-anonymous-smoke.png
```

- [ ] **步骤 2：检查文件哈希、尺寸与 PNG 完整性**

```powershell
Get-FileHash docs/evidence/*v0.1.1*.png -Algorithm SHA256
python -m unittest discover -s tests -p "test_final_evidence.py" -k "png" -v
```

预期：三张文件均非空，PNG 结构校验通过；测试仍可因尚未同步的 Markdown 事实保持 RED。

### 任务 3：同步当前发布材料

**文件：**
- 修改：`README.md`
- 修改：`docs/DEPLOYMENT.md`
- 修改：`docs/PROJECT_WALKTHROUGH.md`
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`docs/REFLECTION_FACT_CHECK.md`

- [ ] **步骤 1：更新源码交付基线**

写明 PR #28 合并后的 `main@9cf9093`，GitHub [CI #69](https://github.com/YuGarden404/SpecGate/actions/runs/29678498485)、[Pages #39](https://github.com/YuGarden404/SpecGate/actions/runs/29678498457) 以及 NJU Pipeline #313118 / job #596642 成功。GitHub Actions 与 NJU GitLab CI 各自承担的证据角色必须分开描述。

- [ ] **步骤 2：更新 v0.1.1 发布链**

写明 annotated tag object 为 `adb74ca0586b20e3cb5e32767bb409370e70c2ef`，peeled commit / OCI revision 为 `9cf909341cd1a5feb8ed2b244ce31f0495016c4c`，GHCR #2 run 为 `29679264248`，镜像为 `ghcr.io/yugarden404/specgate:0.1.1`，RepoDigest 为：

```text
sha256:8cb8e5b9c9483a7f6bb70cc27fc3f3053b48be2f4a69374865e7bcbbaca4fd0f
```

记录匿名 pull、CLI help、Mock Demo、Web help 均退出码 0，临时匿名 Docker 配置已清理。

- [ ] **步骤 3：保留历史与部署边界**

不得删除或改写 `v0.1.0`、`main@44b236f`、GHCR #1、历史 digest 和五张历史截图。明确镜像是 CLI-first；虽然容器内存在 `specgate-web` 入口，但公开 registry 与 CLI 镜像发布不代表公网交互式 Web 后端已经部署。

- [ ] **步骤 4：运行最终证据契约直至 GREEN**

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：所有最终证据测试通过。

### 任务 4：追加 Stage B 过程记录

**文件：**
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`

- [ ] **步骤 1：追加 PLAN 当前章节**

增加 `# 2026-07-19 v0.1.1 发布证据同步`，记录标签双远端一致性、GHCR #2、Public Package、匿名 smoke、digest/revision、三张截图、TDD 与验收命令。Stage A 原章节保持原样。

- [ ] **步骤 2：追加 AGENT_LOG 当前章节**

增加 `## 2026-07-19 v0.1.1 发布证据同步`，记录用户执行的远端操作、PowerShell Go-template 引号失败的真实原因、结构化 inspection 的成功结果、截图来源、RED/GREEN 和最终验证。明确所有 Git add/commit/push/PR 操作仍由用户执行。

- [ ] **步骤 3：重新运行证据契约**

```powershell
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

预期：全部通过，且 `REFLECTION.md` 未发生变化。

### 任务 5：端到端验证与独立审查

**文件：**
- 必要时按审查结果修改上述 Stage B 文件。

- [ ] **步骤 1：运行聚焦测试**

```powershell
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m unittest discover -s tests -p "test_imports.py" -v
python -m unittest discover -s tests -p "test_cli.py"
python -m unittest discover -s tests -p "test_workflows.py" -v
python -m unittest discover -s tests -p "test_final_evidence.py" -v
```

- [ ] **步骤 2：运行语法与密钥检查**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git grep -n -E "sk-[A-Za-z0-9_-]{20,}" -- src .github Dockerfile README.md docs/DEPLOYMENT.md docs/PROJECT_WALKTHROUGH.md docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md
```

预期：编译和 JavaScript 检查退出码 0；密钥扫描无输出且退出码 1。

- [ ] **步骤 3：运行完整测试**

```powershell
python -m unittest discover -s tests
```

记录本次新鲜运行的测试数、耗时、跳过数和退出码；不得覆盖教师干净克隆的 `Ran 954 tests in 213.679s` 基线。

- [ ] **步骤 4：请求独立审查并处理发现**

审查 `main@9cf9093..v011-evidence-sync` 的工作树差异，优先检查事实矛盾、历史证据损坏、路径失效、凭据泄露、当前/历史范围混淆，以及把公开镜像误写成公网 Web 部署。修复 Critical/Important 问题并重新运行受影响验证。

- [ ] **步骤 5：检查最终范围**

```powershell
git diff --check
git status --short --branch
git diff --stat
git diff -- REFLECTION.md
```

预期：只有本计划列出的文档、测试和三张图片发生变化，`REFLECTION.md` 无差异。

### 任务 6：交给用户提交 Stage B

**文件：**
- 不再修改文件，除非最终检查发现问题。

- [ ] **步骤 1：向用户提供手动提交指令**

```powershell
git add -- README.md PLAN.md AGENT_LOG.md docs/DEPLOYMENT.md docs/PROJECT_WALKTHROUGH.md docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md docs/evidence/github-actions-ghcr-v0.1.1-success.png docs/evidence/github-package-specgate-v0.1.1-public.png docs/evidence/ghcr-v0.1.1-anonymous-smoke.png docs/superpowers/plans/2026-07-19-v011-evidence-sync.md tests/test_final_evidence.py
git diff --cached --check
git diff --cached --stat
git commit -m "docs: 同步 v0.1.1 发布证据"
git push -u origin v011-evidence-sync
```

- [ ] **步骤 2：创建并验收 Stage B PR**

PR 目标为 `main`。等待 GitHub CI/Pages 成功后合并；合并后由用户同步 GitHub/NJU `main`。`v0.1.1` 已冻结在 `9cf9093`，不得因证据 PR 产生的新 merge commit 而移动或重建标签。

## 自审结果

- 规格覆盖：三张截图、精确远端事实、TDD、历史保留、部署边界、过程记录、全量验证、独立审查和用户手动 Git 流程均有对应任务。
- 占位符检查：仅附件复制命令中的 `<...-附件>` 表示运行时已由用户提供的三个绝对临时路径；执行时必须替换为实际路径，不是未决设计。
- 一致性检查：所有章节统一使用 PR #28、`main@9cf9093`、CI #69、Pages #39、GHCR #2、Pipeline #313118 / job #596642、同一 digest、tag object 与 OCI revision。
