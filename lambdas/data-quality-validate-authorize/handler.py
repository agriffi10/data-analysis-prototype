"""data-quality validate-authorize — SPEC-108 SKELETON STUB.

Pass-through only: no token verification, no authorization, no destination validation —
all of that is SPEC-109. This stub exists so the foundation's control-plane path runs end
to end (message -> Pipe -> execution -> terminal state) and the smoke test can prove the
plumbing before any logic lands.

Its input is the RAW SQS batch the Pipe forwards (a JSON array); it returns the parsed
request body as the object every later state threads.

IT MUST GUARANTEE THE IDENTITY CONTRACT. From this state onward the threaded object has
to carry ``requestId`` and ``actor`` KEYS, because the terminal ``RecordSuccess`` /
``RecordFailure`` Pass states read ``$.requestId`` / ``$.actor``. A Pass state's JSONPath
resolution HARD-FAILS on an ABSENT key (States.Runtime) — and that failure is
UNCATCHABLE: a Pass state has no Catch, so it escapes straight to ExecutionFailed,
skipping NotifyFailure and leaving the user with no notification at all. A null VALUE is
fine (the key exists); a missing key is fatal. SPEC-109 binds ``actor`` from the verified
token claim; this stub only guarantees the keys are present.
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

    # The identity contract the terminal Pass states depend on (see the module docstring).
    request.setdefault("requestId", None)
    request.setdefault("actor", None)

    logger.info("validate-authorize stub: requestId=%s", request.get("requestId"))
    return request
