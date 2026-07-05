"""inspect-source — table-share verb Lambda (PLACEHOLDER).

SPEC-088 stub: passes its input through unchanged so the control-plane skeleton
(queue → pipe → state machine → recipient Map) can be smoke-tested end to end.
The real logic — clones the source Glue table definition, lists the source objects, and enforces the copy caps — lands in SPEC-090.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Pass the threaded state object through unchanged."""
    logger.info("placeholder inspect-source invoked")
    return event
