"""data-quality assemble-report — SPEC-108 SKELETON STUB.

Will join the Athena results + the byte scan + the cross-file column agreement into
report.json at a key that is a pure function of requestId (so a retry overwrites it
byte-identically), and append the per-space runs index entry under ETag CAS (SPEC-123).

Pass-through only: SPEC-112 wires the real logic. This stub exists so the foundation's
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
    logger.info("assemble-report stub: requestId=%s", request.get("requestId"))
    return request
