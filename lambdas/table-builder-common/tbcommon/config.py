"""Domain configuration for the table-builder control plane (SPEC-107).

The shared core (region, User Pool ids, buckets, workgroup, notifications queue,
``CATALOG_IDENTIFIER_RE``, ``_require``) moved to ``cpcommon.config``; only the
table-builder domain constants live here.
"""

# Partition-key projection types the modal can declare (table-builder domain).
PARTITION_TYPES = frozenset({"integer", "date", "string"})
