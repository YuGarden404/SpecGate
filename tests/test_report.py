import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
