"""apply-refresh — the refresh branch's terminal task (SPEC-149, replacing SPEC-144's DDL).

Replaces the table's definition IN PLACE with one ``glue:UpdateTable``. SPEC-144 rebuilt it
by dropping the table and creating it again through Athena, which worked but carried two
costs no amount of care removed: for a second or two the user's table DID NOT EXIST, and the
rebuilt catalog entry was a NEW entry — so the table's identity, its ``Description``, its
``Owner`` and any Lake Formation grant made directly on it were gone.

A READ-MODIFY-WRITE, NEVER A REBUILD FROM SPEC-143's CAPTURE, and it is the one thing here
worth getting right. ``UpdateTable`` replaces the WHOLE definition: a ``TableInput`` that
omits a field does not leave that field alone, it CLEARS it. ``clone_definition`` never
carried ``Description`` or ``Owner`` and deliberately strips ``EXTERNAL``, so building the
input from the capture would delete exactly what this verb exists to preserve. It reads the
live table immediately before writing it and mutates only the columns and the
``projection.*`` parameters.

WHAT THIS RETIRES. There is no moment at which the table is absent, so no concurrent refresh
can see ``table_not_found`` mid-rebuild — and A FAILED UPDATE CHANGES NOTHING, which retires
SPEC-144's "a committed drop followed by exhausted retries notifies nobody" exposure
outright: there is no committed destructive step left to be silent about.

WHAT IT DOES NOT RETIRE, stated rather than implied, because SPEC-144 FR-006 AC1 claimed a
serialization guarantee that did not exist. The Pipe still invokes ``StartExecution`` as
``FIRE_AND_FORGET`` (``infra/modules/table-builder/pipe.tf``), so two refreshes on one
database still overlap, and GLUE OFFERS NO COMPARE-AND-SET TO CLOSE IT: ``UpdateTable``'s
``VersionId`` is documented only as "the version ID at which to update the table contents",
alongside ``TransactionId`` and ``ViewUpdateAction``, with no precondition-failure error.
What changes is the severity — the worst case degrades from "one run sees no table" to
last-write-wins between two definitions, and ``ConcurrentModificationException``, which Glue
raises on genuine simultaneity, is retried.
"""

import logging

from cpcommon import clients, ddl, errors, events, observability
from cpcommon.errors import TerminalError, TransientError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# `service` is the CONTROL PLANE, not the function: one table-build is five invocations, and
# they are only one queryable set if they share a service name (SPEC-127 FR-003). The per-verb
# identity rides as the `verb` field.
observability.init(service="table-builder")

#: The fields ``glue:UpdateTable``'s ``TableInput`` accepts.
#:
#: AN ALLOWLIST, NOT A DENYLIST OF WHAT ``GetTable`` ADDS, and the difference is not
#: cosmetic: ``Table`` returns 25 members and ``TableInput`` accepts these 14, so a denylist
#: has to name 11 — and it goes stale the next time AWS adds a field to ``Table``. That drift
#: is already visible (``IcebergTableMetadata``, ``Status``, ``IsMultiDialectView`` and
#: ``IsMaterializedView`` all postdate the obvious ``CreateTime``/``CreatedBy`` set). A
#: rejected field fails the call loudly; an unstripped one Glue silently accepts is worse.
#: ``test_apply_refresh`` pins this tuple against botocore's own service model, so the list
#: is verified against the API on every run rather than once during a build.
_TABLE_INPUT_FIELDS = frozenset({
    "Name",
    "Description",
    "Owner",
    "LastAccessTime",
    "LastAnalyzedTime",
    "Retention",
    "StorageDescriptor",
    "PartitionKeys",
    "ViewOriginalText",
    "ViewExpandedText",
    "TableType",
    "Parameters",
    "TargetTable",
    "ViewDefinition",
})

