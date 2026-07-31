import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Barrier

import specgate.workspace_fs as workspace_fs
from specgate.gate import GateCheck, GateIssue, GateResult
from specgate.metrics import RunMetrics
from specgate.run_state import (
    InMemoryRunStateStore,
    FileRunStateStore,
    Observation,
    RunState,
    RunStateConflict,
    RunStateFormatError,
    RunStateSerializationError,
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


class FileRunStateStoreTests(unittest.TestCase):
    def test_duplicate_create_checks_identity_before_serializing_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = FileRunStateStore(root)
            original = store.create(RunState("run-1", step=1))

            with self.assertRaises(RunStateConflict):
                store.create(
                    RunState(
                        "run-1",
                        observations=(
                            Observation("tool", {"callback": lambda: None}),
                        ),
                    )
                )

            self.assertEqual(store.get("run-1"), original)

    def test_round_trips_all_explicit_state_fields(self):
        gate = GateResult(
            False,
            [GateCheck("html", False, "missing html")],
            [GateIssue("html", "error", "missing", "none", "add html")],
            "repair",
            artifact_sha256="artifact",
            checklist_sha256="checklist",
        )
        state = RunState(
            "run-1",
            status=RunStatus.NEEDS_APPROVAL,
            step=3,
            observations=(Observation("tool_result", {"ok": True}),),
            latest_gate=gate,
            pending_approval_id="approval-1",
            finish_requested=True,
            metrics=RunMetrics(steps=3, llm_calls=2, gate_failures=1),
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = FileRunStateStore(Path(tmp))

            created = store.create(state)
            loaded = FileRunStateStore(Path(tmp)).get("run-1")

        self.assertEqual(created, state)
        self.assertEqual(loaded, state)

    def test_persistence_redacts_secrets_and_rejects_callables(self):
        secret = "sk-state-secret-1234567890"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = FileRunStateStore(root)
            created = store.create(
                RunState(
                    "run-1",
                    observations=(Observation("tool", {"token": secret}),),
                )
            )
            raw = (root / "state.json").read_text(encoding="utf-8")

            self.assertNotIn(secret, raw)
            self.assertNotIn(secret, repr(created))
            self.assertIn("[REDACTED]", raw)

        with tempfile.TemporaryDirectory() as tmp:
            store = FileRunStateStore(Path(tmp))
            with self.assertRaises(RunStateSerializationError):
                store.create(
                    RunState(
                        "run-2",
                        observations=(
                            Observation("tool", {"callback": lambda: None}),
                        ),
                    )
                )
            self.assertFalse((Path(tmp) / "state.json").exists())

    def test_unknown_schema_and_invalid_field_types_fail_closed(self):
        cases = (
            {"schema_version": "999"},
            {
                "schema_version": "1",
                "run_id": "run-1",
                "revision": 0,
                "status": "running",
                "step": True,
                "observations": [],
                "latest_gate": None,
                "pending_approval_id": None,
                "finish_requested": False,
                "metrics": RunMetrics().to_dict(),
            },
        )
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                workspace_fs.write_workspace_text(
                    root,
                    "state.json",
                    json.dumps(payload),
                    encoding="utf-8",
                )

                with self.assertRaises(RunStateFormatError):
                    FileRunStateStore(root).get("run-1")

    def test_invalid_utf8_fails_with_domain_format_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace_fs.write_workspace_bytes(
                root,
                "state.json",
                b"\xff\xfe\xfd",
            )

            with self.assertRaises(RunStateFormatError):
                FileRunStateStore(root).get("run-1")

    def test_two_store_instances_allow_only_one_cas_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            FileRunStateStore(root).create(RunState("run-1"))
            stores = (FileRunStateStore(root), FileRunStateStore(root))
            barrier = Barrier(2)

            def apply_step(item):
                store, step = item
                barrier.wait()
                try:
                    return store.apply("run-1", 0, StateDelta(step=step))
                except RunStateConflict as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(apply_step, zip(stores, (1, 2))))

            updates = [item for item in results if isinstance(item, RunState)]
            conflicts = [
                item for item in results if isinstance(item, RunStateConflict)
            ]
            self.assertEqual(len(updates), 1)
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(FileRunStateStore(root).get("run-1").revision, 1)


if __name__ == "__main__":
    unittest.main()
