# AI for Coding 知识图谱验收清单

## 自动 Gate 必检项

以下条目会被 SpecGate 的静态 HTML Gate 解析。格式必须保留为 `- 必须包含 ...`。

- 必须包含 AI for Coding 知识图谱
- 必须包含 TASK_SPEC.md
- 必须包含 CHECKLIST.md
- 必须包含 Spec
- 必须包含 Checklist
- 必须包含 Action Protocol
- 必须包含 MockLLM
- 必须包含 Guardrail
- 必须包含 Tool Dispatcher
- 必须包含 HTML Gate
- 必须包含 Feedback Loop
- 必须包含 Context Pack
- 必须包含 Trace / Report
- 必须包含 Credentials
- 必须包含 Docker / CI

## 内置 Gate 检查项

这些检查由 `src/specgate/gate.py` 的代码完成，不依赖 LLM 自我判断：

- `index.html` 必须存在。
- HTML 必须包含 `<!doctype html>`、`html`、`head`、`title`、`body`。
- 必须包含移动端 `viewport`。
- 必须包含搜索或过滤 UI。
- 必须包含至少 10 个 `class="node"` 的知识节点。
- 必须包含关系高亮能力，例如 `data-related` 或 `highlightRelations`。
- 不允许依赖外部 `http://` 或 `https://` 脚本/样式。
- 不允许包含疑似密钥。

## 人工验收项

以下内容由评审者或开发者人工检查：

- 页面第一屏能说明这是 SpecGate 的静态 HTML Harness demo。
- 知识节点不是占位文本，而是能解释 SpecGate 的核心机制。
- 搜索框可以过滤节点。
- 点击节点后，右侧详情区域会更新。
- 视觉风格简洁、可读，不像测试夹具。
- 页面仍然保持 MVP 边界：单文件静态 HTML，不做复杂前端。
