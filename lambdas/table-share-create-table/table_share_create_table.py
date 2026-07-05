"""create-table — table-share verb Lambda (PLACEHOLDER).

SPEC-088 stub: passes its input through unchanged so the control-plane skeleton
(queue → pipe → state machine → recipient Map) can be smoke-tested end to end.
The real logic — runs the cloned CREATE EXTERNAL TABLE IF NOT EXISTS via Athena in the recipient database — lands in SPEC-092.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Pass the threaded state object through unchanged."""
    logger.info("placeholder create-table invoked")
    return event
