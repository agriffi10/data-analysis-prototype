"""Domain configuration for the table-share control plane (SPEC-107).

The shared core (region, User Pool ids, buckets, workgroup, notifications queue,
``CATALOG_IDENTIFIER_RE``, ``_require``) moved to ``cpcommon.config``; only the
table-share domain constants live here.
"""

# Copy caps (SPEC-090): a share exceeding either is a whole-request terminal failure
# ("too large for v1 — S3 Batch Operations is the deferred escape hatch"). Sized so a
# recipient Map item's parallel server-side copy finishes comfortably inside
# copy-objects' 900s timeout (architecture §12).
SHARE_MAX_OBJECTS = 1000
SHARE_MAX_TOTAL_BYTES = 20 * 1024**3  # 20 GiB

# The two recipient kinds a share request may target (SPEC-089 contract).
RECIPIENT_KINDS = frozenset({"user", "space"})