#: Glue faults that are worth retrying and that ``cpcommon.errors`` does not classify.
#:
#: THE SHARED SET IS SPELLED FOR S3, ATHENA AND GENERIC THROTTLES, and Glue's own names miss
#: it by a word: it lists ``InternalError``/``InternalServerException`` but Glue raises
#: ``InternalServiceException``, and it has no entry at all for ``OperationTimeoutException``
#: — which is Glue's most routine transient. Unclassified, they fall through to the terminal
#: branch below and a request dies permanently telling the user nothing was changed, when the
#: state machine's Retry would very likely have succeeded.
#:
#: Handled HERE rather than widened in ``cpcommon`` because that set is shared by every
#: control plane, and this is the only Glue WRITE in the repo — the one call where a spurious
#: terminal failure is user-visible. Read off the operation's own modelled error shapes.
#:
#: THE GAP THAT REASONING LEFT IS NOW CLOSED (SPEC-151 FR-008). It was sound for the write
#: and silent about the READS: `check-table-absent`, `load-table-definition`, `create-space`
#: and `teardown` all turned a routine Glue hiccup into a permanently failed request.
#: ``InternalServiceException`` and ``OperationTimeoutException`` are now in
#: ``cpcommon.errors._TRANSIENT_CODES``, so every read path gets them from the shared
#: classifier. They are kept in the set below too — this verb matches against it DIRECTLY
#: rather than through ``raise_if_transient``, so removing them would change behaviour here.
_GLUE_RETRYABLE = frozenset({
    "InternalServiceException",
    "OperationTimeoutException",
    "ResourceNotReadyException",
    "FederationSourceRetryableException",
    # Glue's guard on two simultaneous modifications. A re-invocation re-reads the live table
    # and writes again, which is exactly what a lost race wants — and is safe in a way
    # SPEC-144's destructive pair never was.
    "ConcurrentModificationException",
})


def _write_columns(columns: list[dict], live_partition_keys: list[dict], live_columns: list[dict]) -> list[dict]:
    """The Glue ``Columns`` an in-place refresh writes: fresh names and types, carrying the
    metadata only the old table holds.

    LOWERCASED, because this write bypasses the folding the create path gets for free. AWS
    documents that "Athena automatically lowers any upper case names in DDL queries when it
    creates databases, tables, or columns" — so every table this plane built through the
    Athena create path carries lower-case columns, and an ``UpdateTable`` writing the file
    header's own casing would leave a mixed-case catalog entry the create path could never
    have produced. The fold is the create path's behaviour, reproduced.

    ``Comment`` and per-column ``Parameters`` are carried from the live column of the same
    folded name. Inference returns names and types and has nothing to say about what a column
    MEANS, so both are metadata only the table holds — and a rebuild is exactly where they
    would silently disappear. A column that is new, or whose metadata was never set, is
    written with neither.

    A data column colliding with a PARTITION KEY is dropped: Glue keeps partition keys in
    their own ``PartitionKeys`` field, which this verb passes through untouched, and one name
    declared in both is not a valid table.

    TWO COLUMNS THAT DIFFER ONLY BY CASE ARE REFUSED, and the check is here because the fold
    above is what creates the collision. A header of ``Amount,amount`` is two distinct fields
    to the inference step and one column name to Glue. SPEC-144 got this refusal for free —
    Athena rejects a ``CREATE`` with duplicate column names — but ``UpdateTable`` performs no
    such validation, and the post-condition cannot catch it either, because it compares NAME
    SETS: both spellings collapse to one entry on each side and compare equal, so the verb
    would report success while the table under-reported a column and failed at query time.

    Raises:
        TerminalError: ``update_failed`` when the fold collapses two columns into one.
    """
    carried = {(c.get("Name") or "").casefold(): c for c in live_columns}
    partition_names = {(k.get("Name") or "").casefold() for k in live_partition_keys}

    written = []
    for column in columns:
        folded = column["name"].casefold()
        if folded in partition_names:
            continue
        entry = {"Name": column["name"].lower(), "Type": column["type"]}
        live = carried.get(folded) or {}
        if live.get("Comment"):
            entry["Comment"] = live["Comment"]
        if live.get("Parameters"):
            entry["Parameters"] = live["Parameters"]
        written.append(entry)

    names = [entry["Name"] for entry in written]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise TerminalError(
            "update_failed",
            f"columns differing only by case collapse to one name: {duplicates}",
        )
    return written


