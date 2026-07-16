"""data-quality check-query — SPEC-108 SKELETON STUB.

The polling verb the state machine's Wait -> CheckQuery -> Choice loop calls. SPEC-111
replaces this with a real Athena GetQueryExecution (and raises TerminalError on a
FAILED/CANCELLED query, so the Choice only ever sees QUEUED/RUNNING/SUCCEEDED).

The stub returns a DETERMINISTIC status sequence driven by a ``pollCount`` it carries in
the threaded request: RUNNING on the first call, SUCCEEDED afterwards. That makes the
skeleton's polling loop provably iterate at least once (SPEC-108 FR-004's smoke test)
without any Athena query existing, and it terminates — a stub that always returned
RUNNING would spin the state machine until the execution timed out.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# One loop iteration, then proceed — enough to prove Wait -> CheckQuery -> Choice cycles.
_POLLS_BEFORE_SUCCESS = 1


def handler(event, context) -> dict:
    """Return the threaded request plus a queryStatus, incrementing pollCount."""
    request = dict(event) if isinstance(event, dict) else {}
    polls = int(request.get("pollCount") or 0) + 1
    request["pollCount"] = polls
    request["queryStatus"] = "RUNNING" if polls <= _POLLS_BEFORE_SUCCESS else "SUCCEEDED"
    logger.info("check-query stub: poll=%s status=%s", polls, request["queryStatus"])
    return request
