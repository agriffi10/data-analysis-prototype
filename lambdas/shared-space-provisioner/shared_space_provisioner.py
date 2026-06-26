"""Shared-space provisioner (SPEC-050 skeleton).

The Step Function (infra/modules/shared-spaces/stepfunction.tf) invokes this Lambda
with the shared-space request message. SPEC-050 is FOUNDATION ONLY: this handler
dispatches/echoes — it provisions nothing. Per-action logic (create / add_member /
remove_member / leave / delete, switched on ``action``) lands in SPEC-051-055, along
with the request-message contract itself (SPEC-056).

Its only job today is to make the control plane observable end-to-end: a message
placed on the SQS queue flows SQS -> EventBridge Pipe -> Step Function -> here, and
this logs what it received and echoes it back so the execution shows a success in
CloudWatch (the SPEC-050 smoke test, docs/testing/shared-spaces-e2e.md).

Input shape: the Pipe forwards the SQS records, so ``event`` is a list of message
records (batch size 1, so length 1). The request body is the SQS ``body`` string.
This skeleton parses defensively — the contract is not defined until SPEC-056 — and
never raises, so a malformed message during early testing is logged, not retried
into the DLQ.
"""

import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def _extract_records(event):
    """Normalise the Pipe payload to a list of SQS records.

    The EventBridge Pipe forwards a list of SQS message records. Tolerate a bare
    dict (single record) or anything unexpected so the skeleton never crashes.
    """
    if isinstance(event, list):
        return event
    if isinstance(event, dict):
        return [event]
    return []


def _parse_action(record):
    """Best-effort pull of ``action`` from an SQS record body. Skeleton only."""
    body = record.get("body") if isinstance(record, dict) else None
    if not body:
        return None
    try:
        return json.loads(body).get("action")
    except (TypeError, ValueError):
        return None


def handler(event, context):
    records = _extract_records(event)
    actions = [_parse_action(r) for r in records]
    logger.info(
        "shared-space-provisioner skeleton invoked: %d record(s), actions=%s",
        len(records),
        actions,
    )
    # Echo so the Step Function execution carries the dispatch result (no-op until
    # SPEC-051+ replaces this with real per-action provisioning).
    return {"status": "dispatched", "count": len(records), "actions": actions}
