"""data-quality assemble-report — joins everything into the report.

Reads the three Athena result sets and the manifest, computes the one finding SQL cannot express
— cross-file column agreement — and writes the single durable artefact this whole arc exists to
produce.

It recomputes nothing Athena already computed. Row counts, null ratios, type consistency and
duplicates arrive as numbers and are consumed as numbers; re-deriving any of them here would mean
reading the data in a Lambda, which is the design this arc replaced.

The report key is a pure function of the request id, so a retry or a redelivery overwrites the
same object rather than leaving a second copy. That is the whole of this pipeline's replay
safety — no verb in this codebase does request-id idempotency checking — and it is why nothing in
the report may depend on when it ran except its completion timestamp.

The results are read from S3 rather than through the query-results API, which the execution role
deliberately does not grant: the result objects already sit in the requesting space, the role can
already read that prefix, and paginating a wide result through the API would buy nothing.

The service name is the control plane, not the function: one data-quality run is nine
invocations, and they are only one queryable set if they share it. The per-verb identity rides as
the ``verb`` field.

Attributes:
  REPORT_BASENAME: Basename of the artefact, under the request's report prefix.
  OVER_CAP_EVENT: The one event this verb emits about its own output's size, named here so the
    test that holds it to the over-cap path alone matches on the module's string rather than on a
    literal of its own.
  UNLISTED_SUFFIX: What a shortened list's count is named after: the list's own field name with
    this appended, written beside the list in the same object. One rule rather than three names,
    so the page reads every list's count the same way.
  _RESULT_SUFFIX: Athena names a result object after its execution id. The key is constructed
    rather than listed — one read instead of a list plus a read, and deterministic under replay.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from cpcommon import clients, errors, events, observability
from cpcommon.errors import TerminalError
from dqcommon import config, index_store, messages, notify, report, sql
from dqcommon import manifest as manifest_store

logger = logging.getLogger()
logger.setLevel(logging.INFO)

observability.init(service="data-quality")

REPORT_BASENAME = "report.json"

OVER_CAP_EVENT = "report over the document cap"

UNLISTED_SUFFIX = "Unlisted"

_RESULT_SUFFIX = ".csv"


def report_key(report_prefix: str) -> str:
    """Derives the report object's key, purely from the request's report prefix.

    Args:
      report_prefix: The request's report prefix.

    Returns:
      The report key.

    Raises:
      None.
    """
    return f"{report_prefix.rstrip('/')}/{REPORT_BASENAME}"


def _split_uri(uri: str) -> tuple[str, str]:
    """Splits an ``s3://`` URI into its bucket and key.

    Args:
      uri: The full URI.

    Returns:
      A ``(bucket, key)`` tuple.

    Raises:
      None.
    """
    bucket, _, key = uri[len("s3://") :].partition("/")
    return bucket, key


def _read(bucket: str, key: str) -> bytes:
    """Reads one object's bytes, mapping a retryable fault.

    Args:
      bucket: The object's bucket.
      key: The object key.

    Returns:
      The object's bytes.

    Raises:
      TransientError: On a retryable S3 fault.
      ClientError: Any deterministic fault propagates.
    """
    try:
        return clients.s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as err:
        errors.raise_if_transient(err, f"get {bucket}/{key}")
        raise


@observability.step("read-results")
def _result_rows(block, field_size_limit: int | None = None) -> list[dict]:
    """Reads one query's result rows, or none when it produced no readable result.

    Athena writes a select's results to a file named after its execution id under the output
    location. That is documented and deterministic, which is worth a direct read over a listing —
    but it is also the one assumption in this verb no unit test can prove, since nothing else in
    this repo has ever read a result file. So a miss falls back to listing the prefix rather than
    failing a check that has already run three queries and a byte scan.

    Args:
      block: The state's block for one query, or None when it was never submitted.
      field_size_limit: Raises the CSV reader's per-field limit for this read alone. Only the
        duplicates result needs it — its samples cell carries whole rows of the user's data, and
        one cell past the reader's default would fail the entire report rather than one figure.

    Returns:
      The parsed rows, empty for a query that was not computed.

    Raises:
      TerminalError: ``query_failed`` when no result object can be found at all.
      TransientError: On a retryable S3 fault.
    """
    if not block or block.get("status") == "not_computed":
        return []

    bucket, prefix = _split_uri(block["resultLocation"])
    key = f"{prefix}{block['queryExecutionId']}{_RESULT_SUFFIX}"
    try:
        return report.parse_result(_read(bucket, key), field_size_limit)
    except Exception as err:
        if errors.error_code(err) not in ("NoSuchKey", "404"):
            raise
        logger.warning("result %s not at the expected key — listing %s", key, prefix)

    found = _find_result(bucket, prefix)
    if not found:
        raise TerminalError(
            messages.QUERY_FAILED, f"no result object under {bucket}/{prefix}"
        )
    return report.parse_result(_read(bucket, found), field_size_limit)


@observability.step("find-result")
def _find_result(bucket: str, prefix: str) -> str:
    """Finds the first result object under a prefix, as a fallback when the key misses.

    Athena's column-type sidecar is excluded by the suffix check: it sorts adjacent to the result,
    and parsing it as the result would yield a report full of zeros rather than an error.

    Args:
      bucket: The results bucket.
      prefix: The query's output prefix.

    Returns:
      The first matching key, or "" when there is none.

    Raises:
      TransientError: On a retryable S3 fault. The fallback path needs the same mapping as every
        other read here — a throttle arriving as a bare client error is not in the Retry list, so
        a one-off would permanently fail a request that has already paid for three queries.
      ClientError: Any deterministic fault propagates.
    """
    try:
        listed = clients.s3().list_objects_v2(Bucket=bucket, Prefix=prefix).get("Contents") or []
    except Exception as err:
        errors.raise_if_transient(err, f"list {bucket}/{prefix}")
        raise
    keys = [o["Key"] for o in listed if o["Key"].endswith(_RESULT_SUFFIX)]
    return keys[0] if keys else ""


def _serialize(document: object) -> bytes:
    """Renders the report exactly as it is written.

    The one serializer, because the size check and the write must not be able to disagree: a cap
    measured on a different rendering than the one that lands is a cap on nothing. The same holds
    for one entry of a list the cap shortens, which is measured here too.

    Args:
      document: The assembled report, or one value inside it.

    Returns:
      The bytes that would be written.

    Raises:
      None.
    """
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


@observability.step("write-report")
def _write(bucket: str, key: str, body: bytes) -> None:
    """Writes the report object.

    Args:
      bucket: The reports bucket.
      key: The report key.
      body: The serialized report, from ``_serialize``.

    Returns:
      None.

    Raises:
      TransientError: On a retryable S3 fault. Losing the report to a one-off throttle must not
        fail the request after every query has run: the key is a pure function of the request id,
        so a retry rewrites it.
      ClientError: Any deterministic fault propagates.
    """
    try:
        clients.s3().put_object(
            Bucket=bucket, Key=key, Body=body, ContentType="application/json"
        )
    except Exception as err:
        errors.raise_if_transient(err, f"put {bucket}/{key}")
        raise


@dataclass
class _Tail:
    """One list in the report that the cap may shorten from its end, and how much of it is kept.

    The byte figures are the list's serialized items, measured once, so a shortening can be priced
    without serializing the whole report again for every entry it drops.

    Attributes:
      parent: The object in the report that holds the list, and where its count is written.
      field: The list's field name in ``parent``.
      lengths: Each item's serialized length, in the list's order.
      kept: How many items, from the front, are still in.
      listed: The serialized length of the kept items and the commas between them.
    """

    parent: dict
    field: str
    lengths: list[int]
    kept: int
    listed: int

    @classmethod
    def of(cls, parent: dict, name: str) -> "_Tail":
        """Measures one list in the report.

        Args:
          parent: The object holding the list.
          name: The list's field name.

        Returns:
          The list, every item still in.

        Raises:
          None.
        """
        lengths = [len(_serialize(item)) for item in parent.get(name) or []]
        return cls(parent, name, lengths, len(lengths), sum(lengths) + max(len(lengths) - 1, 0))

    def drop_last(self) -> int:
        """Drops the last kept item, and says what that does to the report's size.

        Exact, not estimated: the item and the comma before it leave, and the count beside the list
        is written, or grows, by the width of its number. The count is a new key in an object that
        already has keys, so it costs a comma, its quoted name, a colon and its digits.

        Args:
          None.

        Returns:
          The change in the serialized report's length, in bytes. Negative, except where the count's
          own key costs more than a short item frees.

        Raises:
          None.
        """
        freed = self.lengths[self.kept - 1] + (1 if self.kept > 1 else 0)
        unlisted = len(self.lengths) - self.kept
        self.kept -= 1
        self.listed -= freed
        return self._count_bytes(unlisted + 1) - self._count_bytes(unlisted) - freed

    def _count_bytes(self, unlisted: int) -> int:
        """Prices the count this list writes beside itself, as ``,"<field>Unlisted":<n>``.

        Args:
          unlisted: How many items are left out; nothing is written for none.

        Returns:
          Its length in the serialized report.

        Raises:
          None.
        """
        if not unlisted:
            return 0
        return len(_serialize({f"{self.field}{UNLISTED_SUFFIX}": unlisted})) - 1

    def write(self) -> None:
        """Writes the shortened list and its count into the report, when anything was dropped.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        unlisted = len(self.lengths) - self.kept
        if unlisted:
            self.parent[self.field] = self.parent[self.field][: self.kept]
            self.parent[f"{self.field}{UNLISTED_SUFFIX}"] = unlisted


