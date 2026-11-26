"""The V6-20 delivery seam: envelope, one claim per job, unchanged failure count.

What is pinned here is the seam only, not a delivery guarantee — D9 is still
UNAPPROVED, so `NullDelivery` must reproduce today's behaviour exactly while the
envelope makes a job identifiable:

* `enqueue_job` mints `job_id` and `attempt` and leaves every producer field and
  the top-level `type` untouched (the payload contract is additive, not
  replaced);
* a job pushed before the seam — or by hand with `redis-cli` — carries no
  envelope and is normalised at pop time, keeping its identity if it already had
  one;
* the consumer claims exactly once per job, completes exactly once when the
  handler returns and fails exactly once when it raises;
* a failure still writes one `worker.job.failed` event and one increment of the
  `ops:worker:job_failures` counter V6-21 alerts on, and an unknown job type
  claims nothing and counts nothing.
"""

import asyncio
import json
import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from site_gpt.app import worker
from site_gpt.app.services import delivery, redis as redis_mod


def _raw_job(payload):
    return ("queue:jobs", json.dumps(payload))


class _Queue:
    """The Redis surface the consumer touches: `brpop`, `set` and `incr`."""

    def __init__(self, pops, on_pop=None):
        self._pops = list(pops)
        self.on_pop = on_pop
        self.calls = []
        self.set = AsyncMock(return_value=True)
        self.incr = AsyncMock(return_value=1)
        self.expire = AsyncMock(return_value=True)

    async def brpop(self, key, timeout=None):
        self.calls.append((key, timeout))
        if not self._pops:
            await asyncio.sleep(0)
            return None
        item = self._pops.pop(0)
        if self.on_pop is not None:
            # Lets a test stop the loop after this pop, once its item is handled.
            self.on_pop()
        if isinstance(item, BaseException):
            raise item
        return item


class _Recorder(delivery.NullDelivery):
    """`NullDelivery`, with the three transitions written down."""

    def __init__(self, client=None, **kwargs):
        super().__init__(client, **kwargs)
        self.claimed = []
        self.completed = []
        self.failed = []

    async def claim(self, job):
        claim = await super().claim(job)
        self.claimed.append(claim)
        return claim

    async def complete(self, claim):
        self.completed.append(claim)
        await super().complete(claim)

    async def fail(self, claim, exc):
        self.failed.append((claim, exc))
        return await super().fail(claim, exc)


def _run_consumer(pops, handlers, stop, *, seam=None, on_pop=None):
    """Drive `worker()` over `pops`; `seam` replaces the delivery implementation."""
    queue = _Queue(pops, on_pop=on_pop)
    with ExitStack() as stack:
        stack.enter_context(patch.object(worker, "redis_client", queue))
        stack.enter_context(patch.object(worker, "configure_logging", MagicMock()))
        stack.enter_context(
            patch.object(worker, "requeue_stuck_ingests", AsyncMock())
        )
        stack.enter_context(patch.object(worker, "start_background_loops", lambda: []))
        stack.enter_context(
            patch.object(worker, "note_queue_pop", AsyncMock(return_value=True))
        )
        stack.enter_context(
            patch.object(worker, "close_client", AsyncMock(return_value=True))
        )
        stack.enter_context(patch.object(worker, "dispose_engine", MagicMock()))
        stack.enter_context(patch.object(worker, "_JOB_HANDLERS", handlers))
        if seam is not None:
            stack.enter_context(patch.object(worker, "NullDelivery", seam))
        asyncio.run(worker.worker(stop=stop))
    return queue


