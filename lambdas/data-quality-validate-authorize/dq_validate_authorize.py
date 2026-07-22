"""data-quality validate-authorize — the control plane's security boundary (SPEC-109).

The first verb. It is the ONLY place the actor is established: the request's ID token is
verified offline against the User Pool JWKS and the actor comes from the verified
``cognito:username`` claim — NEVER from a body field (the envelope carries no username at
all, SPEC-109 FR-001).

It then authorizes read access to the requested location and validates the report
destination:

- **personal** — the bucket must be the user-space bucket and the normalized location must
  sit under ``{actor}/``;
- **shared** — the registry record must be an ACTIVE space with the actor in ``members``
  (``cpcommon.registry.is_active_member``), the bucket must be the shared-space bucket, and
  the location must sit under ``{spaceName}/``.

"Active" is the SPACE's provisioning status, NOT SPEC-073's per-member Pending/Active join
chip: SPEC-073 grants access at add time, so a **Pending member passes** (a test pins this
so nobody "fixes" it later).

The identity contract: from this state onward the threaded object carries ``requestId`` and
``actor`` KEYS. The terminal ``RecordSuccess``/``RecordFailure`` Pass states read
``$.requestId``/``$.actor``, and a Pass state's JSONPath hard-fails on an ABSENT key
(``States.Runtime``) — uncatchable, so it would skip ``NotifyFailure`` and leave the user
with no notification at all. A null value is fine; a missing key is fatal.
"""

import logging
import posixpath

from cpcommon import auth, config, events
from cpcommon import observability
from cpcommon import registry as reg
from cpcommon.errors import TerminalError
from dqcommon import messages, notify
from dqcommon.config import MARKER_BASENAME, RESERVED_PREFIXES

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one data-quality run is nine
# invocations, and they are only one queryable set if they share a service name
# (SPEC-127 FR-003). The per-verb identity rides as the `verb` field on each span.
observability.init(service="data-quality")

#: Where this arc writes its reports, relative to the space root.
REPORTS_PREFIX = "_data-quality-reports"


def _normalize(location: str) -> str:
    """Collapse a key to its canonical form, neutralizing traversal.

    ``posixpath.normpath`` resolves ``.``/``..`` segments, so a location that tries to
    climb out of its space (``alice/../bob/secrets``) normalizes to a path that simply
    fails the space-prefix check below — traversal can't sneak past a string comparison
    on the raw input. A leading ``/`` is stripped (S3 keys never start with one).
    """
    collapsed = posixpath.normpath(location.strip().lstrip("/"))
    # normpath turns "" and "." into "."; treat both as empty (an unusable location).
    return "" if collapsed == "." else collapsed


def _authorize(actor: str, space: dict, location: str) -> str:
    """Return the normalized location, or raise a terminal ``forbidden``."""
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
            # Deliberately one reason for "no such space" and "not a member": telling the
            # caller which is a membership oracle.
            raise TerminalError(messages.FORBIDDEN, f"{actor!r} is not an active member of {prefix!r}")
        if not _within(normalized, prefix):
            raise TerminalError(messages.FORBIDDEN, "location escapes the shared space")
        return normalized

    raise TerminalError(messages.FORBIDDEN, f"unknown space kind {kind!r}")


def _within(normalized: str, space_root: str) -> bool:
    """True iff ``normalized`` is the space root itself or sits under it."""
    return normalized == space_root or normalized.startswith(f"{space_root}/")


def _validate_destination(space_root: str, request_id: str) -> str:
    """Return the report destination prefix, or raise if it isn't safe to write.

    Defence in depth behind the execution role's explicit Deny (SPEC-109 FR-006): the
    destination is derived here, not supplied, so this mostly guards against a future
    caller-supplied destination and against the reserved prefixes drifting.
    """
    destination = f"{space_root}/{REPORTS_PREFIX}/{request_id}/"
    first_segment = destination.split("/")[1] if "/" in destination else ""
    # The reports prefix is itself reserved (it is ours), so only a NON-reports collision
    # is a problem — i.e. the derived destination must land in our own reserved folder.
    if first_segment != REPORTS_PREFIX:
        raise TerminalError(messages.FORBIDDEN, f"report destination {destination!r} is not the reports prefix")
    return destination


