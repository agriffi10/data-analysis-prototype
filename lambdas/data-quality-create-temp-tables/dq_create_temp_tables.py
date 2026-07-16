"""data-quality create-temp-tables — SPEC-108 SKELETON STUB.

Will create the temp external table over the SOURCE (+ for CSV, the single-column
raw-line table the ragged check needs), in the user's own database — which is exactly why
every failure path must reach drop-temp-tables.

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
    logger.info("create-temp-tables stub: requestId=%s", request.get("requestId"))
    return request
