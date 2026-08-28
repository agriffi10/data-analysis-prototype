"""Domain configuration for the table-builder control plane.

The shared core — region, user pool identifiers, buckets, workgroup, notifications queue,
the catalog identifier rule — lives in ``cpcommon.config``. Only table-builder's own
constants live here.

Attributes:
  PARTITION_TYPES: The partition-key projection types the build modal can declare.
  REFRESH_MAX_DEFINITION_BYTES: Largest live table definition a refresh will carry onto the
    Step Functions state. Its own bound, deliberately not table-share's, which was measured
    for a 50-recipient Map. Breaching the 256 KB state-payload limit raises
    States.DataLimitExceeded outside every Catch, so an oversized table is refused up front.
    Sizing evidence is in ``lambdas/info/planes/table-builder.md``.
"""

PARTITION_TYPES = frozenset({"integer", "date", "string"})

REFRESH_MAX_DEFINITION_BYTES = 40 * 1024