class EnvelopeTests(unittest.TestCase):
    def test_enqueue_job_mints_an_id_and_an_attempt_and_changes_nothing_else(self):
        fake = MagicMock()
        fake.lpush = AsyncMock()
        with patch.object(redis_mod, "redis_client", fake):
            asyncio.run(redis_mod.enqueue_job({"type": "ingest", "website_id": "w1"}))

        key, raw = fake.lpush.call_args.args
        payload = json.loads(raw)
        self.assertEqual(key, "queue:jobs")
        self.assertEqual(payload["type"], "ingest")
        self.assertEqual(payload["website_id"], "w1")
        self.assertEqual(payload["attempt"], 0)
        self.assertEqual(len(str(UUID(payload["job_id"]))), 36)
        self.assertEqual(set(payload), {"type", "website_id", "job_id", "attempt"})

    def test_two_jobs_get_different_ids(self):
        first = delivery.envelope({"type": "digest"})
        second = delivery.envelope({"type": "digest"})
        self.assertNotEqual(first[delivery.JOB_ID_KEY], second[delivery.JOB_ID_KEY])

    def test_a_legacy_payload_is_normalised_at_pop_time(self):
        # No job_id, no attempt: exactly what the gate pushes with redis-cli, and
        # what a job enqueued before this seam looks like.
        job = delivery.envelope({"type": "retention", "company_id": "c1"})

        self.assertEqual(job["type"], "retention")
        self.assertEqual(job["company_id"], "c1")
        self.assertEqual(job["attempt"], 0)
        self.assertTrue(job["job_id"])
        self.assertEqual(delivery.claim_of(job).job_type, "retention")

    def test_an_existing_envelope_is_preserved(self):
        job = {"type": "ingest", "job_id": "abc", "attempt": 2}
        self.assertEqual(
            delivery.envelope(job),
            {"type": "ingest", "job_id": "abc", "attempt": 2},
        )
        self.assertEqual(delivery.claim_of(job).attempt, 2)

    def test_a_malformed_attempt_or_id_is_replaced_not_trusted(self):
        job = delivery.envelope({"type": "ingest", "job_id": "", "attempt": "3"})
        self.assertTrue(job["job_id"])
        self.assertEqual(job["attempt"], 0)
        self.assertEqual(
            delivery.envelope({"type": "ingest", "attempt": -1})["attempt"], 0
        )

    def test_next_attempt_counts_up_without_touching_the_job_id(self):
        claim = delivery.Claim(job_id="abc", attempt=0, job_type="ingest")
        self.assertEqual(delivery.next_attempt(claim).attempt, 1)
        self.assertEqual(delivery.next_attempt(claim).job_id, "abc")


class ClaimOncePerJobTests(unittest.TestCase):
    def test_a_handled_job_is_claimed_and_completed_once(self):
        stop = asyncio.Event()
        seen = []

        async def handler(data):
            seen.append(data)
            stop.set()

        recorder = _Recorder()
        _run_consumer(
            [_raw_job({"type": "ingest", "website_id": "w1"})],
            {"ingest": handler},
            stop,
            seam=lambda *a, **k: recorder,
        )

        self.assertEqual(len(recorder.claimed), 1)
        self.assertEqual(len(recorder.completed), 1)
        self.assertEqual(recorder.failed, [])
        # The handler still receives the producer's payload plus the envelope.
        self.assertEqual(seen[0]["website_id"], "w1")
        self.assertEqual(recorder.claimed[0].job_id, seen[0]["job_id"])
        self.assertEqual(recorder.claimed[0].job_type, "ingest")

    def test_an_unknown_type_is_never_claimed(self):
        stop = asyncio.Event()
        stop.set()
        recorder = _Recorder()
        queue = _run_consumer(
            [_raw_job({"type": "nope"})], {}, stop, seam=lambda *a, **k: recorder
        )

        self.assertEqual(recorder.claimed, [])
        self.assertEqual(recorder.completed, [])
        self.assertEqual(recorder.failed, [])
        self.assertEqual(queue.calls, [])

    def test_a_raising_handler_is_failed_once_and_the_loop_continues(self):
        boom = RuntimeError("crawl exploded")
        stop = asyncio.Event()
        calls = []

        async def handler(data):
            calls.append(data["website_id"])
            if data["website_id"] == "w1":
                raise boom
            stop.set()

        recorder = _Recorder()
        _run_consumer(
            [
                _raw_job({"type": "ingest", "website_id": "w1"}),
                _raw_job({"type": "ingest", "website_id": "w2"}),
            ],
            {"ingest": handler},
            stop,
            seam=lambda *a, **k: recorder,
        )

        self.assertEqual(calls, ["w1", "w2"])
        self.assertEqual(len(recorder.claimed), 2)
        self.assertEqual(len(recorder.failed), 1)
        self.assertEqual(len(recorder.completed), 1)
        self.assertIs(recorder.failed[0][1], boom)
        # No retry under this implementation: the failed job is not re-queued and
        # the second job is the only other one the loop saw.
        self.assertEqual(recorder.failed[0][0].job_id, recorder.claimed[0].job_id)


