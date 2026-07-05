"""copy-objects — table-share verb Lambda (PLACEHOLDER).

SPEC-088 stub: passes its input through unchanged so the control-plane skeleton
(queue → pipe → state machine → recipient Map) can be smoke-tested end to end.
The real logic — performs the parallel server-side CopyObject fan-out (multipart > 5 GiB) — lands in SPEC-091.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Pass the threaded state object through unchanged."""
    logger.info("placeholder copy-objects invoked")
    return event
