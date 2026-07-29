import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

from specgate.gate import GateResult
from specgate.metrics import RunMetrics
from specgate.run_state import (
    InMemoryRunStateStore,
    Observation,
    RunState,
    RunStateConflict,
    RunStatus,
    StateDelta,
)


class RunStateTests(unittest.TestCase):
    def test_run_state_defaults_and_models_are_frozen(self):
        observation = Observation("tool_result", {"ok": True})
        state = RunState(run_id="run-1", observations=(observation,))
        delta = StateDelta(step=1)

        self.assertEqual(state.revision, 0)
        self.assertEqual(state.status, RunStatus.RUNNING)
        self.assertEqual(state.step, 0)
        self.assertIsNone(state.latest_gate)
        self.assertIsNone(state.pending_approval_id)
        self.assertFalse(state.finish_requested)
        self.assertEqual(state.metrics, RunMetrics())
        with self.assertRaises(FrozenInstanceError):
            state.step = 2
        with self.assertRaises(FrozenInstanceError):
            observation.kind = "changed"
        with self.assertRaises(FrozenInstanceError):
            delta.step = 2

    def test_apply_appends_observation_merges_metrics_and_increments_revision(self):
        store = InMemoryRunStateStore()
        store.create(
            RunState(
                run_id="run-1",
                metrics=RunMetrics(steps=2, max_steps_reached=True),
            )
        )
        observation = Observation("tool_result", {"ok": True})

        updated = store.apply(
            "run-1",
            expected_revision=0,
            delta=StateDelta(
                append_observations=(observation,),
                metrics=RunMetrics(steps=3, llm_calls=1),
            ),
        )

        self.assertEqual(updated.revision, 1)
        self.assertEqual(updated.observations, (observation,))
        self.assertEqual(updated.metrics.steps, 5)
        self.assertEqual(updated.metrics.llm_calls, 1)
        self.assertTrue(updated.metrics.max_steps_reached)

    def test_stale_revision_is_rejected_without_mutation(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1"))
        current = store.apply("run-1", 0, StateDelta(step=1))

        with self.assertRaises(RunStateConflict):
            store.apply("run-1", 0, StateDelta(step=2))

        self.assertEqual(store.get("run-1"), current)
        self.assertEqual(store.get("run-1").revision, 1)
        self.assertEqual(store.get("run-1").step, 1)

    def test_create_rejects_duplicate_run_id_without_replacing_state(self):
        store = InMemoryRunStateStore()
        original = store.create(RunState(run_id="run-1", step=1))

        with self.assertRaises(RunStateConflict):
            store.create(RunState(run_id="run-1", step=99))

        self.assertEqual(store.get("run-1"), original)

    def test_store_snapshots_do_not_expose_mutable_state_references(self):
        initial_payload = {"nested": {"ok": True}}
        store = InMemoryRunStateStore()
        created = store.create(
            RunState(
                run_id="run-1",
                observations=(Observation("initial", initial_payload),),
            )
        )

        initial_payload["nested"]["ok"] = False
        created.observations[0].payload["nested"]["ok"] = False

        self.assertTrue(
            store.get("run-1").observations[0].payload["nested"]["ok"]
        )

        appended_payload = {"nested": {"ok": True}}
        updated = store.apply(
            "run-1",
            0,
            StateDelta(
                append_observations=(Observation("appended", appended_payload),),
            ),
        )
        appended_payload["nested"]["ok"] = False
        updated.observations[1].payload["nested"]["ok"] = False

        self.assertTrue(
            store.get("run-1").observations[1].payload["nested"]["ok"]
        )

    def test_apply_can_clear_pending_approval(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1", pending_approval_id="approval-1"))

        updated = store.apply(
            "run-1",
            0,
            StateDelta(clear_pending_approval=True),
        )

        self.assertIsNone(updated.pending_approval_id)

    def test_apply_updates_status_step_finish_gate_and_pending_approval(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1"))
        gate = GateResult(True, [], [], "passed")

        updated = store.apply(
            "run-1",
            0,
            StateDelta(
                status=RunStatus.NEEDS_APPROVAL,
                step=4,
                latest_gate=gate,
                pending_approval_id="approval-1",
                finish_requested=True,
            ),
        )

        self.assertEqual(updated.status, RunStatus.NEEDS_APPROVAL)
        self.assertEqual(updated.step, 4)
        self.assertEqual(updated.latest_gate, gate)
        self.assertEqual(updated.pending_approval_id, "approval-1")
        self.assertTrue(updated.finish_requested)

    def test_concurrent_apply_allows_only_one_cas_update(self):
        store = InMemoryRunStateStore()
        store.create(RunState(run_id="run-1"))
        barrier = Barrier(2)

        def apply_step(step):
            barrier.wait()
            try:
                return store.apply("run-1", 0, StateDelta(step=step))
            except RunStateConflict as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(apply_step, (1, 2)))

        updates = [result for result in results if isinstance(result, RunState)]
        conflicts = [result for result in results if isinstance(result, RunStateConflict)]
        self.assertEqual(len(updates), 1)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(store.get("run-1").revision, 1)
        self.assertIn(store.get("run-1").step, (1, 2))


if __name__ == "__main__":
    unittest.main()
