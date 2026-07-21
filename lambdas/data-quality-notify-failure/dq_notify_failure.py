"""data-quality notify-failure — SPEC-108 SKELETON STUB.

Will emit the friendly failure notification to the actor from the recorded-failure
outcome. Provisioned in the foundation, wired by the producer spec.

Pass-through only: SPEC-114 FR-004 wires the real logic. This stub exists so the foundation's
control-plane path runs end to end (message -> Pipe -> execution -> terminal state) and
the smoke test can prove the plumbing before any logic lands. It returns the threaded
request object unchanged, so every later state sees the shape it expects.

ITS INPUT CARRIES THE RAW STEP FUNCTIONS ERROR, NOT A DECODED REASON. RecordFailure
passes `error` through as {Error, Cause} untouched, because the ASL decode that used to
produce a `reason` field lived in a Pass state running States.StringToJson — which raises
an UNCATCHABLE States.Runtime on any Cause that is absent or not JSON (States.Timeout,
States.DataLimitExceeded, Lambda.Unknown), killing the execution before it ever reached
this function. SPEC-114 must call cpcommon.errors.failure_reason(event["error"]) to get a
stable reason code and map it through dqcommon.messages.failure_message — never read a
`reason` key, and never surface the raw Cause to a user (SPEC-106 FR-008).
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context) -> dict:
    """Return the threaded request object unchanged (skeleton no-op)."""
    request = dict(event) if isinstance(event, dict) else {}
    logger.info("notify-failure stub: requestId=%s", request.get("requestId"))
    return request
