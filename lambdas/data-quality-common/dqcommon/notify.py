"""Best-effort outcome notifications for the data-quality pipeline (SPEC-114).

The shared primitives (``emit_notification`` + the ``notifies_on_failure`` skeleton) live
in ``cpcommon.notify`` (SPEC-107). This module holds what is data-quality-specific: the
actor is always the sole recipient (one recipient, like Table Builder — not Table Share's
fan-out), the wording comes from ``dqcommon.messages``, and the success notification
carries a LINK to the SPEC-113 report view.

THE LINK IS THE POINT, not a nicety. SPEC-113 FR-004 hides the ``_data-quality-reports``
folder from the file browser, so a notification that only names a key leaves the user with
no route to their report at all — the only other way in is typing the URL by hand.

A missed notification must never change or fail the pipeline outcome, so every emit goes
through ``cpcommon.notify.emit_notification`` (catches, logs, never raises; a no-op when
the queue URL is unset).
"""

import logging

from cpcommon.errors import TerminalError
from cpcommon.notify import emit_notification
from cpcommon.notify import notifies_on_failure as _notifies_on_failure

from .messages import UNEXPECTED_ERROR, failure_message, success_message

logger = logging.getLogger()

__all__ = [
    "FAILURE_STEP",
    "SUCCESS_STEP",
    "emit_completed",
    "emit_failure",
    "emit_notification",
    "emit_unexpected",
    "notifies_on_failure",
    "report_link",
]

# ── FIFO dedup steps ─────────────────────────────────────────────────────────
# ONE TOKEN PER OUTCOME, NOT ONE PER VERB, and this is load-bearing rather than a
# simplification. Two different code paths emit the failure notification for the SAME
# failure: `notifies_on_failure` (inside the verb, on its way out) and the NotifyFailure
# state (after the Catch, at the end of the execution). NotifyFailure runs once the
# execution has already left the failing verb and CANNOT KNOW WHICH VERB RAISED — so a
# per-verb token would give the two emits different dedup ids and the user would get TWO
# notifications for one failure.
#
# THE COLLAPSE DEPENDS ON SQS FIFO'S 5-MINUTE DEDUPLICATION WINDOW (SPEC-114 FR-004). The
# two emits land seconds apart — the decorator's on the way out of the Lambda, NotifyFailure's
# after DropTempTablesOnFailure and RecordFailure — so they fall inside the window
# comfortably. If a future change put minutes between them (a long Wait on the failure
# path, a retry storm in cleanup), the window would expire and the user would get both.
#
# Only one verb can fail per execution, so one token per outcome still distinguishes a
# failure notification from a success one, which is all the dedup id has to do.
FAILURE_STEP = "failure"
SUCCESS_STEP = "completed"

#: The SPEC-113 report route. The space segment is part of the ROUTE, not derived.
_REPORT_ROUTE = "/data-quality"


def _dedup(request_id, step: str) -> str | None:
    """FIFO dedup id ``{requestId}:{step}``; ``None`` without a requestId (content dedup)."""
    return f"{request_id}:{step}" if request_id else None


def report_link(actor: str, space: dict, request_id: str) -> str | None:
    """The in-app path to this request's report view, or ``None`` when none is safe to mint.

    ``/data-quality/{space}/{requestId}`` — the SPACE IS IN THE PATH because the report
    lives at ``{space}/_data-quality-reports/{requestId}/report.json``. A link carrying only
    the requestId could not locate a shared-space report, so it would deep-link the user to
    a permanent "not found" — worse than no link, because it looks like a broken product
    rather than a missing feature.

    IT MIRRORS THE VIEW'S RESOLUTION PRECEDENCE (SPEC-113 FR-005,
    ``useDataQualityReport.resolveSpace``): the reader resolves a segment equal to the
    viewer's own username as PERSONAL and only consults shared-space names when the segment
    differs. So a SHARED space whose name happens to equal the actor's username is
    unreachable through this route by construction — the view would send the actor to their
    own personal space and 404. Returning ``None`` there is the honest answer: the
    notification still tells them the check finished, it just cannot offer a working link.
    Sending one anyway would be the "permanent not found" this function exists to avoid.
    """
    name = (space or {}).get("prefix") or ""
    name = str(name).strip("/")
    if not name or not request_id or not actor:
        return None
    # Belt and braces on values that reach a user's inbox as a clickable path. Usernames and
    # space names are already catalog-safe (^[a-z][a-z0-9_]{2,62}$, SPEC-033) and requestIds
    # are uuids, so this rejects nothing the pipeline legitimately produces — it is here so a
    # future change to either format cannot quietly put a traversal or a query string into a
    # link. The browser re-checks with isSafeInAppPath (SPEC-058); this is the producer half.
    if not _is_plain_segment(name) or not _is_plain_segment(str(request_id)):
        logger.warning("refusing to build a report link from unexpected segments")
        return None
    # BOTH KINDS ARE CHECKED, not just the shared one, because the view's rule is a single
    # equality test and each kind falls the wrong side of it in a different way:
    #
    #   personal, name != actor  -> the view sees a segment ≠ its username, so it looks the
    #                               name up among SHARED spaces and reads the wrong bucket.
    #   shared,   name == actor  -> the view sees its own username, resolves PERSONAL, and
    #                               404s in a space that never held this report.
    #
    # validate-authorize already rejects the first (a personal space's prefix must equal the
    # actor), so it is unreachable today — it is guarded anyway because this function's
    # correctness must not depend on a check in a different verb continuing to exist.
    kind = (space or {}).get("kind")
    if kind == "personal" and name != actor:
        return None
    if kind == "shared" and name == actor:
        return None
    if kind not in ("personal", "shared"):
        return None
    return f"{_REPORT_ROUTE}/{name}/{request_id}"


