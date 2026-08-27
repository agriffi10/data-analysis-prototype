"""The arc's first proof that a server-assumed session is isolated, and its negative control.

**Scaffolding, and it is deleted by the spec that ports the first real route.** It exists because
until a feature is ported there is no way to drive the identity layer end to end at all, and a
layer nobody has driven is a layer nobody has tested. Every offline test in this arc supplies its
own claims and its own stubbed STS; none of them can tell you that the trust policy admits the
API, that the tags were stamped, or that the bucket policy's allowlist resolves an assumed-role
request the way the comment in ``s3.tf`` says it does.

**Both booleans are required, and they fail for different reasons.** An unstamped tag makes the
first false — the portal role grants ``s3:ListBucket`` only under a prefix condition naming the
tag — and an over-granted or wrongly-conditioned policy makes the second true. A probe asserting
only that its own prefix is listable would pass with the isolation model deleted.

**It takes no parameter of any kind.** The foreign prefix is a constant in this file, not an
input: a route that lists a caller-supplied prefix is the credential-selection defect the identity
layer forbids, wearing a probe's clothes.

**A false negative control must mean AWS refused, never that something went wrong.** Only a denial
becomes ``false``; a timeout, a throttle or a missing bucket propagates and fails the request. A
broad ``except`` here would report a passing isolation proof for a call that never happened, on
the one route the whole live verification hangs on.

Attributes:
  FOREIGN_PREFIX: A prefix no username can ever be — it fails the catalog identifier rule on its
    first character, which a test asserts rather than assumes. It is also not one of the bucket's
    real shared prefixes, so a denial here is the isolation model and not a coincidence.
  PROBE_MAX_KEYS: One key is enough to learn whether a listing is permitted, and this call is
    billed like any other.
"""

from typing import Any

from apicommon import identity
from apicommon.config import user_space_bucket
from apicommon.context import RequestContext

FOREIGN_PREFIX = "__no_such_user__/"
PROBE_MAX_KEYS = 1


def _listable(client: Any, prefix: str) -> bool:
    """Whether this caller's session may list one prefix of the user-space bucket.

    Args:
      client: A user-plane S3 client.
      prefix: The prefix to attempt.

    Returns:
      True if the listing was permitted, False if AWS refused it.

    Raises:
      Exception: Anything that is not a denial. A fault must not read as a refusal — that is the
        difference between "isolation is working" and "the call never happened".
    """
    try:
        client.list_objects_v2(
            Bucket=user_space_bucket(), Prefix=prefix, MaxKeys=PROBE_MAX_KEYS
        )
    except Exception as exc:
        from apicommon.errors import DENIAL_CODES

        if identity.aws_error_code(exc) in DENIAL_CODES:
            return False
        raise
    return True


def identity_self(context: RequestContext) -> dict[str, Any]:
    """Reports what this caller's assumed session can and cannot reach.

    The space count is taken from the token's CLAIMS rather than from the session's tags, and that
    is a limitation rather than a choice: nothing this route touches is governed by a membership
    tag, so the number would be the same with every slot tag dropped. The slot half of the tag
    proof is owed to the spec that ports a route reaching a shared space.

    Args:
      context: The authenticated request.

    Returns:
      The caller's username, how many spaces their token says they are in, and the two booleans.

    Raises:
      IdentityUnavailableError: If the role cannot be assumed.
      Exception: Any non-denial failure from either listing.
    """
    client = identity.user_client("s3", context.acting_as)
    return {
        "username": context.acting_as.username,
        "spaceCount": len(context.acting_as.memberships),
        "ownPrefixListable": _listable(client, f"{context.acting_as.username}/"),
        "foreignPrefixListable": _listable(client, FOREIGN_PREFIX),
    }
