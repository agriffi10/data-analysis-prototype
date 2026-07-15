"""data-quality start-profile-query — SPEC-108 SKELETON STUB.

Will START the Athena profile query (with a ClientRequestToken = requestId, so an SFN
Retry after a post-submission error cannot start a second query) and return its
QueryExecutionId. It never waits — the poll lives in the state machine.

Pass-through only: SPEC-111 wires the real logic. This stub exists so the foundation's
control-plane path runs end to end (message -> Pipe -> execution -> terminal state) and
the smoke test can prove the plumbing before any logic lands. It returns the threaded
request object unchanged, so every later state sees the shape it expects.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context) -> dict:
    """Return the threaded request object unchanged (skeleton no-op)."""
    request = dict(event) if isinstance(event, dict) else {}
    logger.info("start-profile-query stub: requestId=%s", request.get("requestId"))
    return request