def _shed_longest_first(lists: list[list[_Tail]], size: int) -> int:
    """Shortens the report's per-file lists until it fits, always from whichever is longest.

    Longest in serialized bytes, and one entry at a time, so a long list cannot push a short one
    out: a short list is only touched once every longer one has come down to its length. A fixed
    order could not promise that. It empties the first list before it touches the second, which
    would drop every row count to make room for a column's spellings when the spellings were what
    made the report large.

    Each list is shortened from its end and counts what it left out, so what is kept is the front
    of the list as it was built. A column's spellings compete as ONE list across every column, the
    last column's going first: two hundred columns competing one by one would, between them, take
    the room the files that disagree about their columns need.

    A tie goes to the list named first, so the order is part of the output and a replay writes the
    same report.

    Args:
      lists: The lists, least worth keeping first; each is a run of one or more ``_Tail`` spent
        from its end.
      size: The report's serialized length before anything is dropped.

    Returns:
      The report's serialized length afterwards, which is at most the cap unless every list ran
      out first.

    Raises:
      None.
    """
    totals = [sum(tail.listed for tail in tails) for tails in lists]
    ends = [len(tails) for tails in lists]
    while size > config.DQ_REPORT_MAX_BYTES and any(totals):
        longest = max(range(len(lists)), key=lambda index: (totals[index], -index))
        tails = lists[longest]
        while not tails[ends[longest] - 1].kept:
            ends[longest] -= 1
        tail = tails[ends[longest] - 1]
        before = tail.listed
        size += tail.drop_last()
        totals[longest] -= before - tail.listed
    for tails in lists:
        for tail in tails:
            tail.write()
    return size