def _check_source_not_reserved(normalized: str, space_root: str) -> None:
    """A check may not target a reserved sub-tree or the space marker."""
    rel = normalized[len(space_root) :].strip("/") if normalized.startswith(space_root) else normalized
    if not rel:
        return  # the space root itself is a legitimate (if broad) folder target
    first = rel.split("/")[0]
    if first in RESERVED_PREFIXES:
        raise TerminalError(messages.FORBIDDEN, f"{first!r} is a reserved prefix and cannot be checked")
    if rel == MARKER_BASENAME:
        raise TerminalError(messages.FORBIDDEN, "the space marker is not data")


def _validate_and_authorize(event) -> dict:
    req = events.parse_sqs_request(event, reason=messages.UNAUTHORIZED)

    # THE ACTOR IS BOUND FIRST, BEFORE THE SHAPE CHECKS, and the order is deliberate
    # (SPEC-114 FR-002). It used to run after them, which meant a malformed envelope raised
    # `invalid_request` with no actor bound — and this verb is the ONE place a failure
    # cannot fall back to the NotifyFailure state, because ValidateFailureSeed seeds
    # `actor: null` for exactly this case. Every shape terminal would have notified nobody.
    # Verifying the token first costs nothing (it is offline against the cached JWKS) and
    # gives every failure below a recipient. An `unauthorized` from HERE still has none —
    # a caller who cannot prove who they are has no inbox we may write to — which is why
    # this line stays outside the try.
    actor = auth.verified_username(req.get("idToken"))

    # From here the actor is known, so a terminal failure notifies them (best-effort)
    # before the SFN Catch records it. The decorator cannot do this for us: its `event` is
    # the raw SQS ARRAY, which carries no actor field to address.
    try:
        # Shape first, so a malformed envelope is a typed terminal rather than a bare
        # KeyError the SFN records as an opaque failure (SPEC-083 FR-002).
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
        notify.emit_failure(
            {
                "actor": actor,
                # The body's own location, not the normalized one — normalization may not
                # have run. It is the user's own submitted value being echoed back to that
                # same verified user, so there is no cross-inbox injection here.
                "location": req.get("location"),
                "requestId": req.get("requestId"),
            },
            err,
        )
        raise

    logger.info("authorized %s for %s/%s", actor, space.get("bucket"), normalized)
    return {
        "requestId": request_id,
        "actor": actor,
        "space": {"kind": space["kind"], "bucket": space["bucket"], "prefix": f"{space_root}/"},
        "location": normalized,
        "reportPrefix": destination,
        # SEEDED NULL HERE, FILLED BY assemble-report. It exists from the FIRST verb purely
        # so the terminal RecordFailure Pass state can read $.reportKey on every path: a
        # Pass state's JSONPath hard-fails on an ABSENT key with an uncatchable
        # States.Runtime, which would kill the execution before NotifyFailure and leave the
        # user with no notification at all — the same trap $.location fell into (see
        # ValidateFailureSeed's comment in the ASL). A null VALUE is fine; a missing key is
        # fatal. Every verb threads the state with dict(event), so seeding it once is
        # enough. What it buys: notify-failure can tell a post-report cleanup failure from
        # a real one and stay quiet, because the user already has their success
        # notification and their report (SPEC-114).
        "reportKey": None,
    }


# @traced is OUTERMOST, above @notifies_on_failure, deliberately: notifies_on_failure
# catches on its way out, so if it were outermost the span would close status="ok" on an
# invocation that actually failed and notified. Outermost traced sees the exception the
# handler really raised.
@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Verify the caller, authorize the location, and emit the threaded request object.

    ``notify_terminal=False``: a ``TerminalError`` is notified inside
    ``_validate_and_authorize``, which knows the actor. The decorator's own event is the raw
    SQS array and could not address one. It still covers UNEXPECTED exceptions, where it
    correctly no-ops for want of a recipient — the SFN records those either way.
    """
    return _validate_and_authorize(event)
