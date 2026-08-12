"""notify — the plane's only SUCCESS producer, for both of its modes.

Three outcomes, three states, one verb: an archive that completed, a restore that has been
requested and is now waiting hours, and a restore that finished.

**Every other terminal outcome is already told by somebody else, and that is why this verb is
small.** FR-006 names nine; the six refusals — ``archive_not_found``, ``archive_incomplete``,
``destination_occupied``, ``restore_incomplete``, ``restore_timed_out`` and the rest — are reason
codes in ``arcommon.messages``, emitted once by ``notifies_on_failure`` on the verb that raised or
by the machine's own ``NotifyFailure``. A second producer for them would be the duplicate the
one-token-per-outcome rule (SPEC-114) exists to prevent.

**THE ASL SEEDS WHICH OUTCOME THIS IS**, rather than the verb inferring it from the state's shape.
The three call sites are distinguishable only by where they sit in the machine — the same keys are
present at all three — so inferring would mean guessing, and a restore-started message on a
finished restore is worse than no message. SPEC-171 settled the same question the same way for its
two destination guards.

**Nothing here can fail the run.** By the time any of these states runs the work has happened; a
raise would replace a delivered archive with a failed one, and on the archive arm the source is
already deleted. That is why the handler has no ``@notifies_on_failure`` — the decorator would
report a failure of the notifier as a failure of the archive — and why every state that invokes it
carries ``ResultPath: null``, so the verb cannot reshape the object the rest of the machine reads.

The service name is the control plane, not the function, so one archive's invocations stay one
queryable set. The per-verb identity rides as the ``verb`` field.

Attributes:
  _OUTCOMES: The outcome tokens the ASL may seed, and what each one emits.
"""

import logging

from arcommon import notify
from cpcommon import observability

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="archive")

_OUTCOMES = ("archived", "restore_started", "restored")


@observability.traced("notify")
def handler(event, context) -> dict:
    """Step Functions entry point: says the one thing this point in the machine knows.

    ``@traced`` is the only decorator, for the reason in the module docstring.

    Args:
      event: The seeded summary — ``{outcome, requestId, actor, space, objectCount, totalBytes}``.
      context: The Lambda context, unused.

    Returns:
      An empty dict. The invoking states all carry ``ResultPath: null``, so nothing is threaded
      onward and the running object is untouched.

    Raises:
      None.
    """
    return _notify(event)


def _notify(event) -> dict:
    """Emits the one message the seeded outcome calls for.

    An unrecognised or absent outcome is a logged no-op rather than a raise: this verb runs on a
    run that has otherwise succeeded, and the only thing worse than a missing notification here
    would be turning one into a failed archive.

    Args:
      event: The seeded summary.

    Returns:
      An empty dict.

    Raises:
      None. The emit itself already swallows, and composing a message cannot fail on values this
      shape — but the whole body is guarded anyway, because the alternative to a missed message
      is a successful run reported as a failure.
    """
    summary = event if isinstance(event, dict) else {}
    outcome = summary.get("outcome")
    actor = summary.get("actor") or ""
    space = summary.get("space") if isinstance(summary.get("space"), dict) else {}
    objects = summary.get("objectCount") or 0
    total_bytes = summary.get("totalBytes") or 0

    if outcome not in _OUTCOMES or not actor:
        logger.warning("nothing to notify: outcome=%r, actor=%r", outcome, actor)
        observability.warning(
            "no outcome to notify", outcome=str(outcome), actor=actor, notified=False
        )
        return {}

    try:
        if outcome == "archived":
            notify.emit_archived(actor, space, summary.get("requestId") or "", objects, total_bytes)
        elif outcome == "restore_started":
            notify.emit_restore_started(actor, objects)
        else:
            notify.emit_restored(actor, space, objects, total_bytes)
    except Exception:
        logger.exception("could not notify the %s outcome; the run is unaffected", outcome)
        observability.warning("outcome notification failed", outcome=outcome, notified=False)
        return {}

    logger.info("notified %s of the %s outcome (%d object(s))", actor, outcome, objects)
    observability.info(
        "outcome notified",
        outcome=outcome,
        actor=actor,
        objects=objects,
        bytes=total_bytes,
        notified=True,
    )
    return {}
