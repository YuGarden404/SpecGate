import tempfile
import unittest
import json
from pathlib import Path

from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path
from specgate.gate import GateCheck, GateResult
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary
from specgate.report import generate_report


class ReportTests(unittest.TestCase):
    def test_generate_static_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate 通过")
            trace_path = root / "runs" / "latest" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                '{"event_type":"llm_response","payload":{"step":1,"text":"{}"}}\n'
                '{"event_type":"tool_result","payload":{"step":1,"result":{"blocked":false}}}\n',
                encoding="utf-8",
            )
            (root / "memory.json").write_text(
                '{"runs":[{"passed":true,"steps":3,"gate_summary":"remembered layout"}]}',
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=3)

            self.assertTrue(output.exists())
            html = output.read_text(encoding="utf-8")
            self.assertIn("SpecGate Run Report", html)
            self.assertIn("Gate 通过", html)
            self.assertIn("3", html)
            self.assertIn("Tools", html)
            self.assertIn("write_file", html)
            self.assertIn("finish", html)
            self.assertIn("Run Events", html)
            self.assertIn("llm_response", html)
            self.assertIn("tool_result", html)
            self.assertIn("Memory Summary", html)
            self.assertIn("remembered layout", html)

    def test_generate_report_includes_governance_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            metrics = RunMetrics(
                steps=2,
                llm_calls=2,
                tool_calls=1,
                successful_tool_calls=0,
                blocked_actions=1,
                finish_actions=1,
            )
            decisions = [
                PermissionDecision(
                    step=2,
                    action="write_file",
                    path="<script>evil_path()</script>",
                    allowed=False,
                    blocked=True,
                    reason="write path not allowed: <script>evil_reason()</script>",
                    profile="<script>alert(1)</script>",
                    rule_family="allowlist",
                )
            ]
            trust = TrustSummary(
                "<img src=x onerror=alert(1)>",
                ["blocked_actions_present", "<img src=x onerror=alert(1)>"],
            )

            output = generate_report(
                root,
                gate,
                steps="<script>alert(2)</script>",  # type: ignore[arg-type]
                metrics=metrics,
                permission_decisions=decisions,
                trust=trust,
                profile="<script>alert(1)</script>",
            )

            html = output.read_text(encoding="utf-8")
            self.assertIn("Trust Summary", html)
            self.assertIn("blocked_actions_present", html)
            self.assertIn("Run Metrics", html)
            self.assertIn("llm_calls", html)
            self.assertIn("Permission Decisions", html)
            self.assertIn("&lt;script&gt;alert(2)&lt;/script&gt;", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)
            self.assertIn("write path not allowed: &lt;script&gt;evil_reason()&lt;/script&gt;", html)
            self.assertIn("&lt;script&gt;evil_path()&lt;/script&gt;", html)
            self.assertNotIn("<script>", html)
            self.assertNotIn("<img src=x onerror=alert(1)>", html)

    def test_generate_report_includes_approval_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-123",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="needs review <script>alert(1)</script>",
                        profile="review",
                        status="denied",
                        decision_reason="too broad <script>alert(2)</script>",
                        action_payload={"args": {"content": "secret sk-test-secret-1234567890"}},
                    )
                ]
            ).write(approval_queue_path(root))

            output = generate_report(root, gate, 1, profile="review")

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("approval-123", html)
            self.assertIn("denied", html)
            self.assertIn("replace_file", html)
            self.assertIn("README.md", html)
            self.assertIn("needs review &lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertIn("too broad &lt;script&gt;alert(2)&lt;/script&gt;", html)
            self.assertIn("Decision Reason", html)
            self.assertNotIn("action_payload", html)
            self.assertNotIn("sk-test-secret", html)
            self.assertNotIn("<script>", html)

    def test_generate_report_redacts_approval_history_text_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-secret-reason",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="review contains sk-test-secret-1234567890",
                        profile="review",
                        status="denied",
                        decision_reason="denied because sk-test-secret-0987654321",
                    )
                ]
            ).write(approval_queue_path(root))

            output = generate_report(root, gate, 1, profile="review")

            html = output.read_text(encoding="utf-8")
            self.assertIn("approval-secret-reason", html)
            self.assertIn("denied", html)
            self.assertIn("replace_file", html)
            self.assertIn("README.md", html)
            self.assertNotIn("sk-test-secret", html)

    def test_generate_report_strips_action_payload_from_run_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            trace_path = root / "runs" / "latest" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                json.dumps(
                    {
                        "event_type": "approval_requested",
                        "payload": {
                            "approval": {
                                "id": "approval-step-1",
                                "status": "pending",
                                "action": "replace_file",
                                "path": "README.md",
                                "reason": "requires human review",
                                "action_payload": {
                                    "args": {"content": "secret sk-test-secret-1234567890"}
                                },
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("approval_requested", html)
            self.assertIn("approval-step-1", html)
            self.assertIn("replace_file", html)
            self.assertIn("pending", html)
            self.assertNotIn("action_payload", html)
            self.assertNotIn("sk-test-secret", html)

    def test_generate_report_does_not_render_malformed_trace_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            trace_path = root / "runs" / "latest" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(
                '{"event_type": "approval_requested", "payload": {"action_payload": '
                '{"args": {"content": "secret sk-test-secret-1234567890"}}}\n',
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("malformed trace event", html)
            self.assertNotIn("invalid_trace_line", html)
            self.assertNotIn("action_payload", html)
            self.assertNotIn("sk-test-secret", html)

    def test_generate_report_includes_retrieval_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
            (run_dir / "retrieval.json").write_text(
                json.dumps(
                    {
                        "query_terms": ["python", "gate"],
                        "candidate_count": 8,
                        "selected_chunks": [
                            {
                                "path": "notes<script>.md",
                                "start_line": 1,
                                "end_line": 3,
                                "score": 2.0,
                                "matched_terms": ["python", "gate"],
                                "reason": "matched terms: <script>alert(1)</script>",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Retrieval Evidence", html)
            self.assertIn("notes&lt;script&gt;.md", html)
            self.assertIn("python, gate", html)
            self.assertIn("matched terms: &lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("notes<script>.md", html)

    def test_generate_report_handles_malformed_retrieval_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "retrieval.json").write_text(
                '{"selected_chunks": [<script>alert(1)</script>]}',
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Retrieval Evidence", html)
            self.assertIn("could not read retrieval evidence", html)
            self.assertNotIn("<script>alert(1)</script>", html)

    def test_generate_report_includes_compression_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "compression.json").write_text(
                json.dumps(
                    {
                        "original_chars": 5000,
                        "compressed_chars": 400,
                        "cleared_tool_results": 1,
                        "summarized_events": 2,
                        "pinned_sections": ["Task Constraints", "<script>alert(1)</script>"],
                        "dropped_sections": [],
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Compression Evidence", html)
            self.assertIn("cleared_tool_results", html)
            self.assertIn("Task Constraints", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)

    def test_generate_report_includes_role_isolation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "isolation.json").write_text(
                json.dumps(
                    {
                        "roles": [
                            {
                                "role": "reviewer<script>",
                                "visible_sections": ["Final Artifact"],
                                "hidden_sections": ["draft_patch"],
                                "allowed_actions": ["read_file", "finish"],
                                "state_keys": ["task", "review_notes"],
                            }
                        ],
                        "role_contexts": 1,
                        "isolated_state_keys": 2,
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Role Isolation Evidence", html)
            self.assertIn("reviewer&lt;script&gt;", html)
            self.assertIn("draft_patch", html)
            self.assertNotIn("reviewer<script>", html)

    def test_generate_report_includes_role_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(False, [GateCheck("doctype", False, "failed")], [], "Gate failed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "isolation.json").write_text(
                json.dumps(
                    {
                        "strategy": "multi-agent-isolated",
                        "role_runs": 1,
                        "role_blocked_actions": 1,
                        "review_repairs": 0,
                        "executions": [
                            {
                                "role": "planner",
                                "phase": "plan",
                                "context_chars": 100,
                                "visible_sections": ["Task"],
                                "allowed_actions": ["finish"],
                                "attempted_action": "write_file",
                                "action_allowed_by_role": False,
                                "blocked_reason": "role planner cannot perform write_file",
                                "summary": "<script>alert(1)</script>",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Role Execution Evidence", html)
            self.assertIn("planner", html)
            self.assertIn("write_file", html)
            self.assertIn("role planner cannot perform write_file", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_generate_report_includes_prompt_injection_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            (run_dir / "security.json").write_text(
                json.dumps(
                    {
                        "passed": False,
                        "findings": ["blocked_action", "<script>alert(1)</script>"],
                        "failures": ["model revealed sk-test-secret in output"],
                        "must_not_create_violations": 1,
                        "must_not_reveal_violations": 1,
                        "cases": 2,
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Prompt Injection Safety", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertNotIn("sk-test-secret", html)

    def test_generate_report_includes_benchmark_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            benchmark_dir = root / "eval-runs" / "latest"
            benchmark_dir.mkdir(parents=True)
            (benchmark_dir / "benchmark.json").write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "strategy": "rag<script>",
                                "total_cases": 2,
                                "passed_cases": 2,
                                "expected_matches": 2,
                                "avg_context_chars": 1200,
                                "avg_retrieved_chunks": 2.5,
                                "blocked_actions": 0,
                                "effective_blocked_actions": 1,
                                "approval_requests": 0,
                                "parse_errors": 0,
                                "gate_runs": 2,
                                "role_runs": 3,
                                "role_blocked_actions": 1,
                                "review_repairs": 1,
                            },
                            {
                                "strategy": "baseline",
                                "total_cases": 1,
                                "passed_cases": 1,
                                "expected_matches": 1,
                                "avg_context_chars": 500,
                                "avg_retrieved_chunks": 0,
                                "blocked_actions": 0,
                                "effective_blocked_actions": 0,
                                "approval_requests": 0,
                                "parse_errors": 0,
                                "gate_runs": 1,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, steps=1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Benchmark Summary", html)
            self.assertIn("rag&lt;script&gt;", html)
            self.assertIn("2.5", html)
            self.assertIn("Role Runs", html)
            self.assertIn("Role Blocks", html)
            self.assertIn("Review Repairs", html)
            self.assertIn("Effective Blocks", html)
            self.assertIn(">3<", html)
            self.assertIn(">1<", html)
            self.assertIn("<td>baseline</td><td>1</td><td>1</td><td>1</td><td>500</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>1</td><td>0</td><td>0</td><td>0</td>", html)
            self.assertNotIn("rag<script>", html)

    def test_generate_report_handles_missing_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("No approvals recorded", html)

    def test_generate_report_handles_empty_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            ApprovalQueue().write(approval_queue_path(root))

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("No approvals recorded", html)

    def test_generate_report_handles_malformed_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text('{"approvals": [<script>alert(1)</script>]}', encoding="utf-8")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("could not read approval history", html)
            self.assertNotIn("<script>alert(1)</script>", html)

    def test_generate_report_handles_non_object_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text("[]", encoding="utf-8")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("could not read approval history", html)
            self.assertNotIn("[]", html)

    def test_generate_report_handles_non_list_pending_approvals_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text('{"approvals": {}}', encoding="utf-8")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("could not read approval history", html)
            self.assertNotIn('{"approvals": {}}', html)

    def test_generate_report_handles_malformed_pending_approval_field_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(
                json.dumps(
                    {
                        "approvals": [
                            {
                                "id": {"secret": "sk-test-secret-1234567890"},
                                "step": 1,
                                "action": "replace_file",
                                "path": "README.md",
                                "risk_level": "review",
                                "reason": ["sk-test-secret-abcdefghij"],
                                "profile": "review",
                                "status": "pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("could not read approval history", html)
            self.assertNotIn("sk-test-secret", html)

    def test_generate_report_redacts_malformed_approval_history_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(
                json.dumps(
                    {
                        "approvals": [
                            {
                                "id": "approval-123",
                                "step": 1,
                                "action": "replace_file",
                                "path": "README.md",
                                "risk_level": "review",
                                "reason": "needs review",
                                "profile": "review",
                                "status": "pending",
                                "decision_reason": {"secret": "sk-test-secret-1234567890"},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Approval History", html)
            self.assertIn("could not read approval history", html)
            self.assertNotIn("sk-test-secret", html)


if __name__ == "__main__":
    unittest.main()
