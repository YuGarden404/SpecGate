import json
import tempfile
import unittest
from pathlib import Path

from specgate.runtime_events import (
    FanoutRunEventSink,
    InMemoryRunEventSink,
    NullRunEventSink,
    RunEventContext,
    TraceRunEventSink,
)
from specgate.trace import TraceStore
from tests.shell_support import FailingSink, RecordingSink


class RuntimeEventTests(unittest.TestCase):
    def setUp(self):
        self.context = RunEventContext("run-1", "agent-1", "parent-1")

    def test_in_memory_sink_adds_identity_fixed_time_and_redacts_payload(self):
        sink = InMemoryRunEventSink(clock=lambda: "2026-07-29T00:00:00Z")

        sink.emit(
            self.context,
            "ToolCompleted",
            {
                "token": "sk-secret-1234567890",
                "items": ("sk-tuple-secret-1234567890",),
            },
            step=2,
            phase="tool",
        )

        event = sink.events[0]
        self.assertEqual(event.run_id, "run-1")
        self.assertEqual(event.agent_run_id, "agent-1")
        self.assertEqual(event.parent_run_id, "parent-1")
        self.assertEqual(event.step, 2)
        self.assertEqual(event.phase, "tool")
        self.assertEqual(event.event_type, "ToolCompleted")
        self.assertEqual(event.timestamp, "2026-07-29T00:00:00Z")
        self.assertNotIn("sk-secret", str(event.payload))
        self.assertNotIn("sk-tuple-secret", str(event.payload))
        self.assertIn("[REDACTED]", str(event.payload))

    def test_in_memory_sink_owns_input_and_output_snapshots(self):
        sink = InMemoryRunEventSink(clock=lambda: "fixed")
        payload = {"nested": {"value": "original"}}

        sink.emit(self.context, "Event", payload)
        payload["nested"]["value"] = "changed-input"
        first_snapshot = sink.events
        first_snapshot[0].payload["nested"]["value"] = "changed-output"

        self.assertEqual(
            sink.events[0].payload["nested"]["value"],
            "original",
        )

    def test_fanout_redacts_and_observer_failure_does_not_block_primary(self):
        primary = RecordingSink()
        observer = FailingSink()
        errors = []
        sink = FanoutRunEventSink(primary, (observer,), errors.append)

        sink.emit(
            self.context,
            "ToolCompleted",
            {"token": "sk-secret-1234567890"},
        )

        self.assertEqual(len(primary.events), 1)
        self.assertNotIn("sk-secret", str(primary.events[0]))
        self.assertIn("[REDACTED]", str(primary.events[0]))
        self.assertEqual(len(errors), 1)

    def test_fanout_gives_each_sink_an_independent_payload_snapshot(self):
        class MutatingSink:
            def emit(
                self,
                context,
                event_type,
                payload,
                *,
                step=0,
                phase="runtime",
            ):
                del context, event_type, step, phase
                payload["nested"]["value"] = "observer mutation"

        primary = RecordingSink()
        sink = FanoutRunEventSink(primary, (MutatingSink(),))
        payload = {"nested": {"value": "original"}}

        sink.emit(self.context, "Event", payload)

        self.assertEqual(payload["nested"]["value"], "original")
        self.assertEqual(primary.events[0][2]["nested"]["value"], "original")

    def test_null_sink_accepts_events_without_side_effects(self):
        NullRunEventSink().emit(
            self.context,
            "Event",
            {"token": "sk-secret-1234567890"},
            step=2,
            phase="test",
        )

    def test_trace_sink_maps_unified_event_and_uses_trace_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trace.jsonl"
            trace = TraceStore(
                path,
                clock=lambda: "2026-07-29T01:02:03Z",
            )
            sink = TraceRunEventSink(trace)

            sink.emit(
                self.context,
                "GateCompleted",
                {"message": "key sk-secret-1234567890"},
                step=3,
                phase="gate",
            )

            record = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(record["timestamp"], "2026-07-29T01:02:03Z")
        self.assertEqual(record["event_type"], "GateCompleted")
        self.assertEqual(record["payload"]["run_id"], "run-1")
        self.assertEqual(record["payload"]["agent_run_id"], "agent-1")
        self.assertEqual(record["payload"]["parent_run_id"], "parent-1")
        self.assertEqual(record["payload"]["step"], 3)
        self.assertEqual(record["payload"]["phase"], "gate")
        self.assertNotIn("sk-secret", str(record))


if __name__ == "__main__":
    unittest.main()
