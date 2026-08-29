"""A request's space, resolved from verified claims and never from what the request said.

Every object route names a space. This module turns that name into a bucket and a root prefix,
and it is the only thing standing between a caller and somebody else's prefix — so the whole
module is about what it *refuses*.

**It reads claims and nothing else.** `focommon.authz` solves the same problem by loading the
shared-space registry and asking whether the caller is an active member, and copying that here
would be wrong twice: it costs an S3 read on a path SPEC-198 FR-001 requires to make **zero** AWS
calls before refusing, and it sources membership from somewhere other than the claims SPEC-196's
"the API assumes the same role with the same tags from the same claims" equivalence rests on.
That file is the obvious thing to reach for; this docstring is here to say don't.

**A refusal costs no AWS call, and that is asserted by call count** — because a refusal issued
*after* a successful `AssumeRole` and `ListObjectsV2` looks identical from outside the process.
"""

from dataclasses import dataclass
from typing import Literal

from . import config
from .envelope import ApiError
from .identity import UserIdentity

SpaceKind = Literal["personal", "shared"]


@dataclass(frozen=True)
class ResolvedSpace:
    """Where a request's objects actually live.

    Attributes:
      kind: Which sort of space it is, for the rules that differ between the two buckets.
      name: The space's name, as the caller gave it and as the claims confirmed it.
      bucket: The bucket holding it.
      root: The space's root prefix, always ending in ``/``.
    """

    kind: SpaceKind
    name: str
    bucket: str
    root: str


def resolve(identity: UserIdentity, kind: str, name: str) -> ResolvedSpace:
    """Resolves a named space against the caller's verified identity.

    Args:
      identity: The AWS identity built from the caller's verified claims.
      kind: The space kind the request named.
      name: The space name the request named.

    Returns:
      The resolved space.

    Raises:
      ApiError: ``AccessDenied`` when the name is not one the claims authorize, or when the kind
        is neither of the two. Raised before any AWS call.
      ConfigError: If the bucket variables are unset.
    """
    if kind == "personal":
        # The ONLY personal space a caller may name is their own, and the comparison is against
        # the verified username rather than against anything in the request. A request naming
        # another user's personal space is the case FR-013's route-layer proof turns on.
        if name != identity.username:
            raise ApiError("AccessDenied", "personal space is not the caller's")
        return ResolvedSpace("personal", name, config.user_space_bucket(), f"{name}/")

    if kind == "shared":
        # Membership is the claim set, whole. Checking a slot number instead of the values would
        # let a caller pick which of their own memberships to be checked against.
        if name not in set(identity.memberships.values()):
            raise ApiError("AccessDenied", "no membership claim for that space")
        return ResolvedSpace("shared", name, config.shared_space_bucket(), f"{name}/")

    raise ApiError("AccessDenied", "unknown space kind")