class JobIdentityOnEventsTests(unittest.TestCase):
    """A job can be followed from the pop to its failure by `job_id`.

    The envelope is a label on events that already existed: nothing here is a
    new event or a delivery record, it only stops the three events about one job
    from being matched by timestamp.
    """

    def test_received_and_failed_events_carry_the_same_id(self):
        stop = asyncio.Event()

        async def handler(_data):
            stop.set()
            raise RuntimeError("boom")

        with patch.object(worker, "log_event") as events, patch.object(
            delivery, "log_exception"
        ) as failed:
            _run_consumer(
                [_raw_job({"type": "ingest", "website_id": "w1"})],
                {"ingest": handler},
                stop,
            )

        received = [
            c for c in events.call_args_list if c.args[0] == "worker.job.received"
        ]
        self.assertEqual(len(received), 1)
        self.assertEqual(len(failed.call_args_list), 1)
        received_kwargs = received[0].kwargs
        failed_kwargs = failed.call_args.kwargs
        self.assertTrue(received_kwargs["job_id"])
        self.assertEqual(received_kwargs["job_id"], failed_kwargs["job_id"])
        self.assertEqual(received_kwargs["attempt"], 0)
        self.assertEqual(failed_kwargs["attempt"], 0)

    def test_an_unknown_type_reports_the_same_id_it_popped(self):
        stop = asyncio.Event()
        with patch.object(worker, "log_event") as events:
            # Stop after the single pop, so the skip is logged and the loop leaves.
            _run_consumer(
                [_raw_job({"type": "nope"})], {}, stop, on_pop=stop.set
            )

        by_event = {
            c.args[0]: c.kwargs
            for c in events.call_args_list
            if str(c.args[0]).startswith("worker.job.")
        }
        self.assertEqual(
            set(by_event), {"worker.job.received", "worker.job.unknown"}
        )
        self.assertEqual(by_event["worker.job.unknown"]["job_type"], "nope")
        self.assertEqual(
            by_event["worker.job.unknown"]["job_id"],
            by_event["worker.job.received"]["job_id"],
        )
        self.assertEqual(by_event["worker.job.unknown"]["attempt"], 0)

    def test_a_legacy_payload_gets_an_id_before_the_first_event(self):
        stop = asyncio.Event()
        # No job_id and no attempt on the wire: the id on the events is minted
        # at pop time, so even a hand-pushed job is followable.
        with patch.object(worker, "log_event") as events:
            _run_consumer(
                [_raw_job({"type": "nope"})], {}, stop, on_pop=stop.set
            )

        received = [
            c for c in events.call_args_list if c.args[0] == "worker.job.received"
        ]
        self.assertEqual(len(str(UUID(received[0].kwargs["job_id"]))), 36)


class UnchangedFailureCountingTests(unittest.TestCase):
    """`NullDelivery.fail` must do exactly what the loop's old except did."""

    def test_fail_logs_one_event_and_increments_once(self):
        client = MagicMock()
        counter = AsyncMock(return_value=1)
        implementation = delivery.NullDelivery(client, note_failure=counter)
        claim = delivery.Claim(job_id="abc", attempt=0, job_type="ingest")

        with patch.object(delivery, "log_exception") as logged:
            outcome = asyncio.run(implementation.fail(claim, RuntimeError("x")))

        counter.assert_awaited_once_with(client)
        logged.assert_called_once()
        self.assertEqual(logged.call_args.args[0], "worker.job.failed")
        self.assertEqual(logged.call_args.kwargs["job_type"], "ingest")
        self.assertEqual(logged.call_args.kwargs["job_id"], "abc")
        self.assertEqual(logged.call_args.kwargs["attempt"], 0)
        # No retry: nothing re-queues the job under this implementation.
        self.assertFalse(outcome.retry)
        self.assertFalse(outcome.parked)
        self.assertIs(outcome.claim, claim)

    def test_fail_without_a_client_logs_but_does_not_count(self):
        implementation = delivery.NullDelivery(None, note_failure=AsyncMock())
        claim = delivery.Claim(job_id="abc", attempt=0, job_type="ingest")

        with patch.object(delivery, "log_exception") as logged:
            outcome = asyncio.run(implementation.fail(claim, RuntimeError("x")))

        logged.assert_called_once()
        implementation.note_failure.assert_not_awaited()
        self.assertFalse(outcome.retry)

    def test_complete_is_a_no_op(self):
        implementation = delivery.NullDelivery(MagicMock())
        claim = delivery.Claim(job_id="abc", attempt=0, job_type="ingest")
        self.assertIsNone(asyncio.run(implementation.complete(claim)))

    def test_the_worker_counts_through_its_own_hook(self):
        # The loop builds `NullDelivery(redis_client, note_failure=note_job_failure)`,
        # so the counter patched on the worker module is the one that runs.
        stop = asyncio.Event()
        counter = AsyncMock(return_value=1)

        async def handler(_data):
            stop.set()
            raise RuntimeError("boom")

        queue = _Queue([_raw_job({"type": "ingest", "website_id": "w1"})])
        with (
            patch.object(worker, "redis_client", queue),
            patch.object(worker, "configure_logging", MagicMock()),
            patch.object(worker, "requeue_stuck_ingests", AsyncMock()),
            patch.object(worker, "start_background_loops", lambda: []),
            patch.object(worker, "note_queue_pop", AsyncMock(return_value=True)),
            patch.object(worker, "note_job_failure", counter),
            patch.object(worker, "close_client", AsyncMock(return_value=True)),
            patch.object(worker, "dispose_engine", MagicMock()),
            patch.object(worker, "_JOB_HANDLERS", {"ingest": handler}),
        ):
            asyncio.run(worker.worker(stop=stop))

        counter.assert_awaited_once_with(queue)


if __name__ == "__main__":
    unittest.main()
