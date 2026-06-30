"""table-builder infer-schema — SPEC-066 stub.

The real logic (open the sample object with a polars LazyFrame → data columns; map
polars dtypes → Hive types; fold in the user-declared partition columns + projection
TBLPROPERTIES; generate the CREATE EXTERNAL TABLE DDL) lands in SPEC-069 and uses the
polars Lambda layer that CI builds + attaches to THIS function (deploy-lambdas.yml).

For the SPEC-066 control-plane smoke test this echoes its input — it does NOT import
polars (the layer is attached but not exercised yet) so the skeleton runs without the
heavy dependency.
"""

import json


def handler(event, context):
    print(f"table-builder-infer-schema stub invoked: {json.dumps(event)[:512]}")
    return event