def _write_parameters(live_parameters: dict, partition_keys: list[dict]) -> dict:
    """The table ``Parameters`` an in-place refresh writes.

    Every ``projection.*`` key is REPLACED — the live ones dropped, the regenerated ones
    rendered from the reconstructed partition keys through the CREATE PATH'S OWN renderer
    (``ddl.projection_properties``), so the two paths cannot drift. Every other key is passed
    through untouched: ``EXTERNAL``, ``skip.header.line.count``, and whatever a user set with
    ``ALTER TABLE`` are all things a refresh does not own.

    The projection keys are NOT lower-cased like the column names are. They embed the
    PARTITION key's name, and this verb writes the live ``PartitionKeys`` back unchanged — so
    folding them here would produce properties naming a partition key that does not exist.

    The portal's creation marker is re-asserted through ``ddl.mark_managed`` so a table this
    path touches stays marked (SPEC-143 FR-007) — through the shared helper rather than by
    name, because a verb that can NAME the marker is a verb that can branch on it, and a
    tree-wide test forbids exactly that.
    """
    parameters = ddl.mark_managed({
        key: value for key, value in live_parameters.items() if not key.startswith("projection.")
    })
    if partition_keys:
        parameters["projection.enabled"] = "true"
        for key in partition_keys:
            parameters.update(ddl.projection_properties(key))
    return parameters


def _table_input(live_table: dict, columns: list[dict], partition_keys: list[dict]) -> dict:
    """The Glue TableInput for an in-place refresh: the LIVE table, minus the read-only
    fields Glue rejects, with columns and projection.* replaced.

    A READ-MODIFY-WRITE, never a rebuild from SPEC-143's capture. UpdateTable replaces the
    WHOLE definition, so any field this input omits is CLEARED — and the capture never
    carried Description or Owner and deliberately strips EXTERNAL. Building from it would
    delete exactly what this spec exists to preserve.
    """
    table_input = {key: value for key, value in live_table.items() if key in _TABLE_INPUT_FIELDS}

    storage = dict(table_input.get("StorageDescriptor") or {})
    storage["Columns"] = _write_columns(
        columns, table_input.get("PartitionKeys") or [], storage.get("Columns") or []
    )
    table_input["StorageDescriptor"] = storage
    table_input["Parameters"] = _write_parameters(live_table.get("Parameters") or {}, partition_keys)
    return table_input


def _get_table(database: str, table: str) -> dict:
    """The live definition, read immediately before it is written.

    ``EntityNotFoundException`` is matched on the botocore CODE rather than the client's
    modelled exception class, so the check does not depend on a fake exposing ``.exceptions``.
    A throttle here is retryable — nothing has been written yet.
    """
    client = clients.glue()
    try:
        return client.get_table(DatabaseName=database, Name=table)["Table"]
    except Exception as err:
        code = errors.error_code(err)
        if code == "EntityNotFoundException":
            raise TerminalError("table_not_found", f"{database}.{table}") from err
        if code in _GLUE_RETRYABLE:
            raise TransientError(f"glue get_table {database}.{table}: transient {code}") from err
        errors.raise_if_transient(err, f"glue get_table {database}.{table}")
        raise


def _update(database: str, table_input: dict) -> None:
    """Replace the definition in place.

    ``SkipArchive=False`` is passed EXPLICITLY rather than left to the default. The default
    already archives — AWS documents that "UpdateTable always creates an archived version of
    the table before updating it" unless ``skipArchive`` is set — and the retained version is
    the manual rollback path for a refresh that landed but was not wanted (FR-004). Saying so
    means a future SDK default cannot quietly take it away, and lets a test assert it.

    A FAILED UPDATE CHANGES NOTHING, which is why every deterministic fault maps to ONE
    reason: ``update_failed`` tells the user nothing was changed, and that is true whether
    Glue refused on permissions or on the input. The raw text stays in the operator-only
    detail (SPEC-106 FR-008).
    """
    client = clients.glue()
    name = table_input.get("Name")
    try:
        client.update_table(DatabaseName=database, TableInput=table_input, SkipArchive=False)
    except Exception as err:
        code = errors.error_code(err)
        if code == "EntityNotFoundException":
            raise TerminalError("table_not_found", f"{database}.{name}") from err
        if code in _GLUE_RETRYABLE:
            raise TransientError(f"glue update_table {database}.{name}: transient {code}") from err
        errors.raise_if_transient(err, f"glue update_table {database}.{name}")
        raise TerminalError("update_failed", f"{database}.{name}: {err}") from err


