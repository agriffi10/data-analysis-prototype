"""A request's space, resolved from the verified identity and never from what the request said.

Every object route names a space. This module turns that name into a bucket and a root prefix,
and it is the only thing standing between a caller and somebody else's prefix — so the whole
module is about what it *refuses*.

**It reads the identity the router already built, and nothing else.** That identity carries the
memberships the configured source resolved — claims today, the admin-bucket index in the successor
account — so this module and the tag set are answers to one question asked once. `focommon.authz`
solves the same problem by loading the shared-space registry and asking whether the caller is an
active member, and copying that here would be wrong twice: it costs an S3 read of its own on a path
that must reach no AWS service before refusing, and it would be a **second** membership answer
inside one request. Two answers is a defect whichever one is right. That file is the obvious thing
to reach for; this docstring is here to say don't.

**A refusal reaches no AWS service, and that is asserted by call count** — because a refusal
issued *after* a successful `AssumeRole` and `ListObjectsV2` looks identical from outside the
process. Under the index source the request has already made one call to exist at all: the read of
the caller's OWN index, before any route was chosen. That is not an oracle for anything the request
named, and it is the honest form of the guarantee — the refusal itself still costs nothing.

The only personal space a caller may name is their own, compared against the verified username and
never against anything in the request; a shared one is compared against the membership *values*,
because checking a slot number would let a caller choose which of their own memberships is tested.
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
      ApiError: ``AccessDenied`` when the name is not one the identity authorizes, or when the kind
        is neither of the two. Raised before any AWS call.
      ConfigError: If the bucket variables are unset.
    """
    if kind == "personal":
        if name != identity.username:
            raise ApiError("AccessDenied", "personal space is not the caller's")
        return ResolvedSpace("personal", name, config.user_space_bucket(), f"{name}/")

    if kind == "shared":
        if name not in set(identity.memberships.values()):
            raise ApiError("AccessDenied", "no membership for that space")
        return ResolvedSpace("shared", name, config.shared_space_bucket(), f"{name}/")

    raise ApiError("AccessDenied", "unknown space kind")
