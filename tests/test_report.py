import tempfile
import unittest
from pathlib import Path

from specgate.gate import GateCheck, GateResult
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


if __name__ == "__main__":
    unittest.main()
