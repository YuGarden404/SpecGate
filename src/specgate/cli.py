from __future__ import annotations

import argparse
from pathlib import Path

from specgate.config import load_policy
from specgate.gate import run_html_gate
from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.report import generate_report
from specgate.runner import AgentRunner


def _fixed_demo_html() -> str:
    node_data = [
        (
            "spec",
            "Spec 规范文档",
            "规约层",
            "定义目标、范围、输入输出和验收边界，是 agent 开始行动前的任务契约。",
            "SPEC.md / TASK_SPEC.md",
            "checklist,context",
        ),
        (
            "checklist",
            "Checklist 检查清单",
            "规约层",
            "把主观需求变成可执行检查项，用于自动验收页面是否符合任务要求。",
            "CHECKLIST.md",
            "spec,gate",
        ),
        (
            "action",
            "Action Protocol",
            "决策层",
            "要求模型只输出严格 JSON 动作，避免自然语言直接驱动文件系统。",
            "src/specgate/actions.py",
            "mockllm,guardrail",
        ),
        (
            "mockllm",
            "MockLLM",
            "决策层",
            "用脚本化响应替代真实模型，让主循环、失败反馈和修复行为可以离线测试。",
            "src/specgate/llm.py",
            "action,runner",
        ),
        (
            "guardrail",
            "Guardrail 护栏",
            "治理层",
            "在工具执行前拦截未知动作、路径越界和未授权写入，安全逻辑由代码保证。",
            "src/specgate/policy.py",
            "action,tools",
        ),
        (
            "tools",
            "Tool Dispatcher",
            "执行层",
            "只分发白名单文件工具，把执行结果结构化回传给 agent loop。",
            "src/specgate/tools.py",
            "guardrail,runner",
        ),
        (
            "gate",
            "HTML Gate",
            "反馈层",
            "解析 index.html，检查结构、节点数量、搜索过滤、关系高亮和 checklist 词项。",
            "src/specgate/gate.py",
            "checklist,feedback",
        ),
        (
            "feedback",
            "Feedback Loop",
            "反馈层",
            "Gate 失败摘要进入下一轮上下文，推动 MockLLM 从失败草稿改成合格页面。",
            "src/specgate/runner.py",
            "gate,context",
        ),
        (
            "context",
            "Context Pack",
            "记忆层",
            "组合任务文档、当前产物摘要和最近 Gate 结果，让模型获得必要上下文。",
            "src/specgate/context.py",
            "spec,feedback,trace",
        ),
        (
            "trace",
            "Trace / Report",
            "可观测层",
            "记录模型输出、工具结果、护栏决策和 Gate 结果，并生成静态运行报告。",
            "src/specgate/trace.py / src/specgate/report.py",
            "context,credentials",
        ),
        (
            "credentials",
            "Credentials",
            "安全层",
            "Mock 模式不需要密钥；真实 provider 默认 fail closed，避免误用未配置凭据。",
            "src/specgate/credentials.py",
            "trace,docker",
        ),
        (
            "docker",
            "Docker / CI",
            "分发层",
            "用容器和 CI 证明项目可以在新环境中运行测试与 mock demo。",
            "Dockerfile / .gitlab-ci.yml",
            "credentials,gate",
        ),
    ]
    nodes = "\n".join(
        f"""
        <button class="node" type="button" data-id="{node_id}" data-related="{related}" onclick="showDetail('{node_id}')">
          <span class="layer">{layer}</span>
          <h2>{title}</h2>
          <p>{detail}</p>
          <small>{artifact}</small>
        </button>"""
        for node_id, title, layer, detail, artifact, related in node_data
    )
    detail_items = ",\n".join(
        f""""{node_id}": {{
      title: "{title}",
      layer: "{layer}",
      detail: "{detail}",
      artifact: "{artifact}",
      related: "{related}"
    }}"""
        for node_id, title, layer, detail, artifact, related in node_data
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI for Coding 知识图谱</title>
  <style>
    :root {{
      --bg: #eef2f6;
      --ink: #17202a;
      --muted: #667382;
      --line: #d8e0ea;
      --paper: #ffffff;
      --soft: #f8fafc;
      --blue: #2f6fed;
      --teal: #0f8a83;
      --orange: #c46a2f;
      --shadow: 0 24px 70px rgba(18, 28, 42, 0.13);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: linear-gradient(180deg, #f4f7fb 0%, #edf2f7 100%);
      color: var(--ink);
      font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
      letter-spacing: 0;
    }}
    .topbar {{
      height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      background: rgba(250, 252, 255, 0.92);
      border-bottom: 1px solid var(--line);
      position: sticky;
      top: 0;
      z-index: 2;
    }}
    .brand {{ display: flex; align-items: center; gap: 10px; font-weight: 700; }}
    .brand-mark {{
      width: 44px;
      height: 30px;
      border-radius: 6px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: white;
      background: linear-gradient(135deg, #17202a, #2f6fed);
      font-size: 13px;
    }}
    .progress {{ height: 4px; background: linear-gradient(90deg, var(--blue), var(--teal), var(--orange)); }}
    main {{
      width: min(1480px, calc(100vw - 48px));
      margin: 34px auto;
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 24px;
    }}
    .stage {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 44px 52px;
      min-height: 720px;
      position: relative;
    }}
    .stage::before {{
      content: "";
      position: absolute;
      inset: 0 0 auto 0;
      height: 5px;
      border-radius: 8px 8px 0 0;
      background: linear-gradient(90deg, var(--blue), var(--teal), var(--orange), #7556d9);
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 28px;
      align-items: end;
      margin-bottom: 28px;
    }}
    .eyebrow {{
      margin: 0 0 10px;
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
      text-transform: uppercase;
    }}
    h1 {{ margin: 0; font-size: 42px; line-height: 1.12; }}
    .subtitle {{ color: var(--muted); font-size: 18px; margin-top: 12px; max-width: 760px; }}
    .search {{
      width: 320px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 11px 12px;
      font: inherit;
      background: var(--soft);
    }}
    .node-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
    }}
    .node {{
      text-align: left;
      border: 1px solid var(--line);
      background: white;
      border-radius: 8px;
      padding: 18px;
      min-height: 172px;
      cursor: pointer;
      transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
    }}
    .node:hover,
    .node.active {{
      border-color: var(--blue);
      box-shadow: 0 12px 24px rgba(47, 111, 237, 0.12);
      transform: translateY(-1px);
    }}
    .node.related {{ border-color: var(--teal); background: #f2fbfa; }}
    .node[hidden] {{ display: none; }}
    .layer {{
      color: var(--blue);
      font-weight: 800;
      font-size: 13px;
    }}
    .node h2 {{ margin: 10px 0 8px; font-size: 21px; }}
    .node p {{ color: var(--muted); margin: 0 0 12px; line-height: 1.5; }}
    .node small {{ color: var(--orange); font-weight: 700; }}
    .knowledge-detail {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 14px 34px rgba(18, 28, 42, 0.08);
      padding: 24px;
      align-self: start;
      position: sticky;
      top: 82px;
    }}
    .knowledge-detail h2 {{ margin: 0 0 8px; font-size: 28px; }}
    .knowledge-detail .meta {{ color: var(--blue); font-weight: 800; margin-bottom: 16px; }}
    .knowledge-detail p {{ color: var(--muted); line-height: 1.65; }}
    .detail-list {{ margin: 18px 0 0; padding: 0; list-style: none; }}
    .detail-list li {{
      border-top: 1px solid var(--line);
      padding: 12px 0;
      color: var(--muted);
    }}
    .empty {{ color: var(--muted); margin-top: 20px; }}
    @media (max-width: 980px) {{
      main {{ grid-template-columns: 1fr; }}
      .hero {{ align-items: stretch; flex-direction: column; }}
      .search {{ width: 100%; }}
      .node-grid {{ grid-template-columns: 1fr; }}
      .stage {{ padding: 34px 24px; }}
      h1 {{ font-size: 34px; }}
      .knowledge-detail {{ position: static; }}
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="brand-mark">SG</span><span>SpecGate 静态 HTML Harness</span></div>
    <span>MockLLM · Guardrail · Gate · Report</span>
  </header>
  <div class="progress" aria-hidden="true"></div>
  <main>
    <section class="stage">
      <div class="hero">
        <div>
          <p class="eyebrow">AI4SE Knowledge Navigator</p>
          <h1>AI for Coding 知识图谱</h1>
          <p class="subtitle">根据 TASK_SPEC.md 与 CHECKLIST.md 生成的静态页面，用于展示 SpecGate 如何把规约、工具、护栏和 Gate 反馈闭环串起来。</p>
        </div>
        <input id="searchBox" class="search" type="search" placeholder="搜索知识点、层级或文件" oninput="filterNodes()">
      </div>
      <div id="nodeGrid" class="node-grid">
        {nodes}
      </div>
      <p id="emptyState" class="empty" hidden>没有找到匹配的知识点。</p>
    </section>
    <aside class="knowledge-detail" id="knowledgeDetail" aria-label="知识点详情">
      <p class="eyebrow">Knowledge Detail</p>
      <h2>Spec 规范文档</h2>
      <div class="meta">规约层</div>
      <p>定义目标、范围、输入输出和验收边界，是 agent 开始行动前的任务契约。</p>
      <ul class="detail-list">
        <li><strong>对应文件：</strong><span>SPEC.md / TASK_SPEC.md</span></li>
        <li><strong>关联节点：</strong><span>checklist, context</span></li>
      </ul>
    </aside>
  </main>
  <script>
    const knowledge = {{
      {detail_items}
    }};

    function allNodes() {{
      return Array.from(document.querySelectorAll(".node"));
    }}

    function showDetail(id) {{
      const item = knowledge[id];
      if (!item) return;
      const panel = document.getElementById("knowledgeDetail");
      panel.innerHTML = `
        <p class="eyebrow">Knowledge Detail</p>
        <h2>${{item.title}}</h2>
        <div class="meta">${{item.layer}}</div>
        <p>${{item.detail}}</p>
        <ul class="detail-list">
          <li><strong>对应文件：</strong><span>${{item.artifact}}</span></li>
          <li><strong>关联节点：</strong><span>${{item.related}}</span></li>
        </ul>`;
      allNodes().forEach((node) => node.classList.toggle("active", node.dataset.id === id));
      highlightRelations(id);
    }}

    function highlightRelations(id) {{
      const item = knowledge[id];
      const related = item ? item.related.split(",") : [];
      allNodes().forEach((node) => {{
        node.classList.toggle("related", related.includes(node.dataset.id));
      }});
    }}

    function filterNodes() {{
      const query = document.getElementById("searchBox").value.trim().toLowerCase();
      let visible = 0;
      allNodes().forEach((node) => {{
        const text = node.textContent.toLowerCase();
        const match = !query || text.includes(query);
        node.hidden = !match;
        if (match) visible += 1;
      }});
      document.getElementById("emptyState").hidden = visible !== 0;
    }}
  </script>
</body>
</html>"""


def _default_demo_policy(root: Path) -> WorkspacePolicy:
    return WorkspacePolicy(
        root=root,
        allowed_actions={"write_file", "replace_file", "read_file", "list_files", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )


def _load_demo_policy(root: Path) -> WorkspacePolicy:
    config_path = root / "specgate.toml"
    if config_path.exists():
        return load_policy(config_path)
    return _default_demo_policy(root)


def run_mock_demo(root: Path) -> int:
    llm = MockLLM(
        [
            {
                "schema_version": "1",
                "action": "write_file",
                "args": {"path": "index.html", "content": "<html><head><title>x</title></head><body></body></html>"},
            },
            {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": _fixed_demo_html()}},
            {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
        ]
    )
    policy = _load_demo_policy(root)
    result = AgentRunner(root, llm, policy, max_steps=5).run()
    gate = result.final_gate or run_html_gate(root / "index.html", root / "CHECKLIST.md")
    generate_report(root, gate, result.steps)
    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specgate")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("run-mock-demo")
    demo.add_argument("workspace")
    args = parser.parse_args(argv)
    if args.command == "run-mock-demo":
        return run_mock_demo(Path(args.workspace))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