def _is_plain_segment(value: str) -> bool:
    """True iff ``value`` is a single path segment with nothing that could change a URL."""
    return bool(value) and all(c.isalnum() or c in "-_" for c in value)


def emit_completed(event: dict) -> None:
    """Emit the actor-addressed SUCCESS notification, with the report link (best-effort).

    Reads only the small summary ``assemble-report`` threads onward — never the report
    document, which stays a file.
    """
    space = event.get("space") or {}
    actor = event.get("actor", "")
    emit_notification(
        actor,
        success_message(
            event.get("location", ""),
            event.get("verdict", ""),
            event.get("topIssues") or [],
            has_approximate=bool(event.get("hasApproximateFigures")),
            has_incomplete=bool(event.get("hasIncompleteFigures")),
        ),
        dedup_id=_dedup(event.get("requestId"), SUCCESS_STEP),
        link=report_link(actor, space, event.get("requestId", "")),
    )


def emit_failure(event: dict, err: TerminalError, step: str = FAILURE_STEP) -> None:
    """Emit the actor-addressed failure notification for a verb's ``TerminalError``.

    Best-effort. ``err.detail`` (raw Athena/AWS text) is deliberately NOT forwarded — it
    stays on the exception for the logs and the SFN record (SPEC-106 FR-008). ``err.tokens``
    IS forwarded: those are the per-request values the message body's {object}/{count}
    markers need, and they are the reason this emit — not NotifyFailure's — is the one the
    user should receive (see the module note on dedup).

    A failure raised before the actor is bound has no recipient, so the emit is a no-op
    rather than a lost message.
    """
    del step  # one token per outcome; kept in the signature for the cpcommon seam
    emit_notification(
        event.get("actor", "") if isinstance(event, dict) else "",
        failure_message(err.reason, _location(event), **getattr(err, "tokens", {})),
        dedup_id=_dedup(_request_id(event), FAILURE_STEP),
    )


def emit_unexpected(event, step: str = FAILURE_STEP) -> None:
    """Emit the actor-addressed failure notification for an UNEXPECTED verb exception.

    Best-effort, generic wording (no leaked internals). Tolerates a non-dict event —
    validate-authorize's input is the raw SQS array, and a failure there happens before the
    actor is bound, so there is no recipient and the emit is a no-op.
    """
    del step  # see emit_failure
    data = event if isinstance(event, dict) else {}
    emit_notification(
        data.get("actor", ""),
        failure_message(UNEXPECTED_ERROR, _location(data)),
        dedup_id=_dedup(_request_id(data), FAILURE_STEP),
    )


def _location(event) -> str:
    """The checked location, or "" — never raises on a non-dict or a null field."""
    if not isinstance(event, dict):
        return ""
    return str(event.get("location") or "")


def _request_id(event):
    """The requestId, or None — never raises on a non-dict."""
    return event.get("requestId") if isinstance(event, dict) else None


def notifies_on_failure(step: str = FAILURE_STEP, *, notify_terminal: bool = True):
    """data-quality ``notifies_on_failure`` — binds the domain emitters into the shared
    ``cpcommon.notify`` skeleton (SPEC-107).

    By default a verb's ``TerminalError`` notifies the actor HERE, so worker verbs need no
    ``try/except TerminalError`` of their own. ``notify_terminal=False`` for
    validate-authorize, whose failures happen before the actor is bound — notifying from
    there would address a recipient the token has not yet proven.
    """
    return _notifies_on_failure(step, emit_unexpected, emit_failure if notify_terminal else None)
