"""The queue's delivery seam (V6-20, before D9).

D9 has not chosen where the delivery guarantee lives, so this module holds only
the part both candidates need and ships one implementation whose behaviour is
exactly today's. Nothing here decides between the acknowledgement list and the
durable job record (`docs/preflight-v6.md` §1), the duplicate/loss rule (§2), the
retry policy (§3) or where a failure is surfaced (§4).

The three transitions every mechanism needs:

* `claim(job)` records the attempt and returns the job's identity for the rest
  of its handling. `None` means "nothing to do here", which is how a mechanism
  that has already settled this job answers a redelivery.
* `complete(claim)` — the handler returned.
* `fail(claim, exc)` — the handler raised.

`NullDelivery` is the only implementation: `claim` mints nothing, `complete` is
a no-op, and `fail` does exactly what the consumer loop did before this seam
existed — one structured `worker.job.failed` event and one increment of the
`ops:worker:job_failures` counter the V6-21 alert reads. `retry` in the returned
`Outcome` is False for the same reason: nothing re-queues the job today, and
that is a retry policy, not a delivery record.

The envelope is additive. `type` and every producer field stay where they were,
so a handler, an existing test or the V6-2G gate's `redis-cli LPUSH` recipe
reads the same payload; a payload pushed before this seam existed (no `job_id`,
no `attempt`) is accepted and normalised at pop time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol
from uuid import uuid4

from site_gpt.app.core.logging import log_exception
from site_gpt.app.core.telemetry import note_job_failure

#: The envelope's own keys. A reader that does not know them can ignore them.
JOB_ID_KEY = "job_id"
ATTEMPT_KEY = "attempt"


@dataclass(frozen=True)
class Claim:
    """One delivery attempt: the job's identity plus its attempt number."""

    job_id: str
    attempt: int
    job_type: str | None = None


@dataclass(frozen=True)
class Outcome:
    """What `fail` decided about this attempt."""

    claim: Claim
    retry: bool = False
    parked: bool = False


def envelope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`payload` with a job id and attempt number, minted only where absent.

    `enqueue_job` calls this for every new job, and the consumer calls it on what
    came off the queue, so a legacy or hand-pushed payload keeps its exact fields
    and gains the two the seam needs. An existing `job_id` is preserved verbatim
    (a redelivery keeps its identity) and an attempt that is not a non-negative
    integer is read as 0.
    """
    job = dict(payload)
    job_id = job.get(JOB_ID_KEY)
    if not isinstance(job_id, str) or not job_id:
        job_id = str(uuid4())
    job[JOB_ID_KEY] = job_id
    attempt = job.get(ATTEMPT_KEY)
    job[ATTEMPT_KEY] = attempt if isinstance(attempt, int) and attempt >= 0 else 0
    return job


def claim_of(job: Mapping[str, Any]) -> Claim:
    """The `Claim` a normalised envelope describes."""
    raw_type = job.get("type")
    return Claim(
        job_id=str(job.get(JOB_ID_KEY) or ""),
        attempt=int(job.get(ATTEMPT_KEY) or 0),
        job_type=raw_type if isinstance(raw_type, str) else None,
    )


def next_attempt(claim: Claim) -> Claim:
    """The claim a redelivery carries — for a mechanism, never for `NullDelivery`."""
    return replace(claim, attempt=claim.attempt + 1)


class Delivery(Protocol):
    """The seam. Both D9 candidates implement exactly these three calls."""

    async def claim(self, job: Mapping[str, Any]) -> Claim | None: ...

    async def complete(self, claim: Claim) -> None: ...

    async def fail(self, claim: Claim, exc: BaseException) -> Outcome: ...


class NullDelivery:
    """Today's behaviour behind the seam: no record, no retry, same log and count.

    `client` is the worker's Redis client, because the failure counter lives in
    its telemetry keys (V6-21); `None` keeps the implementation silent, for a
    caller that is not a worker. `note_failure` is the counter itself, injected
    so the worker passes the one it already owns and a test can watch it without
    reaching into Redis.
    """

    name = "null"

    def __init__(self, client: Any = None, *, note_failure=note_job_failure):
        self.client = client
        self.note_failure = note_failure

    async def claim(self, job: Mapping[str, Any]) -> Claim:
        return claim_of(job)

    async def complete(self, claim: Claim) -> None:
        return None

    async def fail(self, claim: Claim, exc: BaseException) -> Outcome:
        # Exactly the loop's old `except` block: one event, one counter, no
        # retry. `job_id` and `attempt` are additive fields on that same event.
        log_exception(
            "worker.job.failed",
            exc,
            job_type=claim.job_type,
            job_id=claim.job_id,
            attempt=claim.attempt,
        )
        if self.client is not None:
            await self.note_failure(self.client)
        return Outcome(claim=claim)