def _post_condition(database: str, table: str, expected: set) -> int:
    """Read the table back and confirm the new definition landed.

    CHECKED RATHER THAN ASSUMED because this plane's canonical failure was a verb that
    COMPLETED while the catalog did not agree (SPEC-135, PRs #243-246). An accepted
    ``UpdateTable`` proves the CALL was accepted, not that the definition landed as intended.

    Compares the case-folded NAME SET rather than a count: same cost, and a count cannot tell
    an update that landed from one that landed against a definition carrying the same number
    of columns.

    TERMINAL, NEVER TRANSIENT, including on a throttle. The update is already committed, so a
    Step Functions Retry would re-read a table that has ALREADY changed and write it again —
    and a verification failing is not evidence that repeating the work it was verifying will
    help. Unlike SPEC-144 that repeat would no longer be destructive; it is still pointless.
    """
    glue = clients.glue()
    try:
        table_def = glue.get_table(DatabaseName=database, Name=table)["Table"]
    except Exception as err:
        raise TerminalError(
            "update_failed", f"{database}.{table} is not readable after the update: {err}"
        ) from err

    actual = {
        (c.get("Name") or "").casefold()
        for c in (table_def.get("StorageDescriptor") or {}).get("Columns") or []
    }
    if actual != expected:
        raise TerminalError(
            "update_failed",
            f"{database}.{table} has {len(actual)} columns after the update, "
            f"expected {len(expected)} (missing {sorted(expected - actual)}, "
            f"unexpected {sorted(actual - expected)})",
        )
    return len(actual)


# @traced is OUTERMOST, above @notifies_on_failure: the latter catches on its way out,
# so if it were outermost the span would close status="ok" on an invocation that
# actually failed and notified.
@observability.traced("apply-refresh")
@notify.notifies_on_failure("apply")
def handler(event: dict, context) -> dict:
    """SFN entry point: replace the table's definition in place with the refreshed columns.

    Delegates to ``_apply``. A terminal failure notifies the actor before the SFN ``Catch``
    records it — and every terminal outcome here leaves the table exactly as it was.
    """
    return _apply(event)


def _apply(event: dict) -> dict:
    events.require(event, "actor")
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")
    columns = events.require(event, "columns")
    partition_keys = event.get("partitionKeys") or []

    live_table = _get_table(database, table)
    table_input = _table_input(live_table, columns, partition_keys)
    written = [column["Name"] for column in table_input["StorageDescriptor"]["Columns"]]

    observability.info(
        "applying refresh",
        database=database,
        table=table,
        column_count=len(written),
        partition_key_count=len(partition_keys),
        # Schema, not file contents — permitted by the field rule, and what an operator needs
        # to see what the update actually declared. The `ddl` field SPEC-144 logged has no
        # successor here: there is no statement to reproduce.
        column_names=written,
    )

    _update(database, table_input)
    applied = _post_condition(database, table, {name.casefold() for name in written})

    out = dict(event)
    out["status"] = "refreshed"
    out["appliedColumnCount"] = applied
    logger.info("refreshed %s.%s: %d columns", database, table, applied)
    observability.info(
        "refresh applied",
        database=database,
        table=table,
        applied_column_count=applied,
        post_condition_ok=True,
        # The previous definition is retained as a Glue table version (FR-004) — the manual
        # rollback path, named in the delivery doc.
        previous_version_archived=True,
    )
    notify.emit_refresh_outcome(event, "refreshed", event.get("diff"))
    return out
