from __future__ import annotations

import argparse
from pathlib import Path

from specgate.gate import run_html_gate
from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.report import generate_report
from specgate.runner import AgentRunner


def _fixed_demo_html() -> str:
    nodes = "".join(
        f'<section class="node" data-related="rel{i}"><h2>Node {i}</h2><p>Spec Gate Checklist 定义 {i}</p></section>'
        for i in range(10)
    )
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
        "<title>AI for Coding Knowledge Navigator</title></head><body><input type=\"search\">"
        f"{nodes}<script>function highlightRelations(){{}} function filterNodes(){{}}</script></body></html>"
    )


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
    policy = WorkspacePolicy(
        root=root,
        allowed_actions={"write_file", "replace_file", "read_file", "list_files", "finish"},
        allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
        allowed_write_paths={"index.html"},
    )
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
