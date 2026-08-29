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
  REASON_ASSUME_FAILED: Raised when STS refuses or cannot be reached. Fixed, and deliberately
    carrying nothing STS said — a role ARN and an account id travel in the provider's own text.
  REASON_CREDENTIALS_EXPIRED: Raised when a second attempt with freshly assumed credentials
    expires too. One retry is the whole allowance.
  EXPIRED_CREDENTIAL_CODES: The service codes meaning "these credentials are past their expiry",
    which is the one downstream failure worth a forced re-assume.
  _CREDENTIAL_CACHE: Per-container credentials, keyed on the WHOLE tag set. A warm container
    serves many callers in sequence, so this survives the invocation deliberately and is keyed
    rather than cleared — the opposite of trace baggage, and for the opposite reason.
"""

import dataclasses
import datetime
import re
from collections.abc import Mapping
from typing import Any

from cpcommon import observability
from cpcommon.auth import Principal
from cpcommon.config import CATALOG_IDENTIFIER_RE

from . import config, planes

SHARED_SPACE_CLAIM = "custom:shared_space_{}"
SHARED_SPACE_TAG = "shared_space_{}"

ROLE_SESSION_NAME_RE = re.compile(r"^[\w+=,.@-]{2,64}$")
MAX_ROLE_SESSION_NAME = 64

REASON_UNREPRESENTABLE_USERNAME = "unrepresentable_username"
REASON_ASSUME_FAILED = "assume_role_failed"
REASON_CREDENTIALS_EXPIRED = "credentials_expired"

EXPIRED_CREDENTIAL_CODES = frozenset({"ExpiredToken", "ExpiredTokenException"})

_CREDENTIAL_CACHE: dict[tuple[object, ...], "AssumedCredentials"] = {}


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


def _client(service: str, credentials: AssumedCredentials | None = None) -> Any:
    """Builds an AWS client. The ONE construction site in this package.

    With no credentials it is the function's own execution role — the API plane, which is how the
    assume-role call itself is made. With credentials it is the caller's assumed session — the
    user plane, and the only isolation-enforced door.

    Private, unguarded, and exempt from the sweep by module identity rather than by any name or
    filename pattern: a pattern exemption silently exempts the next module somebody names
    similarly. The sweep asserts this package holds exactly ONE construction, not merely that
    every other module holds none — the second is satisfied by a layer that builds six.

    The keyword arguments are assembled before the call rather than split across two calls, so
    there is one site to find and one site to get wrong. boto3 is imported here rather than at
    module scope, matching the layer's own factories: a request needing no client should not pay
    for the import.

    Args:
      service: The AWS service name.
      credentials: The caller's assumed session, or None for the execution role.

    Returns:
      A client on those credentials.

    Raises:
      None.
    """
    import boto3

    session: dict[str, str] = {}
    if credentials is not None:
        session = {
            "aws_access_key_id": credentials.access_key_id,
            "aws_secret_access_key": credentials.secret_access_key,
            "aws_session_token": credentials.session_token,
        }
    return boto3.client(service, **session)


def aws_error_code(exc: BaseException) -> str:
    """Reads the service error code off a botocore client error, if it is one.

    Duck-typed rather than caught by class so this module does not import botocore to read a
    field. The shape is botocore's own and stable.

    PUBLIC deliberately, and it is not a door: it reads a field off an exception and reaches no
    credential. A route needs it to tell a denial from a fault on a call it is deliberately
    expecting to be refused, and the sweep that keeps the two credential doors exclusive should
    not push that route into duplicating this.

    Args:
      exc: The exception to inspect.

    Returns:
      The service's error code, or the empty string.

    Raises:
      None.
    """
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        error = response.get("Error")
        if isinstance(error, dict):
            return str(error.get("Code", ""))
    return ""


def _cache_key(caller: UserIdentity) -> tuple[object, ...]:
    """The key a caller's credentials are cached under: the WHOLE tag set.

    Never the username alone. A username-only key pins a caller to whichever membership set their
    first request of the hour happened to carry — which turns the product's refresh-to-propagate
    contract into refresh-and-nothing-happens. Never nothing at all, which serves the second
    caller the first caller's session.

    Args:
      caller: The verified identity.

    Returns:
      A hashable key covering the username and the ordered membership slots.

    Raises:
      None.
    """
    return (caller.username, tuple(sorted(caller.memberships.items())))


def _usable(credentials: AssumedCredentials, now: datetime.datetime) -> bool:
    """Whether a cached session has enough life left to serve a whole request.

    Args:
      credentials: The cached session.
      now: The current time, timezone-aware.

    Returns:
      True if more than the margin remains.

    Raises:
      TypeError: If either value is naive. Deliberately not defended against — STS returns an
        aware expiry, so a naive one means a fixture is measuring a shape the service never
        produces, and a silent mis-compare would be worse than the raise.
    """
    return (
        credentials.expires_at - now
    ).total_seconds() > config.CREDENTIAL_EXPIRY_MARGIN_SECONDS


@observability.step("assume_user_role")
def _assume(caller: UserIdentity) -> AssumedCredentials:
    """Assumes the portal role as this caller, tagged from their verified claims.

    The session name is resolved FIRST, so a username that cannot be represented is refused
    before any call is issued rather than after one.

    Args:
      caller: The verified identity.

    Returns:
      The assumed session.

    Raises:
      IdentityUnavailableError: If the username cannot be a session name, if the tag set cannot
        be built, or if STS refuses or cannot be reached. **Tag construction is INSIDE the wrap**
        deliberately: it reads configuration, so an unset tag key raises a configuration error,
        and outside the wrap that reaches the caller as a bare gateway fault carrying no code at
        all. The three conditions the failure mapping distinguishes are only distinguishable if
        each one actually arrives as itself. **The wrap below is load-bearing, not tidiness.** STS answers
        ``AccessDenied`` when the trust policy is wrong — a missing ``sts:TagSession`` renders,
        plans, applies and unit-tests green — and an unwrapped one reaches the failure mapping
        carrying that service code, where it is indistinguishable from the isolation model
        working. Every user would be told they lack a permission, for something only an operator
        can fix. Wrapping strips the service response, so the failure can only be classified by
        what it is.
    """
    session_name = role_session_name(caller.username)
    observability.info(
        "assuming the caller's role",
        username=caller.username,
        membership_slots=len(caller.memberships),
    )
    try:
        tags = session_tags(caller)
        response = _client("sts").assume_role(
            RoleArn=config.portal_role_arn(),
            RoleSessionName=session_name,
            DurationSeconds=config.ASSUME_ROLE_DURATION_SECONDS,
            Tags=tags,
        )
    except Exception as exc:
        raise IdentityUnavailableError(REASON_ASSUME_FAILED) from exc

    block = response["Credentials"]
    return AssumedCredentials(
        access_key_id=block["AccessKeyId"],
        secret_access_key=block["SecretAccessKey"],
        session_token=block["SessionToken"],
        expires_at=block["Expiration"],
    )


def assume_user_role(caller: UserIdentity, *, force: bool = False) -> AssumedCredentials:
    """Returns this caller's assumed session, from the per-container cache where possible.

    Args:
      caller: The verified identity.
      force: Skip the cache and re-assume. Used by the single expiry retry.

    Returns:
      The assumed session. Annotated at the call below because the tracing decorator is
      untyped, so the type is lost through it rather than absent from it.

    Raises:
      IdentityUnavailableError: If the role cannot be assumed.
      ConfigError: If the layer's configuration is unusable.
    """
    key = _cache_key(caller)
    if not force:
        cached = _CREDENTIAL_CACHE.get(key)
        if cached is not None and _usable(
            cached, datetime.datetime.now(datetime.UTC)
        ):
            return cached
    fresh: AssumedCredentials = _assume(caller)
    _CREDENTIAL_CACHE[key] = fresh
    return fresh


def reset_credential_cache() -> None:
    """Empties the per-container cache. Test fixtures only.

    Called by this package's fixture so a leak between TESTS cannot mask a leak between
    REQUESTS — the sequence that catches a wrongly-keyed cache only means something if each test
    starts empty.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    _CREDENTIAL_CACHE.clear()