def _per_file_lists(document: dict) -> list[list[_Tail]]:
    """Measures the lists the cap may shorten, least worth keeping first.

    The spellings each column was merged from are a disclosure — Athena already reads them as one
    column — and they come first. The row counts are next: the only place a file with no rows
    shows. The files that disagree about their columns are last, because they are a finding, and
    a tie is lost by whichever is named first.

    Args:
      document: The assembled report.

    Returns:
      The lists, each a run of one or more ``_Tail``.

    Raises:
      KeyError: If the report has no exact section, columns or cross-file block.
    """
    exact = document["exact"]
    return [
        [_Tail.of(column, "otherSpellings") for column in exact["columns"]],
        [_Tail.of(exact, "rowCountsByFile")],
        [_Tail.of(exact["crossFile"], "disagreements")],
    ]


def _within_document_cap(document: dict) -> bytes:
    """Serializes the report, shedding what it must to stay openable, and saying what it shed.

    The browser reads a report through the document route's size cap, so a report above it is not
    a large report — it is an unreadable one, and every other finding in it is lost with the part
    that made it big.

    The duplicate samples go first and whole: they are an illustration of a count that stays, and
    the report can explain their absence in a sentence. Then the per-file lists, which the object
    and column caps bound in count but nothing bounds in bytes — the files that disagree about their
    columns, which name every column each one lacks and adds; the row counts, which carry every
    file's key; and the spellings each column was merged from. Those are shortened from the end,
    longest first, each counting what it left out under its field name with ``UNLISTED_SUFFIX``,
    and the page says how many more there are. Nothing is cut inside an entry: a file listed with
    some of its missing columns would be a wrong figure, where a file not listed is a shorter list.

    Once all of that is gone, what is left fits — the offending values are sized for it, and the
    suite builds the largest report every bound allows to hold it — so the cap is met rather than
    attempted.

    The duplicate samples are dropped only when there are samples to drop. A report without them
    replaces nothing there: an absent field, or the sentence a nested source already wrote in its
    place, is a true explanation, and a false one would not free a byte.

    The size is logged only on the path that had to act. Logged on every run it would be a number
    nobody reads, and the one run where it mattered would look like all the others.

    Args:
      document: The assembled report, modified in place when anything is shed.

    Returns:
      The bytes to write.

    Raises:
      None.
    """
    body = _serialize(document)
    if len(body) <= config.DQ_REPORT_MAX_BYTES:
        return body

    observability.info(OVER_CAP_EVENT, report_bytes=len(body))
    exact = document["exact"]
    if (exact.get("duplicateSamples") or {}).get("rows"):
        exact["duplicateSamples"] = {"omitted": report.SAMPLES_OMITTED_TOO_LARGE}
        body = _serialize(document)
    _shed_longest_first(_per_file_lists(document), len(body))
    return _serialize(document)


