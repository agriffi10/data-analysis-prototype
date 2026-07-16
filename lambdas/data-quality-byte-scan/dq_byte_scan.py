"""data-quality byte-scan — SPEC-108 SKELETON STUB.

Will run the bounded, SAMPLED raw-byte encoding check — the one thing a SQL engine
cannot see. Its budget is PER REQUEST (DQ_SCAN_TOTAL_BYTES, default 2 GiB) divided across
the manifest's files, never per file.

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
    logger.info("byte-scan stub: requestId=%s", request.get("requestId"))
    return request
