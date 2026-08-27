"""The AWS identity a request acts as, and the two credential planes that serve it.

**The API stamps what the Identity Pool stamps, from the same claims of the same token.** That is
the whole of why no IAM policy, bucket policy or Lake Formation grant is rewritten by moving a
call from the browser to here. ``identity-pool.tf`` declares which claim feeds which tag —
``username`` from the username claim, ``shared_space_k`` from ``custom:shared_space_k`` — and AWS
applies that map to the ID token the browser presents. This module is handed the same token's
VERIFIED claims and applies the same map. A policy sees a session tag, not who stamped it.

The claim names are the only thing copied from the Identity Pool, and copying them is what makes
the preservation provable rather than arguable. Sourcing membership from the shared-space registry
instead would be defensible on its own and would break the equivalence.

**A provider fact lives here, deliberately, and it is the sixth.** The verifier describes its
provider in five configured values and names none in code. ``custom:shared_space_{k}`` is a sixth,
hard-coded, and it stays hard-coded because the requirement is byte-equivalence with the map
Terraform declares — a configurable claim template would be free to drift from that map, which is
the one thing the equivalence cannot survive. The username needs no such exception: it arrives
already resolved through the configured username claim. Recorded rather than left to be found,
because the tag set does not outlive the transition and the next reader deserves to know which
half is a decision.

**The failure mode this file is shaped around fails OPEN.** A helper handing back the wrong client
makes the call SUCCEED, against the wrong identity, returning right-looking data. So the identity
is a PARAMETER at every door, the credential cache is keyed on the whole tag set rather than
cleared, and a route reaches AWS through exactly two constructors.

Attributes:
  SHARED_SPACE_CLAIM: The claim carrying the space name occupying one membership slot.
  SHARED_SPACE_TAG: The session tag that claim becomes. Its agreement with the Tofu map is
    asserted, because a hand-written slot name that drifts produces plausible-looking tags
    matching no policy statement.
  ROLE_SESSION_NAME_RE: STS's own charset for a role session name, which the catalog rule is a
    strict subset of.
  MAX_ROLE_SESSION_NAME: STS's ceiling on that name.
  REASON_UNREPRESENTABLE_USERNAME: Logged when a username cannot be a session name. A fixed
    literal; the username travels as a field, where an operator can read it.
"""

import dataclasses
import datetime
import re
from collections.abc import Mapping
from typing import Any

from cpcommon.auth import Principal
from cpcommon.config import CATALOG_IDENTIFIER_RE

from . import config, planes

SHARED_SPACE_CLAIM = "custom:shared_space_{}"
SHARED_SPACE_TAG = "shared_space_{}"

ROLE_SESSION_NAME_RE = re.compile(r"^[\w+=,.@-]{2,64}$")
MAX_ROLE_SESSION_NAME = 64

REASON_UNREPRESENTABLE_USERNAME = "unrepresentable_username"


class PlaneViolationError(RuntimeError):
    """Raised when a route reaches for a credential plane it did not declare.

    Its own type rather than a ``ValueError`` because it must never be mistaken for a caller's
    bad input: it says a route asked for privileges its entry does not carry, which is a
    programming error caught before any AWS call rather than a request that can be refused.
    """


class IdentityUnavailableError(RuntimeError):
    """The role could not be assumed, or the username cannot be represented as a session name.

    Distinct from every authorization failure, and the distinction is the point: this is the API
    unable to act at all, which is a server fault the user did nothing to cause and can do
    nothing about. A denial reaching the user as this, or this reaching them as a denial, is the
    conflation the failure mapping exists to prevent.
    """


@dataclasses.dataclass(frozen=True)
class UserIdentity:
    """The verified identity a request acts as.

    Built ONLY from the claims of the verified ID token — the same claims the Identity Pool's
    principal-tag map reads today. Constructed in this module and nowhere else, asserted by a
    sweep: a route minting one from a path segment would assume the portal role as somebody
    else, and would pass every test that supplies a matching token.

    Attributes:
      username: The verified username claim, already resolved by the verifier.
      memberships: Slot index (1-based) to space name, from the membership claims. A slot with
        no claim is ABSENT, never present with an empty value.
    """

    username: str
    memberships: Mapping[int, str]


@dataclasses.dataclass(frozen=True)
class AssumedCredentials:
    """One caller's temporary AWS credentials.

    Attributes:
      access_key_id: The session's access key.
      secret_access_key: The session's secret key. Never a log field, never a response body.
      session_token: The session token. The same.
      expires_at: When the session ends, TIMEZONE-AWARE because that is what STS returns.
        Comparing an aware value to a naive one raises rather than mis-compares, so a fixture
        that drops the timezone measures a shape STS never produces.
    """

    access_key_id: str
    secret_access_key: str
    session_token: str
    expires_at: datetime.datetime


