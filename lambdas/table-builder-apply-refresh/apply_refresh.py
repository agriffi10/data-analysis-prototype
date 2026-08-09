"""apply-refresh — the refresh branch's terminal task.

Replaces the table's definition in place with one Glue update. The earlier design rebuilt it
by dropping the table and creating it again through Athena, which worked but carried two costs
no amount of care removed: for a second or two the user's table did not exist, and the rebuilt
catalog entry was a new entry, so the table's identity, description, owner and any Lake
Formation grant made directly on it were gone.

It is a read-modify-write, never a rebuild from the captured definition, and that is the one
thing here worth getting right: an update replaces the whole definition, so a field the input
omits is cleared rather than left alone. The capture never carried the description or owner
and deliberately strips the external flag, so building the input from it would delete exactly
what this verb exists to preserve. The live table is read immediately before it is written, and
only the columns and projection parameters are changed.

There is no moment at which the table is absent, so no concurrent refresh can see a missing
table mid-rebuild, and a failed update changes nothing. What that does not retire, stated
rather than implied: two refreshes on one database still overlap, and Glue offers no
compare-and-set to close it. The worst case degrades from one run seeing no table to
last-write-wins between two definitions. See ``docs/lambda-rationale.md``.

Attributes:
  _TABLE_INPUT_FIELDS: The fields a Glue table update accepts. An allowlist rather than a
    denylist of what a read adds, and the difference is not cosmetic — a read returns 25
    members and the input accepts 14, so a denylist has to name 11 and goes stale the next
    time AWS adds a field. A rejected field fails the call loudly; an unstripped one Glue
    silently accepts is worse. The tests pin this against botocore's own service model.
  _GLUE_RETRYABLE: Glue faults worth retrying, matched directly here rather than through the
    shared classifier — this is the only Glue write in the repo, the one call where a spurious
    terminal failure is user-visible. Two of these are also in the shared set now, so every
    read path gets them too; they are kept here because this verb matches against this set
    directly and removing them would change behaviour.
"""

import logging

from cpcommon import clients, ddl, errors, events, observability
from cpcommon.errors import TerminalError, TransientError
from tbcommon import notify

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="table-builder")

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

_GLUE_RETRYABLE = frozenset({
    "InternalServiceException",
    "OperationTimeoutException",
    "ResourceNotReadyException",
    "FederationSourceRetryableException",
    "ConcurrentModificationException",
})


