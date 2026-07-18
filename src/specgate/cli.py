from __future__ import annotations

import argparse
import getpass
import json
from datetime import datetime, timezone
from pathlib import Path

from specgate.approvals import (
    ApprovalStore,
    GovernanceConfig,
    approval_queue_path,
    read_approval_queue_if_present,
    read_existing_approval_queue,
)
from specgate.benchmark import summarize_benchmark
from specgate.config import WorkspaceConfig, load_workspace_config
from specgate.context import VALID_CONTEXT_STRATEGIES
from specgate.credential_store import CredentialStoreUnavailable
from specgate.credentials import clear_credential, credential_status, read_credential, set_credential
from specgate.eval_runner import run_eval_suite
from specgate.gate import run_html_gate
from specgate.llm import LLMProviderError, MockLLM, OpenAICompatibleLLM
from specgate.policy import WorkspacePolicy
from specgate.report import generate_report
from specgate.runner import AgentRunner
from specgate.trace import redact
from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    load_user_llm_config,
    save_user_llm_config,
    user_config_path,
)
from specgate.workspace_fs import WorkspacePathError


GOVERNANCE_PROFILES = ("strict", "demo", "review")


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
    return _load_workspace_settings(root).policy


def _load_workspace_settings(root: Path) -> WorkspaceConfig:
    config_path = root / "specgate.toml"
    if config_path.exists():
        return load_workspace_config(config_path)
    return WorkspaceConfig(policy=_default_demo_policy(root), governance=GovernanceConfig())


def list_approvals(root: Path) -> int:
    try:
        queue = read_approval_queue_if_present(root, approval_queue_path(root))

        if queue is None or not queue.approvals:
            print("no pending approvals")
            return 0

        rows = []
        for approval in queue.approvals:
            approval_id = approval.id
            status = approval.status
            action = approval.action
            path = approval.path
            reason = approval.reason
            decision_reason = approval.decision_reason or ""
            if not all(isinstance(value, str) for value in (approval_id, status, action, reason)):
                raise ValueError("approval display fields must be strings")
            if not isinstance(decision_reason, str):
                raise ValueError("approval decision reason must be a string or null")
            if path is not None and not isinstance(path, str):
                raise ValueError("approval path must be a string or null")
            display_values = redact(
                [
                    approval_id,
                    status,
                    action,
                    path or "",
                    reason,
                    decision_reason,
                ]
            )
            if not all(isinstance(value, str) for value in display_values):
                raise ValueError("approval display fields must be strings")
            rows.append(
                "\t".join(
                    display_values
                )
            )

        print("id\tstatus\taction\tpath\treason\tdecision_reason")
        for row in rows:
            print(row)
    except WorkspacePathError as exc:
        print(f"could not read pending approvals safely: {exc.rule_family}")
        return 1
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        print("could not read pending approvals: malformed queue")
        return 1
    return 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def update_approval(root: Path, approval_id: str, decision: str, reason: str | None = None) -> int:
    try:
        queue_path = approval_queue_path(root)
        store = ApprovalStore(queue_path)
        queue = store.read_existing()
        if decision == "approve":
            store.decide(
                approval_id,
                "approved",
                expected_revision=queue.revision,
                decided_at=_utc_now(),
            )
            message = f"approved {approval_id}"
        elif decision == "deny":
            store.decide(
                approval_id,
                "denied",
                expected_revision=queue.revision,
                reason=reason or "human denied",
                decided_at=_utc_now(),
            )
            message = f"denied {approval_id}"
        else:
            print("could not update approval: invalid decision")
            return 1
        print(message)
        return 0
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        print("could not update approval")
        return 1


def run_mock_demo(root: Path, governance_profile: str | None = None) -> int:
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
    settings = _load_workspace_settings(root)
    result = AgentRunner(
        root,
        llm,
        settings.policy,
        max_steps=5,
        governance_profile=governance_profile,
        governance_config=settings.governance,
    ).run()
    gate = result.final_gate or run_html_gate(root / "index.html", root / "CHECKLIST.md")
    generate_report(
        root,
        gate,
        result.steps,
        metrics=result.metrics,
        permission_decisions=result.permission_decisions,
        trust=result.trust,
        profile=result.profile,
    )
    return 0 if result.passed else 1


