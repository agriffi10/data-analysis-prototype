"""Domain configuration for the table-builder control plane.

The shared core — region, user pool identifiers, buckets, workgroup, notifications queue,
the catalog identifier rule — lives in ``cpcommon.config``. Only table-builder's own
constants live here.

Attributes:
  PARTITION_TYPES: The partition-key projection types the build modal can declare.
"""

PARTITION_TYPES = frozenset({"integer", "date", "string"})