def _write_columns(columns: list[dict], live_partition_keys: list[dict], live_columns: list[dict]) -> list[dict]:
    """Builds the Glue columns an in-place refresh writes: fresh names and types, carried metadata.

    Names are lowercased, because this write bypasses the folding the create path gets for
    free. AWS documents that Athena lowers any upper-case names in DDL when it creates
    databases, tables or columns, so every table this plane built through the Athena create
    path carries lower-case columns, and writing the file header's own casing would leave a
    mixed-case catalog entry the create path could never have produced.

    Comments and per-column parameters are carried from the live column of the same folded
    name. Inference returns names and types and has nothing to say about what a column means,
    so both are metadata only the table holds, and a rebuild is exactly where they would
    silently disappear. A column that is new, or whose metadata was never set, is written with
    neither.

    A data column colliding with a partition key is dropped: Glue keeps partition keys in their
    own field, which this verb passes through untouched, and one name declared in both is not a
    valid table.

    Args:
      columns: The freshly inferred columns.
      live_partition_keys: The live table's partition keys, used only to drop collisions.
      live_columns: The live table's columns, the source of the carried metadata.

    Returns:
      The Glue column entries to write.

    Raises:
      TerminalError: ``update_failed`` when the fold collapses two columns into one. The check
        is here because the fold is what creates the collision — a header of ``Amount,amount``
        is two fields to inference and one column name to Glue. The create path got this
        refusal for free because Athena rejects duplicate column names, but an update performs
        no such validation, and the post-condition cannot catch it either because it compares
        name sets: both spellings collapse to one entry on each side and compare equal, so the
        verb would report success while the table under-reported a column and failed at query
        time.
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
    """Builds the table parameters an in-place refresh writes.

    Every projection key is replaced — the live ones dropped, the regenerated ones rendered
    from the reconstructed partition keys through the create path's own renderer, so the two
    paths cannot drift. Every other key passes through untouched: the external flag, the
    header-skip count, and whatever a user set by hand are all things a refresh does not own.

    The projection keys are not lowercased like the column names are. They embed the partition
    key's name, and this verb writes the live partition keys back unchanged, so folding them
    would produce properties naming a partition key that does not exist.

    The portal's creation marker is re-asserted through the shared helper rather than by name,
    because a verb that can name the marker is a verb that can branch on it, and a tree-wide
    test forbids exactly that.

    Args:
      live_parameters: The live table's parameters.
      partition_keys: The reconstructed declared partition keys.

    Returns:
      The parameters to write.

    Raises:
      ValueError: If a partition key cannot be rendered.
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
    """Projects the live table into the update input, with columns and projection replaced.

    Args:
      live_table: The table as Glue just returned it.
      columns: The freshly inferred columns.
      partition_keys: The reconstructed declared partition keys.

    Returns:
      The table input to write, carrying every accepted field of the live table.

    Raises:
      TerminalError: ``update_failed`` when two columns collapse to one name.
      ValueError: If a reconstructed partition key cannot be rendered.
    """
    table_input = {key: value for key, value in live_table.items() if key in _TABLE_INPUT_FIELDS}

    storage = dict(table_input.get("StorageDescriptor") or {})
    storage["Columns"] = _write_columns(
        columns, table_input.get("PartitionKeys") or [], storage.get("Columns") or []
    )
    table_input["StorageDescriptor"] = storage
    table_input["Parameters"] = _write_parameters(live_table.get("Parameters") or {}, partition_keys)
    return table_input


def _abandon_if_changed(event: dict, live_table: dict, database: str, table: str) -> None:
    """Refuses to write when another writer committed between this run's read and this write.

    SPEC-157 FR-005. ``load-table-definition`` captured the table's ``UpdateTime`` at the start of
    the run; this compares it against the one on the read that immediately precedes the write. A
    difference means the definition this run computed was derived from a table that no longer
    exists in that form, so applying it would silently overwrite whatever the other writer did.

    THIS NARROWS THE WINDOW; IT DOES NOT CLOSE IT. ``GetTable`` and ``UpdateTable`` are still two
    separate calls, and Glue offers no compare-and-set to make them one — ``UpdateTable``'s
    ``VersionId`` is documented as the version to update, with no precondition-failure error, so
    it is NOT passed here and must not be added in the belief that it is a CAS. Another writer
    committing between this comparison and the update below is still possible; the refresh lock
    is what makes it improbable, and this is the backstop for the interval the lock cannot cover
    (a steal, or a future path that writes without taking it).

    A missing stamp on either side is not treated as a change. Glue not reporting an UpdateTime is
    no evidence of a concurrent writer, and refusing on it would fail refreshes for a reason the
    user could neither see nor act on.

    Args:
      event: The running request, carrying ``observedUpdateTime`` when one was captured.
      live_table: The pre-write ``GetTable`` response's table dict.
      database: The target database, for the message.
      table: The target table, for the message.

    Returns:
      None.

    Raises:
      TerminalError: ``table_changed_during_refresh`` when the two stamps disagree.
    """
    observed = event.get("observedUpdateTime")
    current = live_table.get("UpdateTime")
    current = current.isoformat() if hasattr(current, "isoformat") else current
    if not observed or not current or observed == current:
        return

    observability.warning(
        "abandoning refresh — the table changed underneath it",
        database=database,
        table=table,
    )
    raise TerminalError(
        "table_changed_during_refresh",
        f"table {table!r} in database {database!r} was modified by another writer during this "
        "refresh; nothing was changed",
    )


