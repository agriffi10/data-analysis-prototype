"""data-quality drop-temp-tables — SPEC-108 SKELETON STUB.

Will drop the temp Glue tables. Idempotent by design — it must tolerate being reached
before any table was created — and it touches GLUE ONLY (no s3:DeleteObject is granted
anywhere in this arc), which is what makes it safe to reach from every failure path.

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
    logger.info("drop-temp-tables stub: requestId=%s", request.get("requestId"))
    return request