def run_resume(root: Path, max_steps: int, governance_profile: str | None = None) -> int:
    settings = _load_workspace_settings(root)
    llm = MockLLM(
        [
            {
                "schema_version": "1",
                "action": "finish",
                "args": {"summary": "resume complete"},
            }
        ]
    )
    try:
        result = AgentRunner(
            root,
            llm,
            settings.policy,
            max_steps=max_steps,
            governance_profile=governance_profile,
            governance_config=settings.governance,
        ).resume_from_approval()
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"could not resume: {redact(str(exc))}")
        return 1
    gate = result.final_gate or run_html_gate(root / "index.html", root / "CHECKLIST.md")
    generate_report(
        root,
        gate,
        result.steps,
        metrics=result.metrics,
        permission_decisions=result.permission_decisions,
        trust=result.trust,
        profile=result.profile,
    )
    print(f"SpecGate resume finished: passed={result.passed}, steps={result.steps}")
    return 0 if result.passed else 1


def run_real_llm(
    root: Path,
    provider: str,
    model: str,
    base_url: str,
    max_steps: int,
    user_agent: str,
    timeout: float,
    governance_profile: str | None = None,
) -> int:
    status = credential_status(provider)
    if not status.safe_to_run:
        print(status.message)
        return 1
    if provider != "openai-compatible":
        print(f"{provider} is configured, but SpecGate run currently supports openai-compatible only")
        return 1
    api_key = read_credential(provider)
    if not api_key:
        print(f"{provider} credential is not configured")
        return 1

    llm = OpenAICompatibleLLM(
        base_url=base_url,
        api_key=api_key,
        model=model,
        user_agent=user_agent,
        timeout=timeout,
    )
    settings = _load_workspace_settings(root)
    try:
        result = AgentRunner(
            root,
            llm,
            settings.policy,
            max_steps=max_steps,
            governance_profile=governance_profile,
            governance_config=settings.governance,
        ).run()
    except LLMProviderError as exc:
        print(f"provider request failed: {redact(str(exc))}")
        return 1
    gate = result.final_gate or run_html_gate(root / "index.html", root / "CHECKLIST.md")
    generate_report(
        root,
        gate,
        result.steps,
        metrics=result.metrics,
        permission_decisions=result.permission_decisions,
        trust=result.trust,
        profile=result.profile,
    )
    print(f"SpecGate run finished: passed={result.passed}, steps={result.steps}")
    return 0 if result.passed else 1


def run_real_eval(
    root: Path,
    strategy: str,
    provider: str,
    model: str | None,
    base_url: str | None,
    max_steps: int,
    user_agent: str,
    timeout: float,
    save_workspaces: bool = False,
    governance_profile: str | None = None,
    suite: str | None = None,
) -> int:
    if not model:
        print("--model is required when --provider is used")
        return 1
    if not base_url:
        print("--base-url is required when --provider is used")
        return 1
    status = credential_status(provider)
    if not status.safe_to_run:
        print(status.message)
        return 1
    if provider != "openai-compatible":
        print(f"{provider} is configured, but SpecGate eval currently supports openai-compatible only")
        return 1
    api_key = read_credential(provider)
    if not api_key:
        print(f"{provider} credential is not configured")
        return 1

    def llm_factory(_case):
        return OpenAICompatibleLLM(
            base_url=base_url,
            api_key=api_key,
            model=model,
            user_agent=user_agent,
            timeout=timeout,
        )

    try:
        suite = run_eval_suite(
            root,
            strategy=strategy,
            llm_factory=llm_factory,
            max_steps=max_steps,
            save_workspaces=save_workspaces,
            governance_profile=governance_profile,
            suite=suite,
        )
    except LLMProviderError as exc:
        print(f"provider request failed: {redact(str(exc))}")
        return 1
    if suite.total_cases == 0:
        print(f"SpecGate eval found no cases: {root}")
        return 1
    print(
        "SpecGate eval finished: "
        f"strategy={suite.strategy}, "
        f"cases={suite.total_cases}, "
        f"passed={suite.passed_cases}, "
        f"expected_matches={suite.expected_matches}"
    )
    return 0 if suite.expected_matches == suite.total_cases and suite.total_cases > 0 else 1


