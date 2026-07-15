import inspect
import threading
import unittest
from datetime import datetime, timezone
from time import monotonic

import specgate.web_runs as web_runs
from specgate.web_runtime import (
    RunCancelled,
    RunControl,
    RunTask,
    RunTimedOut,
    RuntimeCapacityExceeded,
    WebRuntimeConfig,
    WebRuntimeCoordinator,
    load_web_runtime_config,
)


def wait_until(predicate, timeout=1.0):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return True
        threading.Event().wait(0.01)
    return predicate()


class WebRuntimeArchitectureTests(unittest.TestCase):
    def test_web_runs_has_no_per_run_thread_entrypoint(self):
        source = inspect.getsource(web_runs)

        self.assertFalse(hasattr(web_runs, "start_run_background"))
        self.assertNotIn("threading.Thread(", source)


class WebRuntimeConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_documented(self):
        config = load_web_runtime_config({})

        self.assertEqual(config.worker_count, 4)
        self.assertEqual(config.queue_capacity, 32)
        self.assertEqual(config.max_active_runs_per_user, 4)
        self.assertEqual(config.run_timeout_seconds, 60)

    def test_environment_values_override_defaults(self):
        config = load_web_runtime_config(
            {
                "SPECGATE_WEB_WORKERS": "2",
                "SPECGATE_WEB_QUEUE_CAPACITY": "8",
                "SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER": "3",
                "SPECGATE_WEB_RUN_TIMEOUT_SECONDS": "120",
            }
        )

        self.assertEqual(config, WebRuntimeConfig(2, 8, 3, 120))

    def test_invalid_environment_values_fail_closed(self):
        cases = {
            "SPECGATE_WEB_WORKERS": ("", "0", "1.5", "true", "17"),
            "SPECGATE_WEB_QUEUE_CAPACITY": ("", "0", "1.5", "true", "257"),
            "SPECGATE_WEB_MAX_ACTIVE_RUNS_PER_USER": ("", "0", "1.5", "true", "33"),
            "SPECGATE_WEB_RUN_TIMEOUT_SECONDS": ("", "0", "1.5", "true", "3601"),
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        load_web_runtime_config({name: value})

    def test_boolean_is_not_accepted_as_integer_configuration(self):
        with self.assertRaisesRegex(ValueError, "worker_count"):
            WebRuntimeConfig(worker_count=True)

    def test_user_limit_cannot_exceed_total_runtime_capacity(self):
        with self.assertRaisesRegex(ValueError, "max_active_runs_per_user"):
            WebRuntimeConfig(1, 1, 3, 60)


class WebRuntimeCoordinatorTests(unittest.TestCase):
    def make_blocked_runtime(self, release, *, workers, queue_capacity):
        def execute(task, control):
            release.wait(timeout=2)

        runtime = WebRuntimeCoordinator(
            WebRuntimeConfig(
                workers,
                queue_capacity,
                workers + queue_capacity,
                60,
            ),
            execute,
        )
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)
        self.addCleanup(release.set)
        return runtime

    def test_coordinator_bounds_workers_and_pending_queue(self):
        release = threading.Event()
        started = []
        lock = threading.Lock()

        def execute(task, control):
            with lock:
                started.append(task.run_id)
            release.wait(timeout=2)

        runtime = WebRuntimeCoordinator(
            WebRuntimeConfig(2, 3, 5, 60),
            execute,
        )
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)
        self.addCleanup(release.set)
        for run_id in range(1, 6):
            reservation = runtime.reserve()
            reservation.bind(run_id)
            runtime.submit(reservation, RunTask(run_id, 1, False))

        self.assertTrue(wait_until(lambda: runtime.running_count == 2))
        self.assertEqual(runtime.pending_count, 3)
        self.assertEqual(len(started), 2)
        with self.assertRaises(RuntimeCapacityExceeded) as raised:
            runtime.reserve()
        self.assertEqual(raised.exception.scope, "global")
        release.set()

    def test_pending_run_can_be_removed_and_releases_capacity(self):
        release = threading.Event()
        runtime = self.make_blocked_runtime(release, workers=1, queue_capacity=1)
        first = runtime.reserve()
        first.bind(1)
        runtime.submit(first, RunTask(1, 1, False))
        self.assertTrue(wait_until(lambda: runtime.running_count == 1))
        second = runtime.reserve()
        second.bind(2)
        runtime.submit(second, RunTask(2, 1, False))

        self.assertTrue(runtime.discard_pending(2))

        replacement = runtime.reserve()
        replacement.bind(3)
        runtime.submit(replacement, RunTask(3, 1, False))
        self.assertEqual(runtime.pending_run_ids(), (3,))
        release.set()

    def test_bound_reservation_prevents_duplicate_run_submission(self):
        release = threading.Event()
        runtime = self.make_blocked_runtime(release, workers=1, queue_capacity=1)
        first = runtime.reserve()
        first.bind(7)
        runtime.submit(first, RunTask(7, 1, False))
        self.assertTrue(wait_until(lambda: runtime.running_count == 1))
        second = runtime.reserve()
        with self.assertRaisesRegex(ValueError, "already scheduled"):
            second.bind(7)
        second.release()
        release.set()

    def test_worker_survives_task_exception_and_releases_capacity(self):
        completed = threading.Event()

        def execute(task, control):
            if task.run_id == 1:
                raise RuntimeError("boom")
            completed.set()

        runtime = WebRuntimeCoordinator(WebRuntimeConfig(1, 1, 2, 60), execute)
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)
        first = runtime.reserve()
        first.bind(1)
        runtime.submit(first, RunTask(1, 1, False))
        self.assertTrue(wait_until(lambda: runtime.running_count == 0))
        second = runtime.reserve()
        second.bind(2)
        runtime.submit(second, RunTask(2, 1, False))

        self.assertTrue(completed.wait(timeout=1))

    def test_control_prioritizes_user_cancel_over_timeout(self):
        cancelled = threading.Event()
        cancelled.set()
        control = RunControl(
            cancel_event=cancelled,
            deadline_at="2026-07-14T12:00:00+00:00",
            deadline_monotonic=10.0,
            monotonic_clock=lambda: 11.0,
        )

        with self.assertRaises(RunCancelled):
            control.check()

    def test_control_raises_timeout_after_deadline(self):
        control = RunControl(
            cancel_event=threading.Event(),
            deadline_at="2026-07-14T12:00:00+00:00",
            deadline_monotonic=10.0,
            monotonic_clock=lambda: 10.0,
        )

        with self.assertRaises(RunTimedOut):
            control.check()

    def test_deadline_starts_when_worker_claims_task(self):
        observed = []
        started = threading.Event()
        times = iter((100.0, 100.0, 100.0, 100.0))

        def execute(task, control):
            observed.append(control)
            started.set()

        runtime = WebRuntimeCoordinator(
            WebRuntimeConfig(1, 1, 2, 60),
            execute,
            monotonic_clock=lambda: next(times),
            utc_clock=lambda: datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)
        reservation = runtime.reserve()
        reservation.bind(1)
        runtime.submit(reservation, RunTask(1, 1, False))

        self.assertTrue(started.wait(timeout=1))
        self.assertEqual(observed[0].deadline_monotonic, 160.0)
        self.assertEqual(observed[0].deadline_at, "2026-07-14T12:01:00+00:00")

    def test_refill_executes_database_backlog_with_bounded_pending_queue(self):
        remaining = [RunTask(run_id, 1, False) for run_id in range(1, 6)]
        completed = []
        all_completed = threading.Event()
        max_pending = 0

        def execute(task, control):
            nonlocal max_pending
            max_pending = max(max_pending, runtime.pending_count)
            completed.append(task.run_id)
            if len(completed) == 5:
                all_completed.set()

        def provider(scheduled):
            for task in list(remaining):
                if task.run_id not in scheduled:
                    remaining.remove(task)
                    return task
            return None

        runtime = WebRuntimeCoordinator(WebRuntimeConfig(1, 1, 2, 60), execute)
        runtime.set_refill_provider(provider)
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)

        runtime.refill()

        self.assertTrue(all_completed.wait(timeout=2))
        self.assertEqual(completed, [1, 2, 3, 4, 5])
        self.assertLessEqual(max_pending, 1)

    def test_begin_shutdown_clears_pending_and_signals_running(self):
        cancelled = []
        all_cancelled = threading.Event()

        def execute(task, control):
            try:
                while True:
                    control.check()
                    threading.Event().wait(0.01)
            except RunCancelled:
                cancelled.append(task.run_id)
                if len(cancelled) == 2:
                    all_cancelled.set()

        runtime = WebRuntimeCoordinator(WebRuntimeConfig(2, 2, 4, 60), execute)
        runtime.start()
        self.addCleanup(runtime.shutdown, 1.0)
        for run_id in range(1, 5):
            reservation = runtime.reserve()
            reservation.bind(run_id)
            runtime.submit(reservation, RunTask(run_id, 1, False))
        self.assertTrue(wait_until(lambda: runtime.running_count == 2))

        snapshot = runtime.begin_shutdown()

        self.assertEqual(snapshot.pending_run_ids, (3, 4))
        self.assertEqual(set(snapshot.running_run_ids), {1, 2})
        self.assertEqual(runtime.pending_run_ids(), ())
        self.assertTrue(all_cancelled.wait(timeout=1))
        with self.assertRaises(RuntimeCapacityExceeded):
            runtime.reserve()

    def test_join_uses_one_absolute_deadline(self):
        join_timeouts = []

        class UnfinishedThread:
            def join(self, timeout=None):
                join_timeouts.append(timeout)

        times = iter((100.0, 101.0, 104.5))
        runtime = WebRuntimeCoordinator(
            WebRuntimeConfig(2, 1, 3, 60),
            lambda task, control: None,
            monotonic_clock=lambda: next(times),
        )
        runtime._threads = [UnfinishedThread(), UnfinishedThread()]

        runtime.join(5.0)

        self.assertEqual(join_timeouts, [4.0, 0.5])


if __name__ == "__main__":
    unittest.main()
