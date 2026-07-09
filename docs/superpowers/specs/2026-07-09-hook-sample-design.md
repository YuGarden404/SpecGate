# SpecGate 第二阶段设计：Lab 11 Hook Sample

## 1. 背景

SpecGate 已经完成最终交付材料打磨，并接入 Lab 10 Skill。下一步最小增强是 Lab 11 Hook sample：用确定性脚本展示提交前防线，但不改变 harness runtime。

该 Hook 不是为了替代 CI，也不是为了强制用户本机安装，而是作为课程中的 HE 证据：高风险动作和质量底线应由确定性脚本守住，而不是只靠 prompt。

## 2. 目标

- 新增 `hooks/pre-commit.sample`。
- 检查 staged 文件中是否出现疑似 API key 或私钥。
- 检查 demo 任务关键文件是否存在：
  - `examples/knowledge_nav/TASK_SPEC.md`
  - `examples/knowledge_nav/CHECKLIST.md`
  - `examples/knowledge_nav/specgate.toml`
- 提示提交前运行全量单元测试。
- 新增测试，确保 Hook sample 包含上述防线。
- 更新 Lab 对齐文档、最终提交清单、README 和 AGENT_LOG。

## 3. 非目标

- 不自动安装到 `.git/hooks/pre-commit`。
- 不修改 `.git/hooks`。
- 不改变 SpecGate CLI、runner、tools、policy 或 Gate 行为。
- 不执行 shell 工具作为 harness runtime 能力。
- 不引入外部依赖。

## 4. 设计

新增文件：

```text
hooks/pre-commit.sample
```

它是 POSIX shell 示例脚本，使用 Git 自带能力检查 staged files。脚本逻辑：

1. 获取 staged 文件列表。
2. 使用 `git grep -E` 扫描常见密钥模式。
3. 检查 demo 任务关键文件存在。
4. 输出推荐测试命令。
5. 如果发现疑似密钥或关键文件缺失，则退出 1。

新增测试：

```text
tests/test_hook_sample.py
```

测试不执行 Hook，以避免 Windows / shell 差异；只验证 sample 中包含密钥扫描、必要文件和测试提示。这符合本阶段定位：Hook 是课程证据和可选样例，不是 Python harness 主链路。

## 5. 风险与边界

- Hook sample 使用 shell，但它不是 SpecGate runtime 工具，不会开放给 LLM。
- Windows 用户如果要安装该 Hook，需要 Git for Windows 的 sh 环境；本项目不强制安装。
- 密钥扫描只是基础正则，不能替代专业 secret scanner。
- CI 仍然是正式验证入口，Hook 只是提交前提醒和早期拦截。