def run_benchmark(
    root: Path,
    strategies: list[str],
    governance_profile: str | None = None,
    suite: str | None = None,
) -> int:
    suites = []
    output_dir = root / "eval-runs" / "latest"
    for strategy in strategies:
        suite_result = run_eval_suite(
            root,
            strategy=strategy,
            governance_profile=governance_profile,
            suite=suite,
        )
        suites.append(suite_result)
        results_path = output_dir / "results.json"
        if results_path.exists():
            strategy_results_path = output_dir / f"results-{strategy}.json"
            strategy_results_path.write_text(results_path.read_text(encoding="utf-8"), encoding="utf-8")
    if not suites or any(suite.total_cases == 0 for suite in suites):
        print(f"SpecGate benchmark found no cases: {root}")
        return 1
    benchmark = summarize_benchmark(suites)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark.json").write_text(
        json.dumps(benchmark.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "SpecGate benchmark finished: "
        f"strategies={len(strategies)}, "
        f"cases={suites[0].total_cases}"
    )
    return 0 if all(suite.expected_matches == suite.total_cases for suite in suites) else 1


def configure_user() -> int:
    path = user_config_path()
    try:
        current = load_user_llm_config(path=path)
    except UserConfigError:
        print(
            f"user config is invalid: {path}; "
            "remove it and run: specgate configure"
        )
        return 1

    base_default = current.base_url if current else ""
    model_default = current.model if current else ""
    base_prompt = (
        f"Base URL [{base_default}]: " if base_default else "Base URL: "
    )
    model_prompt = f"Model [{model_default}]: " if model_default else "Model: "
    base_url = input(base_prompt).strip() or base_default
    model = input(model_prompt).strip() or model_default
    if not base_url or not model:
        print("Base URL and Model are required")
        return 1

    status = credential_status("openai-compatible")
    prompt = (
        "API key [configured; press Enter to keep]: "
        if status.safe_to_run
        else "API key: "
    )
    secret = getpass.getpass(prompt)
    if secret:
        try:
            set_credential("openai-compatible", secret)
        except CredentialStoreUnavailable:
            print(
                "credential store is unavailable; "
                "set OPENAI_COMPATIBLE_API_KEY instead"
            )
            return 1
        except ValueError:
            print("API key is invalid")
            return 1
    elif not status.safe_to_run:
        print(
            "API key is required; alternatively set "
            "OPENAI_COMPATIBLE_API_KEY"
        )
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="specgate")
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("run-mock-demo")
    demo.add_argument("workspace")
    demo.add_argument("--governance-profile", choices=GOVERNANCE_PROFILES, default=None)
    real_run = sub.add_parser("run")
    real_run.add_argument("workspace")
    real_run.add_argument("--provider", default="openai-compatible")
    real_run.add_argument("--model", required=True)
    real_run.add_argument("--base-url", required=True)
    real_run.add_argument("--max-steps", type=int, default=5)
    real_run.add_argument("--user-agent", default="SpecGate/0.1 OpenAI-Compatible")
    real_run.add_argument("--timeout", type=float, default=60)
    real_run.add_argument("--governance-profile", choices=GOVERNANCE_PROFILES, default=None)
    resume = sub.add_parser("resume")
    resume.add_argument("workspace")
    resume.add_argument("--max-steps", type=int, default=5)
    resume.add_argument("--governance-profile", choices=GOVERNANCE_PROFILES, default=None)
    eval_parser = sub.add_parser("eval")
    eval_parser.add_argument("cases_root")
    eval_parser.add_argument(
        "--context-strategy",
        choices=sorted(VALID_CONTEXT_STRATEGIES),
        default="baseline",
    )
    eval_parser.add_argument("--provider")
    eval_parser.add_argument("--model")
    eval_parser.add_argument("--base-url")
    eval_parser.add_argument("--max-steps", type=int, default=5)
    eval_parser.add_argument("--user-agent", default="SpecGate/0.1 OpenAI-Compatible")
    eval_parser.add_argument("--timeout", type=float, default=60)
    eval_parser.add_argument("--save-workspaces", action="store_true")
    eval_parser.add_argument("--governance-profile", choices=GOVERNANCE_PROFILES, default=None)
    eval_parser.add_argument("--suite")
    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("cases_root")
    benchmark.add_argument(
        "--strategies",
        nargs="+",
        choices=sorted(VALID_CONTEXT_STRATEGIES),
        default=["baseline", "rag-select", "compressed-rag", "isolated-harness"],
    )
    benchmark.add_argument("--governance-profile", choices=GOVERNANCE_PROFILES, default=None)
    benchmark.add_argument("--suite")
    sub.add_parser(
        "configure",
        help="保存默认 Base URL、Model 和隐藏的 API key",
    )
    credentials = sub.add_parser("credentials")
    credentials_sub = credentials.add_subparsers(dest="credentials_command", required=True)
    for command in ("status", "clear"):
        item = credentials_sub.add_parser(command)
        item.add_argument("provider")
    set_parser = credentials_sub.add_parser("set")
    set_parser.add_argument("provider")
    set_parser.add_argument(
        "--value",
        help="自动化输入；凭据可能留在命令行历史中，日常使用请省略此参数",
    )
    approvals = sub.add_parser("approvals")
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_list = approvals_sub.add_parser("list")
    approvals_list.add_argument("workspace")
    approvals_approve = approvals_sub.add_parser("approve")
    approvals_approve.add_argument("workspace")
    approvals_approve.add_argument("approval_id")
    approvals_deny = approvals_sub.add_parser("deny")
    approvals_deny.add_argument("workspace")
    approvals_deny.add_argument("approval_id")
    approvals_deny.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.command == "configure":
        return configure_user()
    if args.command == "run-mock-demo":
        return run_mock_demo(Path(args.workspace), governance_profile=args.governance_profile)
    if args.command == "run":
        return run_real_llm(
            root=Path(args.workspace),
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            max_steps=args.max_steps,
            user_agent=args.user_agent,
            timeout=args.timeout,
            governance_profile=args.governance_profile,
        )
    if args.command == "resume":
        return run_resume(
            Path(args.workspace),
            max_steps=args.max_steps,
            governance_profile=args.governance_profile,
        )
    if args.command == "eval":
        if args.provider:
            return run_real_eval(
                root=Path(args.cases_root),
                strategy=args.context_strategy,
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                max_steps=args.max_steps,
                user_agent=args.user_agent,
                timeout=args.timeout,
                save_workspaces=args.save_workspaces,
                governance_profile=args.governance_profile,
                suite=args.suite,
            )
        suite = run_eval_suite(
            Path(args.cases_root),
            strategy=args.context_strategy,
            save_workspaces=args.save_workspaces,
            governance_profile=args.governance_profile,
            suite=args.suite,
        )
        if suite.total_cases == 0:
            print(f"SpecGate eval found no cases: {args.cases_root}")
            return 1
        print(
            "SpecGate eval finished: "
            f"strategy={suite.strategy}, "
            f"cases={suite.total_cases}, "
            f"passed={suite.passed_cases}, "
            f"expected_matches={suite.expected_matches}"
        )
        return 0 if suite.expected_matches == suite.total_cases and suite.total_cases > 0 else 1
    if args.command == "benchmark":
        return run_benchmark(
            Path(args.cases_root),
            strategies=args.strategies,
            governance_profile=args.governance_profile,
            suite=args.suite,
        )
    if args.command == "credentials":
        if args.credentials_command == "status":
            status = credential_status(args.provider)
            print(status.message)
            return 0 if status.safe_to_run else 1
        if args.credentials_command == "set":
            secret = args.value if args.value is not None else getpass.getpass("API key: ")
            set_credential(args.provider, secret)
            print(
                f"{args.provider} credential saved to system keyring; "
                "secret value hidden"
            )
            return 0
        if args.credentials_command == "clear":
            clear_credential(args.provider)
            status = credential_status(args.provider)
            print(
                f"{args.provider} keyring credential cleared; "
                f"effective source={status.source}"
            )
            return 0
    if args.command == "approvals":
        if args.approvals_command == "list":
            return list_approvals(Path(args.workspace))
        if args.approvals_command == "approve":
            return update_approval(Path(args.workspace), args.approval_id, "approve")
        if args.approvals_command == "deny":
            return update_approval(Path(args.workspace), args.approval_id, "deny", reason=args.reason)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