def memberships_from(claims: Mapping[str, object]) -> Mapping[int, str]:
    """Reads the occupied membership slots out of a verified claim set.

    A slot whose claim is absent, empty or not a string contributes NOTHING — it is omitted from
    the mapping rather than carried as an empty value. That is load-bearing rather than tidy: an
    empty-valued tag makes a shared-space resource ARN resolve to a bucket followed by a bare
    slash, which is a live grant on every key beginning with one, and S3 permits such a key. An
    unstamped slot, by contrast, matches nothing.

    Args:
      claims: The verified claim set, whole.

    Returns:
      Slot index to space name, holding only the occupied slots.

    Raises:
      ConfigError: If the slot count is unset or unusable.
    """
    occupied: dict[int, str] = {}
    for slot in range(1, config.max_shared_memberships() + 1):
        value = claims.get(SHARED_SPACE_CLAIM.format(slot))
        if isinstance(value, str) and value:
            occupied[slot] = value
    return occupied


def identity_from(caller: Principal) -> UserIdentity:
    """Builds the identity a request acts as, from the verifier's result alone.

    Takes the resolved principal rather than a raw token, so this module holds no decoder of its
    own. It reads the same claims the Identity Pool reads out of the same token, which is the
    whole equivalence argument in one function.

    Args:
      caller: The verified caller.

    Returns:
      The identity, carrying the username and every occupied membership slot.

    Raises:
      ConfigError: If the slot count is unset or unusable.
    """
    return UserIdentity(
        username=caller.username, memberships=memberships_from(caller.claims)
    )


def session_tags(identity: UserIdentity) -> list[dict[str, str]]:
    """Builds the session tags to stamp, in the shape STS takes them.

    The username tag plus one tag per OCCUPIED slot, and nothing for an empty one. The tag names
    are the ones Terraform declares; the values come from claims of a signature-verified token
    and from nothing else the request carries. Anything else as a source — a header, a query
    parameter, a body field, a username re-derived from a path — breaks the equivalence, and it
    breaks it silently, because the call still succeeds.

    Args:
      identity: The verified identity.

    Returns:
      The tag list, username first, then the occupied slots in index order.

    Raises:
      ConfigError: If the tag key is unset.
    """
    tags = [{"Key": config.principal_tag_key(), "Value": identity.username}]
    for slot in sorted(identity.memberships):
        tags.append(
            {"Key": SHARED_SPACE_TAG.format(slot), "Value": identity.memberships[slot]}
        )
    return tags


def role_session_name(username: str) -> str:
    """Returns the session name for a caller, or refuses to invent one.

    The username VERBATIM. No prefix is available and the arithmetic is why: the catalog rule
    admits 63 characters, STS allows 64, so any non-empty prefix overflows — and truncating to
    fit would collapse two usernames onto one identity in every trail that records this session.

    Validated rather than trusted, against both the catalog rule this product keys everything on
    and STS's own charset. A username failing either is REFUSED, never sanitised: the transition
    replaces the username claim with a subject carrying hyphens and uppercase, which this rule
    will not admit, and refusing loudly from one shared constant makes that a single-constant
    change with a failing test in front of it. Sanitising would make it a silent collision.

    Args:
      username: The verified username.

    Returns:
      The session name, identical to the username.

    Raises:
      IdentityUnavailableError: If the username fails either rule. No role is assumed on that
        path.
    """
    if not CATALOG_IDENTIFIER_RE.match(username) or not ROLE_SESSION_NAME_RE.match(
        username
    ):
        raise IdentityUnavailableError(REASON_UNREPRESENTABLE_USERNAME)
    return username


def _execution_client(service: str) -> Any:
    """Builds a client on the function's own execution role. The ONE construction site.

    Private, unguarded, and exempt from the sweep by module identity rather than by any name or
    filename pattern — a pattern exemption silently exempts the next module somebody names
    similarly. Every other module in this package reaches AWS through the two public doors below,
    and the sweep asserts that this package holds exactly one client construction, not merely that
    the others hold none.

    boto3 is imported at the call rather than at module scope, matching the layer's own client
    factories: a request that needs no client should not pay for the import.

    Args:
      service: The AWS service name.

    Returns:
      A client on the execution role's credentials.

    Raises:
      None.
    """
    import boto3

    return boto3.client(service)


def api_client(service: str) -> Any:
    """A client on the execution role, for a route that declared the API plane.

    The check runs BEFORE the client is built, so a violation reaches no AWS service and costs no
    request. Construct-then-check would leave a usable client in the hands of a route that was
    about to be refused, and the refusal is the only thing standing between that route and the
    execution role's own identity.

    Args:
      service: The AWS service name.

    Returns:
      A client on the execution role's credentials.

    Raises:
      PlaneViolationError: If the running route did not declare the API plane, or if no route is
        dispatching at all.
    """
    planes.require(planes.Plane.API)
    return _execution_client(service)
