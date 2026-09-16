"""data-quality validate-authorize — the control plane's security boundary.

The first verb, and the only place the actor is established: it comes from the ``identity`` block
the API stamped after verifying the caller's bearer, never from a body field — the envelope
carries no username at all, and the flat field beside the block holds a raw token only on a
message enqueued before the API stopped sending one.

It then authorizes read access to the requested location and validates the report destination. A
personal space must be the user-space bucket with the location under the actor's own prefix. A
shared space must have an active registry record listing the actor, be the shared-space bucket,
and have the location under the space's prefix. Active is the space's provisioning status, not a
member's pending or active join chip: access is granted at add time, so a pending member passes,
and a test pins that so nobody "fixes" it later.

The identity contract: from this state onward the threaded object carries the request id and
actor keys. The terminal states read them, and a Pass state's JSONPath hard-fails on an absent
key with an uncatchable runtime error, which would skip the notify state and leave the user with
no notification at all. A null value is fine; a missing key is fatal.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  REPORTS_PREFIX: Where this arc writes its reports, relative to the space root.
"""

import logging
import posixpath

from cpcommon import actor as cpactor
from cpcommon import config, events, observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from dqcommon import messages, notify
from dqcommon.config import MARKER_BASENAME, RESERVED_PREFIXES

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

REPORTS_PREFIX = "_data-quality-reports"


def _normalize(location: str) -> str:
    """Collapses a key to its canonical form, neutralising traversal.

    Path normalisation resolves relative segments, so a location that tries to climb out of its
    space collapses to a path that simply fails the space-prefix check below — traversal cannot
    sneak past a string comparison on the raw input. A leading slash is stripped, since S3 keys
    never start with one, and both the empty string and a bare dot are treated as empty, which is
    an unusable location.

    Args:
      location: The raw location from the request body.

    Returns:
      The canonical key, or "" when it is unusable.

    Raises:
      None.
    """
    collapsed = posixpath.normpath(location.strip().lstrip("/"))
    return "" if collapsed == "." else collapsed


@observability.step("authorize")
def _authorize(actor: str, space: dict, location: str) -> str:
    """Authorizes the actor for the requested location and returns its canonical form.

    The shared-space failure uses one reason for "no such space" and "not a member", deliberately:
    telling the caller which is a membership oracle.

    Args:
      actor: The verified username.
      space: The request's space, carrying its kind, bucket and prefix.
      location: The raw location from the request body.

    Returns:
      The normalised location.

    Raises:
      TerminalError: ``forbidden`` on an empty location, the wrong bucket, a personal space that
        is not the actor's own, a shared space the actor is not an active member of, a location
        that escapes its space, or an unknown space kind.
    """
    kind = space.get("kind")
    bucket = space.get("bucket")
    prefix = (space.get("prefix") or "").strip("/")
    normalized = _normalize(location)
    if not normalized:
        raise TerminalError(messages.FORBIDDEN, "empty location")

    if kind == "personal":
        if bucket != config.USER_SPACE_BUCKET:
            raise TerminalError(messages.FORBIDDEN, "personal space must be the user-space bucket")
        if prefix != actor:
            raise TerminalError(messages.FORBIDDEN, "personal space must be the actor's own")
        if not _within(normalized, actor):
            raise TerminalError(messages.FORBIDDEN, "location escapes the personal space")
        return normalized

    if kind == "shared":
        if bucket != config.SHARED_SPACE_BUCKET:
            raise TerminalError(messages.FORBIDDEN, "shared space must be the shared-space bucket")
        if not reg.is_active_member(reg.load(prefix), actor):
            raise TerminalError(messages.FORBIDDEN, f"{actor!r} is not an active member of {prefix!r}")
        if not _within(normalized, prefix):
            raise TerminalError(messages.FORBIDDEN, "location escapes the shared space")
        return normalized

    raise TerminalError(messages.FORBIDDEN, f"unknown space kind {kind!r}")


def _within(normalized: str, space_root: str) -> bool:
    """Reports whether a normalised location is the space root itself or sits under it.

    Args:
      normalized: The canonical location.
      space_root: The space's root prefix.

    Returns:
      True when the location is inside the space.

    Raises:
      None.
    """
    return normalized == space_root or normalized.startswith(f"{space_root}/")


@observability.step("validate-destination")
def _validate_destination(space_root: str, request_id: str) -> str:
    """Derives the report destination prefix and confirms it is safe to write.

    Defence in depth behind the execution role's explicit deny: the destination is derived here
    rather than supplied, so this mostly guards against a future caller-supplied destination and
    against the reserved prefixes drifting. The reports prefix is itself reserved, being ours, so
    only a collision with a different reserved folder is a problem.

    Args:
      space_root: The space's root prefix.
      request_id: The run's request id.

    Returns:
      The destination prefix.

    Raises:
      TerminalError: ``forbidden`` when the derived destination is not the reports prefix.
    """
    destination = f"{space_root}/{REPORTS_PREFIX}/{request_id}/"
    first_segment = destination.split("/")[1] if "/" in destination else ""
    if first_segment != REPORTS_PREFIX:
        raise TerminalError(messages.FORBIDDEN, f"report destination {destination!r} is not the reports prefix")
    return destination


