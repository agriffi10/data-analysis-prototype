"""validate-authorize — the table-share Step Function's first task (PLACEHOLDER).

SPEC-088 stub: parses the Pipe's raw SQS batch into the request object and passes
it through so the control-plane skeleton (queue → pipe → state machine → Map) can
be smoke-tested end to end. The real logic — offline ID-token → actor, source-table
authorization, catalog-safe result name, per-recipient existence checks, and the
structured recorded-failure terminals — lands in SPEC-089.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Return the parsed request body (the Pipe forwards a one-record SQS batch)."""
    record = event[0] if isinstance(event, list) and event else {}
    body = record.get("body") if isinstance(record, dict) else None
    request = json.loads(body) if body else {}
    # The Map state iterates $.recipients; default it so a minimal smoke message
    # still reaches the terminal state.
    request.setdefault("recipients", [])
    logger.info("placeholder validate-authorize passing through request %s", request.get("requestId"))
    return request
