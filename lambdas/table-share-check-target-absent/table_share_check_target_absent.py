"""check-target-absent — table-share verb Lambda (PLACEHOLDER).

SPEC-088 stub: passes its input through unchanged so the control-plane skeleton
(queue → pipe → state machine → recipient Map) can be smoke-tested end to end.
The real logic — fails a recipient on a name conflict or non-empty target prefix — lands in SPEC-091.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    """Pass the threaded state object through unchanged."""
    logger.info("placeholder check-target-absent invoked")
    return event