def _get_table(database: str, table: str) -> dict:
    """Reads the live definition immediately before it is written.

    A missing table is matched on the botocore code rather than the client's modelled exception
    class, so the check does not depend on a fake exposing its exception namespace.

    Args:
      database: The target database.
      table: The target table name.

    Returns:
      The live Glue table dict.

    Raises:
      TerminalError: ``table_not_found`` when the table does not exist.
      TransientError: On a retryable Glue fault. Nothing has been written yet, so a throttle
        here is safe to retry.
      ClientError: Any deterministic Glue fault propagates.
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
    """Replaces the table definition in place.

    Archiving is requested explicitly rather than left to the default. The default already
    archives, and the retained version is the manual rollback path for a refresh that landed but
    was not wanted — saying so means a future SDK default cannot quietly take it away, and lets
    a test assert it.

    A failed update changes nothing, which is why every deterministic fault maps to one reason:
    it tells the user nothing was changed, and that is true whether Glue refused on permissions
    or on the input. The raw text stays in the operator-only detail.

    Args:
      database: The target database.
      table_input: The projected table input.

    Returns:
      None.

    Raises:
      TerminalError: ``table_not_found`` when the table vanished, or ``update_failed`` on any
        other deterministic fault.
      TransientError: On a retryable Glue fault.
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
    """Reads the table back and confirms the new definition landed.

    Checked rather than assumed, because this plane's canonical failure was a verb that
    completed while the catalog did not agree. An accepted update proves the call was accepted,
    not that the definition landed as intended. The comparison is on the case-folded name set
    rather than a count: same cost, and a count cannot tell an update that landed from one that
    landed against a definition carrying the same number of columns.

    Args:
      database: The target database.
      table: The target table name.
      expected: The case-folded column names the update wrote.

    Returns:
      The number of columns the catalog now reports.

    Raises:
      TerminalError: ``update_failed`` when the table cannot be read back or the names do not
        match. Terminal even on a throttle: the update is already committed, so a Retry would
        re-read a table that has already changed and write it again, and a verification failing
        is not evidence that repeating the work it was verifying will help.
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


@observability.traced("apply-refresh")
@notify.notifies_on_failure("apply")
def handler(event: dict, context) -> dict:
    """Step Functions entry point: replaces the table's definition with the refreshed columns.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified.

    Args:
      event: The task input, carrying the actor, space, table name and inferred columns.
      context: The Lambda context, unused.

    Returns:
      The event with a refreshed status and the applied column count.

    Raises:
      TerminalError: ``table_not_found`` or ``update_failed``. Every terminal outcome here
        leaves the table exactly as it was, and the actor is notified before the SFN Catch
        records it.
      TransientError: On a retryable Glue fault.
      ValueError: If a reconstructed partition key cannot be rendered. Unlike the two above it
        is not a classified outcome — the decorator notifies it generically and the state
        machine records it by its Python name.
    """
    return _apply(event)


def _apply(event: dict) -> dict:
    """Reads the live table, writes the new definition, and verifies it landed.

    Column names are schema and are permitted in the record — they are what an operator needs
    to see what the update actually declared. There is no rendered statement to record, because
    there is no statement.

    Args:
      event: The task input.

    Returns:
      The event with a refreshed status and the applied column count, after notifying the actor.

    Raises:
      TerminalError: ``table_not_found`` or ``update_failed``.
      TransientError: On a retryable Glue fault.
      ValueError: If a reconstructed partition key cannot be rendered — it escapes the terminal
        classification and reaches the state machine as its own name.
    """
    events.require(event, "actor")
    database = events.require(event, "space", "database")
    table = events.require(event, "tableName")
    columns = events.require(event, "columns")
    partition_keys = event.get("partitionKeys") or []

    live_table = _get_table(database, table)
    _abandon_if_changed(event, live_table, database, table)
    table_input = _table_input(live_table, columns, partition_keys)
    written = [column["Name"] for column in table_input["StorageDescriptor"]["Columns"]]

    observability.info(
        "applying refresh",
        database=database,
        table=table,
        column_count=len(written),
        partition_key_count=len(partition_keys),
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
        previous_version_archived=True,
    )
    notify.emit_refresh_outcome(event, "refreshed", event.get("diff"))
    return out
