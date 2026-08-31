"""backfill-ever-active: the one-shot that stamps the durable ever-active fact.

Retention keys on ``everActive`` rather than on live ``status``, because a status moves
``active -> deleting -> failed`` while the question the field answers — was this space ever
usable by anyone — cannot. ``finalize`` stamps it going forward; every record written before
that shipped carries nothing, and a delete reaching one of those would take the destroying route
against a live workspace. This walks the registry once and closes that.

It is not a verb. Nothing enqueues it and it sits on no state machine: it is invoked directly,
once, from CI, before the delete verb's new behaviour deploys. There is no enable switch on that
verb, so the ordering is the deploy order and this has to have run first.

Three modes, because enumerating and stamping are different acts and the middle one is a
judgement no rule can make. ``report`` writes nothing and describes what it found. ``apply``
stamps the records whose status decides them. ``stamp`` takes one name, for the records an
operator has to disposition by hand.

**A ``failed`` record cannot be classified automatically, and the discriminator is the space's
resources rather than its roster.** A failed *delete* was ever-active and must be stamped; a
failed *create* must not be, or its name is burned forever. The roster cannot tell them apart —
a failed create can have been added to, and a failed delete of a single-member space is
single-member too, since the status write preserves the members.

What the report offers instead is three facts, and they are not equally strong. **The recorded
reason is the primary discriminator**: it names either a provisioning fault or a teardown one,
and only one kind of run writes each. The resource facts corroborate it and neither is decisive
alone. A create fails at any of its steps, and the marker object and the database are written
early — so a failed create can hold both, which is exactly the quadrant a delete that barely
started also occupies. What no failed create has is *data*, which is why the object signal
excludes the marker. A human reads all three and decides.

Attributes:
  STAMPABLE_STATUSES: The statuses ``apply`` stamps unattended. ``active`` alone, because it
    is the only status that cannot lie: a live space is by definition one that was usable.
    ``deleting`` was specified here too, on the reasoning that only the delete verb writes it
    so it must name a space that had reached ``active``. **The second half does not follow and
    the record is now a human decision.** Deleting is gated on ownership and on nothing else —
    neither the validator nor the authorizer looks at status — so an owner may delete their own
    failed or still-provisioning create, and the verb writes ``deleting`` before it tears
    anything down. An invocation that dies rather than raising leaves that status permanently,
    because the machine records a failure without writing one. So a ``deleting`` record can
    name a space that was never usable, and stamping it unattended would burn its name forever
    with nobody ever seeing it.
  NEVER_STAMP_STATUSES: Statuses whose answer is already known, reported with that verdict
    rather than as something to weigh. Only ``reserve`` writes ``provisioning``, so such a
    record is by construction a create that never reached active.
  REGISTRY_PREFIX: Where the registry's control objects live in the admin bucket.
  MODES: The modes the handler accepts.
  MARKER_BASENAME: The object every space carries to mark its prefix. Excluded from the
    data signal because a create writes it before almost everything else, so counting it
    would report every failed create as holding data.
"""

import logging

import registry as reg
from cpcommon import clients, observability
from cpcommon import config as cpconfig

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="shared-space")

STAMPABLE_STATUSES = ("active",)
NEVER_STAMP_STATUSES = ("provisioning",)
REGISTRY_PREFIX = "shared-spaces/"
MODES = ("report", "apply", "stamp")
MARKER_BASENAME = "DO_NOT_DELETE.txt"


def _registry_names():
    """Yields every registered space name, walking the listing page by page.

    Paginated rather than read whole because the listing grows with every space ever created and
    never shrinks — this spec's own change is what stops records being deleted. The page walk is
    stable under this function's own writes, since stamping a record changes no key.

    Args:
      None.

    Returns:
      An iterator of space names.

    Raises:
      ClientError: On any S3 fault.
    """
    s3 = clients.s3()
    token = None
    while True:
        kwargs = {"Bucket": cpconfig.ADMIN_BUCKET, "Prefix": REGISTRY_PREFIX}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith(".json"):
                yield key[len(REGISTRY_PREFIX) : -len(".json")]
        token = page.get("NextContinuationToken")
        if not token:
            break


def _has_database(name):
    """Reports whether the space still has its Glue database.

    Half of the discriminator an operator needs for a ``failed`` record. Absence is read from
    the entity-not-found signal rather than from a denial, so a missing grant surfaces as a
    fault instead of being reported as a create that never finished.

    Args:
      name: The space name, which is also its database name.

    Returns:
      True when the database exists.

    Raises:
      ClientError: On any Glue fault other than the database being absent.
    """
    glue = clients.glue()
    try:
        glue.get_database(Name=name)
    except glue.exceptions.EntityNotFoundException:
        return False
    return True


