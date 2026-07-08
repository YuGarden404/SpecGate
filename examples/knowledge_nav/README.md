# knowledge_nav 示例任务说明

这个目录是一组 SpecGate 运行时示例文件，用来演示“根据任务规约生成/修复静态 HTML”的闭环。

## 输入文件

- `TASK_SPEC.md`：用户需求。它描述这次要生成什么 HTML 页面。
- `CHECKLIST.md`：验收清单。`- 必须包含 ...` 格式的条目会被静态 Gate 自动检查。
- `specgate.toml`：本任务的 workspace policy。它声明允许的动作、可读文件和可写文件。

## 输出文件

- `index.html`：SpecGate 生成的最终静态 HTML 产物，也就是“AI for Coding 知识图谱”页面。
- `reports/latest/index.html`：本次运行报告，展示 Gate 检查项和通过状态。
- `runs/latest/trace.jsonl`：本次运行 trace。每一行是一条 JSON 事件，记录 LLM 响应、工具执行、Gate 结果等过程证据。

## 和 `site/` 的区别

- `examples/knowledge_nav/index.html` 是 harness 的示例任务产物。
- `site/index.html` 是 GitHub Pages 的公开首页，用来链接 demo、报告和仓库。
- Pages workflow 会在远端部署时把示例产物复制到站点目录中，让老师可以通过公网 URL 打开。

## 重新生成

在项目根目录运行：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

然后打开：

```text
examples/knowledge_nav/index.html
examples/knowledge_nav/reports/latest/index.html
```