def _reported_location(event: dict, location: str) -> str:
    """Spells the checked location the way the report, the notification and the runs row carry it.

    A folder ends in a slash and a file does not. That is the form the report and runs-index
    contracts specify, and the one the report page's Open folder and the runs list read: without
    the slash a folder reads as a file, and Open folder lands on its parent. The slash cannot be
    taken from the threaded location, because validate-authorize normalises the location and
    normalisation drops it.

    So the answer is the one inspect-source decided and carried as ``pathFilter``, which a folder
    target does not have. It is read through ``sql.carried_path_filter``, as create-temp-tables and
    start-profile-query read it, so a state without the key is refused rather than read as a
    folder: a report that named a file as a folder would open the wrong place just as quietly.

    Args:
      event: The task input, carrying the single-file decision.
      location: The authorized location as validate-authorize threaded it.

    Returns:
      The location with one trailing slash for a folder target, or unchanged for a single file.

    Raises:
      TerminalError: ``invalid_request`` when the state carries no ``pathFilter``, or a malformed
        one.
    """
    if sql.carried_path_filter(event) is not None:
        return location
    return f"{location.rstrip('/')}/"


def _assemble(event: dict) -> dict:
    """Reads the results and manifest, builds the report, writes it, and summarises it.

    The summary threaded onward is deliberately small: the findings stay in the report, and the
    notification is built from these fields alone and must never carry the full document.

    The record carries counts and the key, never a result row — and that line is now the only one
    where it holds. The REPORT itself carries up to ``DQ_DUPLICATE_SAMPLE`` of the duplicated rows,
    cell by cell, because a count could not answer which rows repeat. So the old rule that every
    figure here is a measurement and never the data survives for everything that LEAVES this verb:
    the summary threaded onward, the notification built from it, the runs-index row and every log
    line and span field. A row of the user's data goes in the report object, which is written to
    their own prefix and read back by them, and nowhere else.

    That makes the document's SIZE a correctness question rather than a housekeeping one, which is
    ``_within_document_cap``'s subject.

    Args:
      event: The task input, carrying the space, manifest key, report prefix and query blocks.

    Returns:
      The event with the location spelled as the report spells it, and the report key and summary
      fields attached.

    Raises:
      TerminalError: ``invalid_request`` for a missing field — the carried ``pathFilter`` included,
        refused before anything is read or written — or a manifest naming a file outside the
        checked location, or ``query_failed`` when no result object exists or the profile
        result is unusable — a failed check, never a clean one, since every exact figure comes
        from the profile query's total row and without it the report would assemble into a green
        verdict over data nothing measured.
      TransientError: On a retryable S3 fault.
    """
    bucket = events.require(event, "space", "bucket", reason=messages.INVALID_REQUEST)
    manifest_key = events.require(event, "manifestKey", reason=messages.INVALID_REQUEST)
    report_prefix = events.require(event, "reportPrefix", reason=messages.INVALID_REQUEST)
    location = events.require(event, "location", reason=messages.INVALID_REQUEST)
    events.require(event, "requestId", reason=messages.INVALID_REQUEST)
    request = {**event, "location": _reported_location(event, location)}

    manifest = manifest_store.load(bucket, manifest_key, location)
    union, partition_keys, fmt = report.source_shape(request, manifest)
    duplicates_limit = report.duplicates_field_size_limit(
        len(sql.grouped_column_names(union, partition_keys, fmt))
    )
    try:
        document = report.build(
            request,
            manifest,
            _result_rows(event.get("profile")),
            _result_rows(event.get("ragged")),
            _result_rows(event.get("duplicates"), duplicates_limit),
            event.get("encoding") or {},
            completed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    except report.MissingProfileError as err:
        raise TerminalError(messages.QUERY_FAILED, f"profile result unusable: {err}") from err

    key = report_key(report_prefix)
    _write(bucket, key, _within_document_cap(document))

    out = dict(request)
    out["reportKey"] = key
    out["verdict"] = document["verdict"]
    out["hasApproximateFigures"] = document["hasApproximateFigures"]
    out["hasIncompleteFigures"] = document["hasIncompleteFigures"]
    out["completedAt"] = document["completedAt"]
    out["topIssues"] = document["topIssues"]
    out["fileCount"] = document["fileCount"]

    logger.info(
        "report %s: verdict=%s files=%d rows=%d issues=%d",
        key,
        document["verdict"],
        document["fileCount"],
        document["exact"]["rowCount"],
        len(document["topIssues"]),
    )
    observability.info(
        "assembled report",
        report_key=key,
        verdict=document["verdict"],
        files=document["fileCount"],
        row_count=document["exact"]["rowCount"],
        findings=len(document["topIssues"]),
        approximate=document["hasApproximateFigures"],
        incomplete=document["hasIncompleteFigures"],
    )

    return out


@observability.traced("assemble-report")
@notify.notifies_on_failure("assemble-report")
def handler(event, context) -> dict:
    """Writes the report, notifies the actor, and threads the summary onward.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way out,
    so if it were outermost the span would close as successful on an invocation that actually
    failed and notified.

    The success notification is emitted here, not from a terminal state, because this is the last
    point that holds the summary and runs Python — the success state is a Pass, which cannot call
    anything, and adding a notify task would mean a new state in a fixed list. It is emitted after
    the report object is written, so a notification can never link to a report that does not
    exist; if the write fails this line is never reached and the failure path notifies instead.

    Order is the contract, and it is three deep: report object, then notification, then index row
    — most durable to least. The report is written first so the index can never reference a report
    that does not exist, since the reverse would put a row on the dashboard that fails when
    clicked. The notification goes before the index because it is the user's only completion
    signal, and the index append can cost several round trips under contention — putting that
    ahead of the notification means a verb that times out mid-append leaves a written report
    nobody is ever told about, the silent-success twin of the silent failure this arc exists to
    end. The append never raises: losing the row costs a dashboard entry, failing here would cost
    the whole check.

    The recorded failure detail is safe for every raise site in this verb: one message is a
    literal and the other names a bucket and prefix, and neither quotes a result row.

    Args:
      event: The task input.
      context: The Lambda context, unused.

    Returns:
      The event with the report key, summary fields and index outcome attached.

    Raises:
      TerminalError: ``invalid_request`` or ``query_failed``.
      TransientError: On a retryable S3 fault.
    """
    try:
        out = _assemble(event)
    except TerminalError as err:
        observability.error(
            "assemble-report failed",
            step="read-results",
            error_type=type(err).__name__,
            reason=err.reason,
            detail=err.detail,
            tokens=err.tokens or {},
        )
        raise
    notify.emit_completed(out)

    space = out.get("space") or {}
    out["indexed"] = index_store.append(space.get("bucket", ""), out.get("reportPrefix", ""), out)
    return out