def _check_source_not_reserved(normalized: str, space_root: str) -> None:
    """Refuses a check that targets the space root, a reserved sub-tree, or the space marker.

    **The space root is not a data folder**, and refusing it is the whole of the first arm. A
    check builds an external table over its target and Athena reads a table's location
    RECURSIVELY, so a check at the top of a space reads the folders the portal keeps there — the
    Athena results folder, archive receipts, shared-table copies — alongside whatever the user
    meant. It does not fail: it succeeds, reporting row counts and null ratios over the portal's
    own bookkeeping, and the user acts on those numbers. Succeeding is what makes it worth
    refusing rather than qualifying on the report. The results folder is the sharpest case,
    because this run's own query output lands inside it while the run is still going.

    Excluding those sub-trees from the LISTING does not help and is worth saying, because it
    looks like it should: the manifest is what the check knows about, but the table's location is
    the target folder, and Athena reads what is under it rather than what the manifest lists.

    A single file that sits at the root is a different case and stays allowed — its target is the
    file, not the root, and its queries carry a path predicate that makes its numbers its own.

    Table-builder refuses the identical shape for the identical reason; the two do not share a
    validator because the planes are independent, so a change to the rule belongs in both.

    Args:
      normalized: The canonical location.
      space_root: The space's root prefix.

    Returns:
      None.

    Raises:
      TerminalError: ``location_is_space_root`` when the target IS the root,
        ``forbidden`` when the target's first segment is reserved or the target is the space
        marker.
    """
    rel = normalized[len(space_root) :].strip("/") if normalized.startswith(space_root) else normalized
    if not rel:
        raise TerminalError(
            messages.LOCATION_IS_SPACE_ROOT,
            "a check cannot be run on the top of a space, which also holds query results, "
            "archive receipts and shared tables",
        )
    first = rel.split("/")[0]
    if first in RESERVED_PREFIXES:
        raise TerminalError(messages.FORBIDDEN, f"{first!r} is a reserved prefix and cannot be checked")
    if rel == MARKER_BASENAME:
        raise TerminalError(messages.FORBIDDEN, "the space marker is not data")


def _validate_and_authorize(event) -> dict:
    """Reads the trusted actor, authorizes the location, and emits the threaded request object.

    The actor is bound first, before the shape checks, and the order is deliberate. It used to run
    after them, which meant a malformed envelope raised with no actor bound — and this verb is the
    one place a failure cannot fall back to the notify state, because the failure seed supplies a
    null actor for exactly that case, so every shape terminal would have notified nobody.
    Reading the block first costs nothing — it is a field read, not a network call — and gives
    every failure below a recipient. An unauthorized failure from the read itself still has none:
    a message that names no trustworthy actor has no inbox we may write to, which is why that
    line stays outside the guard.

    Shape checks come before authorization so a malformed envelope is a typed terminal rather than
    a bare error the state machine records as opaque.

    The terminal is recorded and notified in one place rather than at each of the raise sites: a
    narrative line added by hand next to a raise is one the next raise will be added without. The
    reason is the constant's own value, never scraped out of the rendered prose, and the detail is
    safe to record for every raise site in this verb — they interpolate locations, buckets,
    prefixes and the actor, and nothing read out of a file. The notification echoes the body's own
    location rather than the normalised one, because normalisation may not have run; it is the
    user's own submitted value going back to that same verified user, so there is no cross-inbox
    injection.

    The report key is seeded null here and filled by the report verb. It exists from the first
    verb purely so the terminal failure state can read it on every path: an absent key would kill
    the execution before the notify state and leave the user with no notification at all. Every
    verb threads the state by copying, so seeding it once is enough. What it buys is that the
    notify verb can tell a post-report cleanup failure from a real one and stay quiet.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.

    Returns:
      The validated request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the actor is bound, then ``invalid_request`` or
        ``forbidden``.
      TransientError: On a retryable S3 fault loading the registry.
    """
    req = events.parse_sqs_request(event, reason=messages.UNAUTHORIZED)

    who = cpactor.trusted_actor(req)
    observability.stamp(
        actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
    )
    actor = who.username

    try:
        request_id = events.require(req, "requestId", reason=messages.INVALID_REQUEST)
        space = req.get("space")
        if not isinstance(space, dict):
            raise TerminalError(messages.INVALID_REQUEST, "missing space")
        events.require(req, "space", "kind", reason=messages.INVALID_REQUEST)
        events.require(req, "space", "bucket", reason=messages.INVALID_REQUEST)
        events.require(req, "space", "prefix", reason=messages.INVALID_REQUEST)
        location = events.require(req, "location", reason=messages.INVALID_REQUEST)

        normalized = _authorize(actor, space, location)
        space_root = (space.get("prefix") or "").strip("/")
        _check_source_not_reserved(normalized, space_root)
        destination = _validate_destination(space_root, request_id)
    except TerminalError as err:
        observability.error(
            "authorization failed",
            step="authorize",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
            actor=actor,
        )
        notify.emit_failure(
            {
                "actor": actor,
                "location": req.get("location"),
                "requestId": req.get("requestId"),
            },
            err,
        )
        raise

    logger.info("authorized %s for %s/%s", actor, space.get("bucket"), normalized)
    observability.info(
        "authorized",
        actor=actor,
        space=space_root,
        space_kind="own" if space.get("kind") == "personal" else "shared",
        bucket=space.get("bucket"),
        location=normalized,
        report_prefix=destination,
    )
    return {
        "traceparent": observability.run_traceparent(),
        "requestId": request_id,
        "actor": actor,
        "space": {"kind": space["kind"], "bucket": space["bucket"], "prefix": f"{space_root}/"},
        "location": normalized,
        "reportPrefix": destination,
        "reportKey": None,
    }


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Verifies the caller, authorizes the location, and emits the threaded request object.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    Terminal notification is turned off at the decorator because a terminal error is notified
    inside the orchestration below, which knows the actor — the decorator's own event is the raw
    SQS array and could not address one. It still covers unexpected exceptions, where it correctly
    no-ops for want of a recipient; the state machine records those either way.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated request.

    Raises:
      TerminalError: ``unauthorized``, ``invalid_request`` or ``forbidden``.
      TransientError: On a retryable S3 fault loading the registry.
    """
    return _validate_and_authorize(event)
