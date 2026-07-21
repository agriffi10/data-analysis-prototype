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

# Max recipients in one share request.
#
# THE DISASTER THIS PREVENTS is not the fan-out itself — it is the Map's RESULT. Each item
# contributes a summary entry to `$.recipientResults`, and a FAILED entry carries the raw
# Step Functions {Error, Cause} (PR #252 — the ASL decode that used to shrink it raised an
# uncatchable States.Runtime, so the raw object is what makes the reason recoverable at all).
# Measured against a real Cause from execution history: ~570 bytes per failed recipient,
# ~1.2 KB with a verbose Athena StateChangeReason. Step Functions caps a state payload at
# 256 KB, and breaching it raises States.DataLimitExceeded ON THE MAP — which routes to the
# whole-request RecordFailure and DESTROYS every per-recipient outcome the Map exists to
# preserve, turning a partial success into a total failure.
#
# Measured, not guessed: at the bounded worst case (a maximum-length detail plus a deep
# stack) 100 recipients reach ~154 KB — under the limit, but the request object rides in
# the SAME payload, so that margin is thinner than it looks. 50 lands at ~68 KB — 26% of
# the limit. test_map_result_stays_under_the_state_payload_limit computes this from these
# constants, so changing either without re-checking the other fails the build.
# The other half of the bound is cpcommon.athena truncating the raw Athena reason it puts
# in a TerminalError detail — a cap on COUNT alone cannot bound a 32 KB Cause, which
# breaches at seven recipients.
#
# It is also a sane product limit in its own right: 1000 objects x 50 recipients is
# 50,000 CopyObject calls, and there was previously NO cap at all.
SHARE_MAX_RECIPIENTS = 50

# Max serialized size of the cloned table definition.
#
# The LAST unbounded term on the Map's state. Moving the object list to a pointer removed
# the big one, but `tableDefinition` still rides inline — and it is USER-CONTROLLED: it
# clones the source's columns (name/type/comment) and its Glue table properties verbatim,
# and a user can set both from the query workspace (CREATE EXTERNAL TABLE … TBLPROPERTIES).
# Measured with the plan already by pointer, 50 recipients all failing:
#
#     300 columns, no comments      89 KB    34%
#   1,000 columns, no comments     123 KB    47%
#   1,000 columns, 255-char comments 393 KB  150%   <- BREACH, after the pointer
#
# So a wide-enough table still trips States.DataLimitExceeded on the Map and destroys every
# per-recipient outcome. 32 KiB is generous — roughly 600 plain columns — and lands the
# worst case near 41%. Rejected in inspect-source as a whole-request terminal, before any
# recipient runs, which is the same shape as the object/byte caps above.
SHARE_MAX_DEFINITION_BYTES = 32 * 1024
