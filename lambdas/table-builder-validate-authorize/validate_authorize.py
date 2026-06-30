"""table-builder validate-authorize — SPEC-066 stub.

First step of the table-builder control plane. The real logic (verify the caller's
Cognito ID token offline → actor; authorize the target personal/shared space;
validate the table name, location, and declared partition keys) lands in SPEC-067.

For the SPEC-066 control-plane smoke test this is an echo/pass-through: it logs that
it ran and returns its input so the Step Function threads the request object to the
next step. The Pipe forwards the raw SQS batch (a JSON array); the state machine's
ValidateAuthorize state uses OutputPath=$.Payload, so whatever this returns becomes
the running request object for the downstream steps.
"""

import json


def handler(event, context):
    print(f"table-builder-validate-authorize stub invoked: {json.dumps(event)[:512]}")
    return event