def _has_data(name):
    """Reports whether any real object remains under the space's prefix.

    **The marker object does not count, and that distinction is the whole value of this
    signal.** Creating a space writes the marker as one of its first steps, before the database,
    the grant and the record's outcome — so a create that failed almost anywhere still has one,
    and counting it would report every failed create as holding data. What is left after
    excluding it is data somebody wrote, which no failed create has.

    One page is enough: the question is emptiness, not a count.

    Args:
      name: The space name, which is also its prefix.

    Returns:
      True when at least one non-marker object exists under the prefix.

    Raises:
      ClientError: On any S3 fault.
    """
    page = clients.s3().list_objects_v2(Bucket=cpconfig.SHARED_SPACE_BUCKET, Prefix=f"{name}/")
    return any(
        item["Key"].rsplit("/", 1)[-1] != MARKER_BASENAME for item in page.get("Contents", [])
    )


def _describe(name, record):
    """Builds one report row for a record no rule decides.

    Carries the timestamps as well as the resources, because they are the sharper signal and the
    resources collide: a create that failed late and a delete that failed early hold the same
    database and the same data, and both write their raw fault text into the same reason field,
    so a pair of them can produce identical rows. What separates them is elapsed time — a create
    that never finished was written and abandoned inside one invocation, while a delete that
    failed happened long after its space was made. The request id is the join into the retained
    structured logs, which settles outright what the row can only suggest.

    Args:
      name: The space name.
      record: The registry record.

    Returns:
      The row: the verdict where there is one, then the timestamps, the resources and the reason.

    Raises:
      ClientError: On any S3 or Glue fault.
    """
    status = record.get("status")
    return {
        "name": name,
        "status": status,
        "verdict": "never stamp" if status in NEVER_STAMP_STATUSES else "decide",
        "createdAt": record.get("createdAt"),
        "updatedAt": record.get("updatedAt"),
        "lastRequestId": record.get("lastRequestId"),
        "hasDatabase": _has_database(name),
        "hasData": _has_data(name),
        "reason": record.get("reason"),
    }


def backfill(mode="report", name=None, request_id=""):
    """Walks the registry and reports, stamps by status, or stamps one named record.

    Every mode is idempotent and re-runnable, so a second run over records the first already
    stamped costs a read each and writes nothing. **What it is not is resumable**: there is no
    marker, so a re-run restarts from the first key rather than continuing, which is why this
    function's timeout is sized to the whole walk instead of to one space.

    Args:
      mode: ``report``, ``apply`` or ``stamp``.
      name: The single space to stamp, required by ``stamp`` and ignored otherwise.
      request_id: The run's request id, recorded on the records this stamps.

    Returns:
      The outcome: how many registry objects were scanned, how many were stamped and under
      which status, how many already carried the field, and — for the statuses no rule decides —
      the rows an operator dispositions by hand.

    Raises:
      ValueError: On an unknown mode, or a ``stamp`` with no name.
      ClientError: On any S3 or Glue fault.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}: expected one of {MODES}")
    if mode == "stamp":
        if not name:
            raise ValueError("stamp mode requires a space name")
        stamped = reg.mark_ever_active(name, request_id)
        observability.info("backfill stamped one record", space=name, stamped=stamped, mode=mode)
        return {"mode": mode, "name": name, "stamped": stamped}

    scanned = 0
    already = 0
    counted = {}
    undecidable = []
    for space in _registry_names():
        record = reg.load(space)
        if record is None:
            continue
        scanned += 1
        if record.get("everActive"):
            already += 1
            continue
        status = record.get("status")
        if status in STAMPABLE_STATUSES:
            # In apply mode the count is what the writer CONFIRMS, not what this loop intended:
            # a record can vanish between the read above and the write's own read, and a count
            # of intentions would report a stamp that never landed.
            if mode != "apply" or reg.mark_ever_active(space, request_id):
                counted[status] = counted.get(status, 0) + 1
            continue
        undecidable.append(_describe(space, record))

    outcome = {
        "mode": mode,
        "scanned": scanned,
        "alreadyStamped": already,
        # Named for what the mode actually did, because the same number means two things: what
        # apply wrote, and what report would write if it were run.
        ("stamped" if mode == "apply" else "wouldStamp"): counted,
        "undecidable": undecidable,
    }
    logger.info("backfill %s: %s", mode, outcome)
    observability.info(
        "backfill swept the registry",
        mode=mode,
        records_scanned=scanned,
        records_already_stamped=already,
        records_stamped=sum(counted.values()),
        records_undecidable=len(undecidable),
    )
    return outcome


@observability.traced("backfill-ever-active")
def handler(event, context):
    """Entry point for the one-shot backfill, invoked directly rather than by the machine.

    The mode defaults to the one that writes nothing, so an invocation with no payload — the
    easiest thing to do by accident — reports rather than mutates.

    Args:
      event: The invocation payload, carrying the mode, an optional space name for ``stamp``,
        and an optional request id.
      context: The Lambda context, unused.

    Returns:
      The outcome from ``backfill``.

    Raises:
      ValueError: On an unknown mode, or a ``stamp`` with no name.
    """
    return backfill(
        mode=(event or {}).get("mode", "report"),
        name=(event or {}).get("name"),
        request_id=(event or {}).get("requestId", ""),
    )
