"""table-builder inspect-source — SPEC-066 stub.

The real logic (list the prefix; validate a single consistent supported format; confirm
the request's user-declared key=value/ partition keys match the layout; emit
{format, partitioned, sampleObjectKey, location, fileCount}) lands in SPEC-068. For the
SPEC-066 control-plane smoke test this echoes its input so the Step Function threads the
request object to the next step.
"""

import json


def handler(event, context):
    print(f"table-builder-inspect-source stub invoked: {json.dumps(event)[:512]}")
    return event
