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

    def test_generate_report_includes_pending_approvals(self):
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
                    )
                ]
            ).write(approval_queue_path(root))

            output = generate_report(root, gate, 1, profile="review")

            html = output.read_text(encoding="utf-8")
            self.assertIn("Pending Approvals", html)
            self.assertIn("approval-123", html)
            self.assertIn("replace_file", html)
            self.assertIn("README.md", html)
            self.assertIn("needs review &lt;script&gt;alert(1)&lt;/script&gt;", html)
            self.assertNotIn("<script>", html)

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

    def test_generate_report_handles_missing_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Pending Approvals", html)
            self.assertIn("No pending approvals", html)

    def test_generate_report_handles_empty_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            ApprovalQueue().write(approval_queue_path(root))

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Pending Approvals", html)
            self.assertIn("No pending approvals", html)

    def test_generate_report_handles_malformed_pending_approvals_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text('{"approvals": [<script>alert(1)</script>]}', encoding="utf-8")

            output = generate_report(root, gate, 1)

            html = output.read_text(encoding="utf-8")
            self.assertIn("Pending Approvals", html)
            self.assertIn("could not read pending approvals", html)
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
            self.assertIn("Pending Approvals", html)
            self.assertIn("could not read pending approvals", html)
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
            self.assertIn("Pending Approvals", html)
            self.assertIn("could not read pending approvals", html)
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
            self.assertIn("Pending Approvals", html)
            self.assertIn("could not read pending approvals", html)
            self.assertNotIn("sk-test-secret", html)


if __name__ == "__main__":
    unittest.main()