class _RetryingClient:
    """A client that survives its credentials expiring, exactly once.

    The server-side successor to the browser's single credential retry, and it exists for the
    same reason: a session can expire between the check and the call, and re-driving the user's
    whole action to recover from something invisible to them is worse than one silent retry.

    **The retry is issued on a NEW client.** boto3 binds credentials at construction, so a proxy
    that re-assumes and then retries on the same object hits the same expired session, fails
    again, and reports a fault — fail-closed, but the retry does nothing while every test of it
    passes.

    It sees direct method calls only. A paginator, a waiter or anything reached through ``meta``
    holds its own reference and bypasses this; nothing here paginates today and a tripwire says
    so, rather than leaving the limit to be discovered by the spec that first needs one.

    One more edge, benign but worth naming: a caller that keeps the bound method — ``op =
    client.list_objects_v2`` then ``op()`` twice — makes its first attempt on the client that was
    current when it took the reference, so after a replacement every call pays an expiry and a
    re-assume before succeeding. Correct, and never the wrong identity; just wasteful. Call
    through the proxy rather than holding a method off it.
    """

    def __init__(self, service: str, caller: UserIdentity, client: Any) -> None:
        """Wraps a client for one caller.

        Args:
          service: The AWS service name, kept so a replacement can be built.
          caller: The identity to re-assume as.
          client: The client to proxy.

        Returns:
          None.

        Raises:
          None.
        """
        self._service = service
        self._caller = caller
        self._client = client

    def __getattr__(self, name: str) -> Any:
        """Proxies an operation, retrying once if the session expired underneath it.

        Private names are refused rather than proxied, which keeps this object's own state out
        of a route's reach and stops the lookup recursing during construction.

        Args:
          name: The attribute asked for.

        Returns:
          The attribute, or a callable wrapping it.

        Raises:
          AttributeError: If a private name is asked for.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        attribute = getattr(self._client, name)
        if not callable(attribute):
            return attribute

        def _call(*args: Any, **kwargs: Any) -> Any:
            try:
                return attribute(*args, **kwargs)
            except Exception as first:
                if aws_error_code(first) not in EXPIRED_CREDENTIAL_CODES:
                    raise
                self._client = _client(
                    self._service, assume_user_role(self._caller, force=True)
                )
                try:
                    return getattr(self._client, name)(*args, **kwargs)
                except Exception as second:
                    if aws_error_code(second) in EXPIRED_CREDENTIAL_CODES:
                        raise IdentityUnavailableError(
                            REASON_CREDENTIALS_EXPIRED
                        ) from second
                    raise

        return _call


def user_client(service: str, caller: UserIdentity) -> Any:
    """A client on THIS caller's assumed session — the only isolation-enforced door.

    The identity is a PARAMETER and may never be read from a request-scoped global: a module-level
    "current identity" is the credential leak this design most invites, wearing a different hat.

    Args:
      service: The AWS service name.
      caller: The verified identity to act as.

    Returns:
      A client carrying that caller's session tags.

    Raises:
      IdentityUnavailableError: If the role cannot be assumed.
      ConfigError: If the layer's configuration is unusable.
    """
    return _RetryingClient(service, caller, _client(service, assume_user_role(caller)))


def signing_client(
    service: str, caller: UserIdentity, *, covering: int
) -> tuple[Any, AssumedCredentials]:
    """A client AND the credentials backing it, from ONE assume, with a window it can cover.

    For presigning, and only for presigning. A presigned URL must not outlive the session that
    signed it — S3 rejects it at redemption, which reads as a permissions bug and not as an expiry,
    and on an upload it rejects *after* the bytes were sent.

    **The point is that this is one read.** Calling ``user_client`` and then ``assume_user_role``
    to learn the expiry is TWO reads, and they can disagree: a cached session with under half a
    minute left is refused as unusable, so the second read re-assumes and hands back a fresh hour
    while the first one's near-dead credential did the signing. The URL then carries an expiry a
    quarter of an hour out and dies in seconds. Measured, and it passes every offline test.

    **``covering`` is why this is not simply ``assume_user_role``.** The cache hands back any
    session with more than one request's life left, which is right for a request and wrong for a
    URL that outlives it: the clamp then signs for whatever happens to remain, so a window is a
    draw from roughly the whole hour rather than the number the route asked for. About a quarter of
    mints land under 900 s and about one in a hundred under a minute. A fresh session is one
    ``AssumeRole`` — tens of milliseconds — and it makes the window a property of the route instead
    of a property of when the request arrived.

    **The cost is bounded and it is worth stating as a rate, not just a latency.** The forced assume
    writes through to the cache, so it refreshes the container's session for every caller: a
    container under continuous presign traffic now consumes a session from 3600 s down to the
    window rather than down to the margin, which raises its assume rate by about a third. At worst
    one extra call per mint, and the cache is emphatically not defeated — see the test that a
    session already covering the window is reused. **A window longer than a whole session WOULD
    defeat it**, permanently and silently; that relation has a test of its own.

    Args:
      service: The AWS service name.
      caller: The verified identity to act as.
      covering: The window the URL needs, in seconds. A cached session with less than this left is
        replaced rather than clamped against.

    Returns:
      The client, and the credentials it is signing with — which have at least ``covering`` seconds
      left unless the ceiling itself is shorter, and the ceiling is an AWS one.

    Raises:
      IdentityUnavailableError: If the role cannot be assumed.
      ConfigError: If the layer's configuration is unusable.
    """
    credentials = assume_user_role(caller)
    if _remaining(credentials) < covering:
        credentials = assume_user_role(caller, force=True)
    return _RetryingClient(service, caller, _client(service, credentials)), credentials


def _remaining(credentials: AssumedCredentials) -> float:
    """How long a session has left, in seconds.

    Args:
      credentials: The session.

    Returns:
      Seconds remaining; negative once it has expired.

    Raises:
      TypeError: If the expiry is naive — see ``_usable``.
    """
    return (credentials.expires_at - datetime.datetime.now(datetime.UTC)).total_seconds()


def api_client(service: str) -> Any:
    """A client on the execution role, for a route that declared the API plane.

    The check runs BEFORE the client is built, so a violation reaches no AWS service and costs no
    request. Construct-then-check would leave a usable client in the hands of a route that was
    about to be refused, and the refusal is the only thing standing between that route and the
    execution role's own identity.

    **It has no caller in shipped code today, and that is a deviation worth naming rather than
    leaving to be noticed.** The spec asks that the assume-role call itself be made "through the
    API plane", and it is — on the execution role's credentials — but through the private
    constructor rather than through this door. It cannot be otherwise: the guard refuses any route
    that has not declared the plane, no route declares it, and assuming is framework work that
    happens for every route including the ones that must never reach the execution role. So the
    declaration mechanism ships with no live subject and is exercised by tests alone until the
    first queue write arrives, which is the route-declared use it was built for.

    Args:
      service: The AWS service name.

    Returns:
      A client on the execution role's credentials.

    Raises:
      PlaneViolationError: If the running route did not declare the API plane, or if no route is
        dispatching at all.
    """
    planes.require(planes.Plane.API)
    return _client(service)


def for_request(caller: Principal) -> UserIdentity:
    """Builds the identity this request acts as, and stamps it on every record the request emits.

    The stamp is here rather than around the assume, and the placement is the point: the assume
    is cached, so a stamp inside it would fire on a cold cache and on nothing else — leaving the
    overwhelming majority of requests, the warm ones, unattributable in the log store while every
    offline test passed.

    Args:
      caller: The verified caller.

    Returns:
      The identity, carrying the username and every occupied membership slot.

    Raises:
      ConfigError: If the slot count is unset or unusable.
    """
    acting_as = identity_from(caller)
    observability.stamp(username=acting_as.username)
    return acting_as
