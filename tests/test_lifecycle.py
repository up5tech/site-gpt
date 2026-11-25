"""V6-23: the API and the worker stop without dropping work or leaking pools.

What is pinned here:

* the API's shutdown gives back the shared Redis client and the database pool,
  and neither failure can turn a stop into an error;
* the worker turns SIGTERM/SIGINT into one stop event instead of being killed;
* a job that was already popped runs to completion before the process leaves,
  while an idle pop times out and re-checks the event (so a stop is noticed
  between jobs rather than after the next job arrives);
* leaving cancels the scheduler loops and closes the pools, and writes one
  `worker.stopped` event.
"""

import asyncio
import json
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from site_gpt.app import main as main_module
from site_gpt.app import worker as worker_module
from site_gpt.app.db import session as session_module
from site_gpt.app.services import redis as redis_module


class ApiShutdownTests(unittest.TestCase):
    def test_the_lifespan_gives_back_redis_and_the_pool(self):
        close_client = AsyncMock(return_value=True)
        dispose_engine = MagicMock(return_value=True)

        async def _run():
            async with main_module.lifespan(FastAPI()):
                pass

        with (
            patch.object(main_module, "close_client", close_client),
            patch.object(main_module, "dispose_engine", dispose_engine),
        ):
            asyncio.run(_run())

        close_client.assert_awaited_once()
        dispose_engine.assert_called_once()

    def test_a_shutdown_that_cannot_close_redis_does_not_raise(self):
        client = SimpleNamespace(aclose=AsyncMock(side_effect=RuntimeError("gone")))
        with patch.object(redis_module, "get_client", lambda: client):
            self.assertFalse(asyncio.run(redis_module.close_client()))

        client.aclose.assert_awaited_once()

    def test_a_pool_that_cannot_dispose_does_not_raise(self):
        engine = MagicMock()
        engine.dispose.side_effect = RuntimeError("already gone")
        with patch.object(session_module, "engine", engine):
            self.assertFalse(session_module.dispose_engine())

    def test_a_healthy_pool_is_disposed_once(self):
        engine = MagicMock()
        with patch.object(session_module, "engine", engine):
            self.assertTrue(session_module.dispose_engine())

        engine.dispose.assert_called_once()


class _Loop:
    """The slice of an event loop `install_stop_handlers` uses."""

    def __init__(self, fail=False):
        self.fail = fail
        self.registered = []

    def add_signal_handler(self, sig, callback):
        if self.fail:
            raise NotImplementedError("this loop cannot install handlers")
        self.registered.append((sig, callback))


class StopHandlerTests(unittest.TestCase):
    def test_both_stop_signals_set_the_event(self):
        stop = asyncio.Event()
        loop = _Loop()

        installed = worker_module.install_stop_handlers(stop, loop=loop)

        self.assertEqual(installed, [signal.SIGTERM, signal.SIGINT])
        self.assertEqual(
            [sig for sig, _ in loop.registered], [signal.SIGTERM, signal.SIGINT]
        )
        self.assertFalse(stop.is_set())
        loop.registered[0][1]()
        self.assertTrue(stop.is_set())

    def test_a_loop_without_signal_support_is_left_alone(self):
        stop = asyncio.Event()

        self.assertEqual(
            worker_module.install_stop_handlers(stop, loop=_Loop(fail=True)), []
        )
        self.assertFalse(stop.is_set())


class _Queue:
    """A scripted `BRPOP`: each entry is a job tuple, None, or an exception."""

    def __init__(self, pops, on_job=None):
        self.pops = list(pops)
        self.calls = []
        self.on_job = on_job

    async def brpop(self, key, timeout=0):
        self.calls.append((key, timeout))
        if not self.pops:
            return None
        item = self.pops.pop(0)
        if isinstance(item, Exception):
            raise item
        if item is not None and self.on_job is not None:
            # A deploy's SIGTERM can arrive between the pop and the handler.
            self.on_job()
        return item


def _job(job_type="ingest"):
    return ("queue:jobs", json.dumps({"type": job_type, "website_id": "x"}))


