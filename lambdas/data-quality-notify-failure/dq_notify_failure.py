"""data-quality notify-failure — SPEC-108 SKELETON STUB.

Will emit the friendly failure notification to the actor from the recorded-failure
outcome. Provisioned in the foundation, wired by the producer spec.

Pass-through only: SPEC-114 FR-004 wires the real logic. This stub exists so the foundation's
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
    logger.info("notify-failure stub: requestId=%s", request.get("requestId"))
    return request
