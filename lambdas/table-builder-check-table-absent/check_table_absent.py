"""table-builder check-table-absent — SPEC-066 stub.

The real logic (Glue GetTable in the target database → fail terminal `table_exists`
if the table already exists, else pass) lands in SPEC-068. For the SPEC-066
control-plane smoke test this echoes its input so the Step Function threads the
request object to the next step.
"""

import json


def handler(event, context):
    print(f"table-builder-check-table-absent stub invoked: {json.dumps(event)[:512]}")
    return event