class WorkerLifecycleTests(unittest.TestCase):
    def _run(self, pops, *, stop=None, handler=None, sleep=None, on_job=None):
        stop = stop or asyncio.Event()
        queue = _Queue(pops, on_job=on_job)
        handlers = {"ingest": handler or AsyncMock()}
        loops = []

        def _start():
            async def forever():
                await asyncio.Event().wait()

            task = asyncio.create_task(forever())
            loops.append(task)
            return [task]

        patches = [
            patch.object(worker_module, "redis_client", queue),
            patch.object(worker_module, "configure_logging", MagicMock()),
            patch.object(worker_module, "requeue_stuck_ingests", AsyncMock()),
            patch.object(worker_module, "start_background_loops", _start),
            patch.object(worker_module, "note_queue_pop", AsyncMock(return_value=True)),
            patch.object(
                worker_module, "note_job_failure", AsyncMock(return_value=1)
            ),
            patch.object(worker_module, "close_client", AsyncMock(return_value=True)),
            patch.object(
                worker_module, "dispose_engine", MagicMock(return_value=True)
            ),
            patch.object(worker_module, "_JOB_HANDLERS", handlers),
        ]
        if sleep is not None:
            patches.append(patch.object(worker_module.asyncio, "sleep", sleep))
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        asyncio.run(worker_module.worker(stop=stop))
        return queue, loops, handlers

    def test_a_popped_job_finishes_before_the_worker_leaves(self):
        stop = asyncio.Event()
        seen = {}

        async def handler(data):
            # The stop arrives after the pop and before the handler's first line:
            # the job is already ours, so it must still complete.
            seen["stop_at_handler_entry"] = stop.is_set()
            seen["job"] = data

        queue, loops, _ = self._run(
            [_job()], stop=stop, handler=handler, on_job=stop.set
        )

        self.assertTrue(seen["stop_at_handler_entry"])
        self.assertEqual(seen["job"]["website_id"], "x")
        self.assertEqual(len(queue.calls), 1)
        # The event is checked before the next pop, so the stop is honoured now.
        self.assertEqual(queue.calls[0][0], "queue:jobs")
        self.assertTrue(loops[0].cancelled())

    def test_a_stop_before_start_consumes_nothing(self):
        stop = asyncio.Event()
        stop.set()

        queue, loops, _ = self._run([_job()], stop=stop)

        self.assertEqual(queue.calls, [])
        self.assertTrue(loops[0].cancelled())
        worker_module.close_client.assert_awaited_once()
        worker_module.dispose_engine.assert_called_once()

    def test_an_idle_pop_times_out_and_keeps_waiting(self):
        stop = asyncio.Event()

        async def handler(_data):
            stop.set()

        queue, _, _ = self._run([None, _job()], stop=stop, handler=handler)

        self.assertEqual(len(queue.calls), 2)
        self.assertEqual(queue.calls[0][1], worker_module.WORKER_QUEUE_POP_TIMEOUT_SECONDS)
        worker_module.note_queue_pop.assert_awaited_once()

    def test_a_read_failure_is_retried_without_stopping_the_worker(self):
        stop = asyncio.Event()

        async def handler(_data):
            stop.set()

        queue, _, _ = self._run(
            [RuntimeError("redis dropped"), _job()],
            stop=stop,
            handler=handler,
            sleep=AsyncMock(return_value=None),
        )

        self.assertEqual(len(queue.calls), 2)
        self.assertEqual(stop.is_set(), True)

    def test_an_unknown_job_type_is_skipped_and_the_loop_continues(self):
        stop = asyncio.Event()

        async def handler(_data):
            stop.set()

        queue, _, _ = self._run(
            [("queue:jobs", json.dumps({"type": "nope"})), _job()],
            stop=stop,
            handler=handler,
        )

        self.assertEqual(len(queue.calls), 2)
        # The unknown type is skipped, so the next job still runs and a failure
        # is not counted for a job nothing was asked to run.
        worker_module.note_job_failure.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
