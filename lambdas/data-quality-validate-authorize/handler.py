"""data-quality validate-authorize — SPEC-108 SKELETON STUB.

Pass-through only: no token verification, no authorization, no destination validation —
all of that is SPEC-109. This stub exists so the foundation's control-plane path runs
end to end (message -> Pipe -> execution -> terminal state) and the smoke test can prove
the plumbing before any logic lands.

Its input is the RAW SQS batch the Pipe forwards (a JSON array); it returns the parsed
request body as the object every later state threads.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context) -> dict:
    """Return the request body from the SQS record as the threaded request object."""
    record = event[0] if isinstance(event, list) and event else event
    body = record.get("body") if isinstance(record, dict) else None
    request = json.loads(body) if isinstance(body, str) else (record if isinstance(record, dict) else {})
    logger.info("validate-authorize stub: requestId=%s", request.get("requestId"))
    return request
