"""The report shape, its exact-versus-approximate tagging, and the top-issues wording.

Everything here is pure: it turns already-fetched Athena result rows, the manifest and the
byte-scan figure into the report dict. No AWS. That is what lets the tests assert the exact
report a given set of inputs produces, which matters more than usual in this module — a subtly
wrong report does not crash, it tells a user something false about their data and they act on it.

Four tags, and the distinction is the point of the whole arc. **Exact** covers type consistency,
null and blank ratios, duplicate rows and row counts, all computed by Athena over every row, and
cross-file column agreement, computed from every file's probed header. **Approximate** covers ragged rows and encoding when computed, each
carrying the reason it can only be approximate, in the report, next to the number. **Skipped** is
a check that could never have found anything here, and is never rendered as a clean pass: a green
result the data did not earn is worse than no result. **Not computed** is a check that was
attempted and failed; the report still lands, with everything else.

Cross-file agreement is computed here and not in SQL because an Athena external table has one
schema for the whole folder. It would happily read a folder whose files disagree and return a
clean-looking answer, hiding the exact disagreement the user needs to see. So it is a reduce over
inspect-source's per-file probe rather than a query, and it is the check most likely to explain
why a downstream table came out wrong.

Attributes:
  SKIP_TYPE_PARQUET: Why type consistency cannot find anything in a format that enforces types.
  SKIP_TYPE_TYPED_COLUMN: Why it cannot find anything in one already-typed column.
  SKIP_RAGGED_NOT_LINE_DELIMITED: Why ragged rows only mean something for a line-delimited text
    format.
  NOTE_RAGGED: Both approximation caveats, never one. Splitting over-reports a quoted delimiter
    and over-reports a newline inside a quoted field, where one logical row arrives as two
    physical lines. Stating only the first would leave a user hunting for malformed rows that are
    in fact perfectly well-formed multi-line records.
  NOT_COMPUTED_RAGGED_LINE_TOO_LONG: The degraded-ragged reason for Athena's single-line limit.
  NOT_COMPUTED_RAGGED: The generic degraded-ragged reason.
  NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE: The size-guard reason. Says what the user can do about it,
    because unlike the other two this one has an action, and names both causes, because the guard
    measures the rendered query and a file count is a poor proxy for its length — a few hundred
    deeply-nested long keys trip it while many short ones do not. Blaming the count alone would be
    flatly untrue for the first user; naming only the length would confuse the ordinary case.
  NOT_COMPUTED_ENCODING: The degraded-encoding reason.
  NOT_COMPUTED_DUPLICATES: The degraded-duplicates reason. None of these carry raw Athena text:
    the engine's own wording names serde classes and byte offsets, which tells a user nothing and
    leaks implementation, and the raw reason stays on the state block and in the execution
    history where an operator can read it.
  SAMPLES_OMITTED_NESTED: Why a source holding lists or objects shows no repeated rows. Says the
    count is unaffected, because a reader who has just been told one figure is missing will
    otherwise wonder whether the one above it is too.
  SAMPLES_OMITTED_TOO_LARGE: Why a report that would not have opened shows no repeated rows. The
    same reassurance, for the same reason.
  _LINE_TOO_LONG_MARKERS: Athena's wording when the raw-line table hit its single-line limit.
    Matched on text because Athena reports it as a generic failure with a message rather than a
    distinct state. A miss is mild and one-way — the user gets the generic sentence instead of
    the specific one, never a wrong outcome.
  _CAST_TYPES: The casts the profile query tried, in report order. Must match the query builder's
    own list, which is where they are generated.
  _NUMERIC_CASTS: Which of those belong to the numeric family.
  _SAMPLE_FOR: Which bounded sample matches a dominant type's family. A numeric-dominant column
    wants examples of values that are not numbers; a temporal one wants values that are not dates.
  _TEXT: What a column whose dominant type covers too little of its non-null values is called. It
    is not a broken numeric column, it is free text that happens to contain numbers.
  _JSON_ESCAPED_STRING_CHARS: Longest one string of a duplicate-samples cell can be once JSON has
    escaped it, in CHARACTERS: every one of ``sql.SAMPLE_VALUE_CHARS`` escaping to TWELVE, plus the
    two quotes and the comma separating it from the next. Twelve rather than six because the cut
    that bounds the value is Trino's ``substr``, which counts CODE POINTS — so a value may be 201
    astral code points, and JSON escapes each of those as a surrogate PAIR — twelve characters,
    two backslash-u sequences. A control character or a BMP character costs six; only the astral
    case costs twelve, and it is the one that decides the bound. Derived rather than measured, because
    the cell is the user's own data and its worst case is a file of emoji — not a file anyone would
    notice was unusual.

    **The twelve rests on an escaping behaviour nobody here has run against Athena, and is safe
    anyway**: the figure only ever raises a ``max()`` floor on a REFUSAL threshold, so if Trino's
    ``json_format`` emits the raw UTF-8 character instead of a surrogate pair, this is merely
    conservative. Six would be the wrong direction to be wrong in — it would refuse a cell the
    statement was entitled to return, and fail the whole report.
  _CSV_DEFAULT_FIELD_CHARS: ``csv``'s own per-field limit, captured at import so the floor in
    ``duplicates_field_size_limit`` is the DEFAULT rather than whatever the limit happens to be when
    it is called.
  MAX_SAMPLE_VALUE_CHARS: Longest offending-value or duplicate-sample value the report will carry.
    One SHORTER than the statement's own cut (``sql.SAMPLE_VALUE_CHARS``), so a value the engine
    shortened is still recognisable as shortened here.
"""

import csv
import io
import json
from collections import Counter

from cpcommon import columns as columns_mod
from cpcommon import ddl

from . import config, sql

SKIP_TYPE_PARQUET = "Parquet enforces types in the file format, so this check cannot find anything."
SKIP_TYPE_TYPED_COLUMN = (
    "the file format defines this column's type, so it cannot hold a value that fails to parse."
)

SKIP_RAGGED_NOT_LINE_DELIMITED = "not a line-delimited text format."

NOTE_RAGGED = (
    "Approximate — over-counts rows with commas inside quotes, and rows with newlines "
    "inside quoted fields."
)

NOT_COMPUTED_RAGGED_LINE_TOO_LONG = (
    "a single line in this data was longer than the check can read (Athena's 200 MB limit)."
)
NOT_COMPUTED_RAGGED = "the ragged-row check couldn't be completed on this data."
NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE = (
    "this folder has too many files, or file names too long, for the ragged-row check to "
    "compare each file against its own columns. Please check a smaller folder."
)
NOT_COMPUTED_ENCODING = "the character-encoding check didn't produce a result."
NOT_COMPUTED_DUPLICATES = (
    "finding duplicates means comparing every column across the whole dataset, and that "
    "was too large to complete here."
)

SAMPLES_OMITTED_NESTED = (
    "the repeated rows aren't shown because this data has columns holding lists or objects, "
    "which can't be rendered as text. The duplicate count above still covers every column."
)
SAMPLES_OMITTED_TOO_LARGE = (
    "the repeated rows aren't shown because the report would have been too large to open. "
    "The duplicate count above is unaffected."
)

_LINE_TOO_LONG_MARKERS = ("line too long", "too long in text file", "max line length", "line length")

_CAST_TYPES = ("bigint", "double", "timestamp", "date")
_NUMERIC_CASTS = frozenset({"bigint", "double"})

_SAMPLE_FOR = {"bigint": "non_numeric", "double": "non_numeric", "timestamp": "non_temporal", "date": "non_temporal"}

_TEXT = "text"

MAX_SAMPLE_VALUE_CHARS = 200


class MissingProfileError(ValueError):
    """The profile result had no total row; the caller raises the terminal."""


_JSON_ESCAPED_STRING_CHARS = sql.SAMPLE_VALUE_CHARS * 12 + 3

_CSV_DEFAULT_FIELD_CHARS = csv.field_size_limit()


def duplicates_field_size_limit(grouped: int) -> int:
    """Sizes the CSV reader's field limit for one duplicates result.

    ``csv`` refuses a field past a process-global limit — 131,072 characters by default — and
    assemble-report re-raises everything but a missing object, so ONE oversized cell fails the
    whole report rather than one figure. The duplicates cell is the only one this check can push
    past that: it carries whole rows of the user's data rather than single values, and a wide
    table multiplies it by the column count.

    Computed from what the statement can return, not guessed: ``DQ_DUPLICATE_SAMPLE`` arrays of
    ``grouped + 1`` strings (the repeat count, then one cell per grouped column), each string at
    its escaped worst case, plus the brackets around each array and around the whole cell. The
    per-string allowance includes a trailing comma that the last element of each array does not
    use, and that slack is what covers the commas BETWEEN the arrays.

    Never below the default — ``_CSV_DEFAULT_FIELD_CHARS``, captured at import rather than read
    here. For a narrow table the computed figure is smaller than it, and returning it would TIGHTEN
    the reader on a cell that parses today: a raise that quietly becomes a lowering is how a guard
    starts failing the thing it was added to protect. Read live, the floor would be whatever the
    limit happens to be at the call rather than the default, so a permanent raise from anywhere else
    in the process would be floored against itself and this sentence would stop being true with
    nothing to say so.

    The unit is CHARACTERS throughout, which is what ``csv`` counts — the escaped-string figure
    counts characters too, not the bytes they encode to.

    Args:
      grouped: How many columns the statement grouped by.

    Returns:
      The field limit, in characters.

    Raises:
      None.
    """
    computed = config.DQ_DUPLICATE_SAMPLE * ((grouped + 1) * _JSON_ESCAPED_STRING_CHARS + 2) + 2
    return max(_CSV_DEFAULT_FIELD_CHARS, computed)


def parse_result(body: bytes, field_size_limit: int | None = None) -> list[dict]:
    """Parses an Athena CSV result file into header-keyed rows.

    Athena quotes result fields, so the CSV reader handles embedded commas, quotes and newlines
    correctly — which the offending-value samples genuinely contain, since they are drawn from
    the worst-formed values in the column. A null arrives as an empty field and is
    indistinguishable from an empty string; every field this module reads is either a number or a
    JSON array, so that ambiguity cannot reach a figure.

    Safe to read whole: every result set here is bounded by files times columns, or is exactly
    one row, never by row count.

    Decoding replaces rather than failing. Hive's text readers already substitute a replacement
    character, so the result file should always be valid text — but the offending-value samples
    in it are literally the worst-formed values in the user's data, on a source this check flagged
    because it may be mis-encoded. A decode error here would escape as a raw Python error after
    every query had already run, to spare a replacement character in one example value.

    Args:
      body: The result file's bytes.
      field_size_limit: Raises ``csv``'s field limit for this read alone. The limit is
        process-global and this verb parses three results per invocation on a container that is
        reused, so it is restored afterwards rather than left raised — a limit that only ever
        climbs would eventually be doing no work at all, and nothing would say so.

    Returns:
      The rows, keyed by header.

    Raises:
      None.
    """
    if field_size_limit is None:
        return list(csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace"))))

    previous = csv.field_size_limit(field_size_limit)
    try:
        return list(csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace"))))
    finally:
        csv.field_size_limit(previous)


def _int(row: dict, key: str) -> int:
    """Reads one result cell as an integer, treating a blank as zero.

    Args:
      row: The result row.
      key: The column name.

    Returns:
      The integer value.

    Raises:
      ValueError: If the cell is non-empty and not a number.
    """
    value = (row.get(key) or "").strip()
    return int(value) if value else 0


def _json_array(row: dict, key: str) -> list:
    """Decodes one bounded sample array, truncating each example.

    The query renders these as JSON precisely so this is a parse rather than a guess: Athena's
    bare array rendering leaves the elements unquoted, and a value containing a comma — the
    canonical CSV defect, and often the very reason the column was flagged — would split into two
    wrong examples.

    Each value is bounded too, not just the count. The sample cap limits how many examples a
    column contributes and the statement's cut how long each is; this cut, one character shorter,
    is what marks a shortened value with an ellipsis, and it holds the report's bound even if a
    value arrives longer than the statement should have returned — an Athena string has no length
    limit of its own, and an example that long tells the reader nothing a truncated one does not.

    Args:
      row: The result row.
      key: The sample column's name.

    Returns:
      The examples, each truncated. Empty for a blank cell, unparseable JSON, or a null aggregate
      — which renders as the JSON null literal and would otherwise put a null where the report
      contract expects a list.

    Raises:
      None.
    """
    return [_truncate(value) for value in _decode_json_array(row, key)]


def _decode_json_array(row: dict, key: str) -> list:
    """Decodes one JSON-rendered result cell, without interpreting what is in it.

    Split from ``_json_array`` because the two callers want different things back: an offending-value
    sample is a list of scalars to truncate, a duplicate sample is a list of ROWS whose cells are
    truncated one level down. Truncating a row would render the whole list as one JSON string.

    Args:
      row: The result row.
      key: The cell's column name.

    Returns:
      The decoded list. Empty for a blank cell, unparseable JSON, or a null aggregate — which
      renders as the JSON null literal and is not a list.

    Raises:
      None.
    """
    raw = (row.get(key) or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    return parsed if isinstance(parsed, list) else []


def _truncate(value):
    """Renders one sample value as a bounded string.

    Args:
      value: The decoded example, of any JSON type.

    Returns:
      The value as a string, with an ellipsis when it was cut.

    Raises:
      None.
    """
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= MAX_SAMPLE_VALUE_CHARS else text[:MAX_SAMPLE_VALUE_CHARS] + "…"


def _is_line_too_long(reason) -> bool:
    """Reports whether Athena's failure text names its single-line limit.

    Args:
      reason: Athena's raw failure text, or None.

    Returns:
      True when any known marker appears.

    Raises:
      None.
    """
    lowered = (reason or "").lower()
    return any(marker in lowered for marker in _LINE_TOO_LONG_MARKERS)


def _skip_reason(column: dict, parquet: bool) -> str:
    """Explains why type consistency was not checked for one column.

    Two different reasons, and they must not be collapsed: Parquet skips every column because the
    format enforces types, while a typed column in a JSON source skips because that particular
    column cannot hold an unparseable value. Both are honest skips; a user reading the Parquet
    explanation under a JSON report would rightly not believe the rest.

    Args:
      column: The column's name and type.
      parquet: Whether the source format is Parquet.

    Returns:
      The reason, or "" when the column was checked.

    Raises:
      KeyError: If the column is missing its type.
    """
    if parquet:
        return SKIP_TYPE_PARQUET
    return "" if column["type"] == "string" else SKIP_TYPE_TYPED_COLUMN


def _column(
    index: int,
    column: dict,
    total: dict,
    row_count: int,
    skip_reason: str,
    other_spellings: list[str],
) -> dict:
    """Builds one column's exact findings from the profile query's total row.

    A skipped column is marked skipped, never a clean pass: a green type-consistency result on a
    format that enforces types would be a result the data never earned. A column whose values are
    all null or blank has no dominant type to find, and calling it numeric-and-clean would be an
    invention. A column whose dominant type covers too little is free text rather than a broken
    numeric column, and reporting the majority of its values as offending would be noise the user
    has to wade past.

    A column merged from names that differ only by case carries its other spellings. They are a
    disclosure, not a finding: Athena reads them as one column and nothing needs repairing, so
    they touch neither the verdict nor the top issues. The field is absent when there are none,
    which is also how every report written before the merge reads.

    Args:
      index: The column's position, which names its result aliases.
      column: The column's name and type.
      total: The profile query's total row.
      row_count: The total row count, the denominator for the missing ratio.
      skip_reason: The reason type consistency was skipped, or "".
      other_spellings: The column's other spellings across the files, or an empty list.

    Returns:
      The column's report entry.

    Raises:
      KeyError: If the column is missing its name.
      ValueError: If a result cell is non-empty and not a number.
    """
    alias = f"c{index}"
    missing = _int(total, f"{alias}_missing")
    non_null = row_count - missing
    entry = {
        "name": column["name"],
        "nullBlankRatio": round(missing / row_count, 4) if row_count else 0.0,
    }
    if other_spellings:
        entry["otherSpellings"] = other_spellings

    if skip_reason:
        entry["typeConsistency"] = "skipped"
        entry["reason"] = skip_reason
        return entry

    if not non_null:
        entry.update(dominantType=_TEXT, nonParsingValues=0, sampleOffending=[])
        return entry

    dominant, failures = min(
        ((cast, _int(total, f"{alias}_not_{cast}")) for cast in _CAST_TYPES),
        key=lambda pair: (pair[1], _CAST_TYPES.index(pair[0])),
    )
    if (non_null - failures) / non_null < config.DQ_TYPE_DOMINANCE_THRESHOLD:
        entry.update(dominantType=_TEXT, nonParsingValues=0, sampleOffending=[])
        return entry

    entry.update(
        dominantType=dominant.upper(),
        nonParsingValues=failures,
        sampleOffending=_json_array(total, f"{alias}_sample_{_SAMPLE_FOR[dominant]}"),
    )
    return entry


def cross_file(files: list[dict], fmt: str | None, partition_keys: list[dict]) -> dict:
    """Reports whether every file presents the same columns, and exactly where they differ.

    The baseline is the modal column set, not the first file's and not the union. The union would
    make every disagreement look like a missing column and never an extra one; the first file's
    would blame every other file when the first is the odd one out. The modal set names the
    minority, which is the file the user has to go and fix.

    The one case where that claim does not hold is exactly two files that disagree: there is no
    majority, the tie breaks on insertion order, and the second file is always the one named. The
    finding itself is still true and still points at the right pair of files, but which of the two
    is the odd one is arbitrary, and no amount of counting can settle it, because the data does
    not say.

    In a CSV each file is also checked against the columns the typed table DECLARES, because
    OpenCSVSerde assigns a file's fields to them by position: field ``i`` is read as declared
    column ``i``, trailing fields past the last declared column are ignored, and a short row reads
    nulls. A file is ``shifted`` when any field it has lands under a column of another name, which
    is every way a CSV is misread — columns in another order, a column inserted or dropped before
    one the table keeps, or two files adding different trailing columns, the later read under the
    earlier's name. Nothing errors, since every CSV column is a string, so this is the only place
    the misread shows. Parquet and JSON are matched by name and are never shifted.

    The declared columns are the union as ``ddl.declare_columns`` pairs it — the same pairing the
    typed table, the profile query and the report's per-column figures are built from — so
    ``shifted`` names exactly the files whose values those figures count under the wrong name.
    That is deliberately not the minority: the declared order is first-seen across the files as
    listed, so when the first file is the odd one, the files named are the rest, and they are the
    ones this report misreads. Missing and extra still name the minority, which is the repair.

    Names are compared through ``columns.fold``, the way ``sql.union_columns`` merges them, so a
    file spelling ``customerid`` agrees with one spelling ``CustomerID`` and is not shifted under
    it: Athena reads the two as one column. Each declared column is compared by the name the FILES
    give it: a CSV column named after a partition is declared under a new name, and a file carrying
    it where the table declares it is read correctly, so comparing the table's name would flag
    every such file. A missing column is named in the union's spelling, the one the report's
    Columns show, and an extra one in the file's own.

    A single file flows through the general path rather than short-circuiting: it produces the
    identical answer, since its own signature is the modal one and it never disagrees with itself,
    and a special case that changes no behaviour is a branch nothing can test.

    The pairing is deliberately non-strict, which keeps today's behaviour explicit. Strict would
    be the stronger claim, but it turns a length mismatch into a raise in the report path — a
    change worth making deliberately, with the callers characterised, not as a lint fix.

    Args:
      files: The manifest's file entries, each carrying its probed columns.
      fmt: The source format key, or None when neither the manifest nor the request names one.
        Positions are checked only for ``ddl.POSITIONAL_FORMATS``, which None is not.
      partition_keys: The declared partition keys, which decide the columns the typed table declares.

    Returns:
      Whether the columns agree, and for each file that does not, its missing and extra columns
      and whether its fields are read under the wrong columns.

    Raises:
      KeyError: If a file entry is missing its key, a column its name, or a partition key its
        name.
    """
    if not files:
        return {"columnsAgree": True, "disagreements": []}

    headers = [[c["name"] for c in (f.get("columns") or [])] for f in files]
    folded = [[columns_mod.fold(name) for name in names] for names in headers]
    signatures = [tuple(sorted(names)) for names in folded]
    baseline = set(Counter(signatures).most_common(1)[0][0])

    positional = fmt in ddl.POSITIONAL_FORMATS
    union = sql.union_columns(files)
    spelled = {columns_mod.fold(c["name"]): c["name"] for c in union}
    declared = [
        columns_mod.fold(pair.source["name"])
        for pair in ddl.declare_columns(union, partition_keys, fmt)
        if pair.declared is not None
    ]

    disagreements = []
    for entry, names, folds in zip(files, headers, folded, strict=False):
        present = set(folds)
        own = dict(zip(folds, names, strict=True))
        width = min(len(folds), len(declared))
        shifted = positional and folds[:width] != declared[:width]
        if present != baseline or shifted:
            disagreements.append(
                {
                    "file": entry["key"],
                    "missing": sorted(spelled[name] for name in baseline - present),
                    "extra": sorted(own[name] for name in present - baseline),
                    "shifted": shifted,
                }
            )
    return {"columnsAgree": not disagreements, "disagreements": disagreements}


def partition_named_columns(
    columns: list[dict], partition_keys: list[dict], fmt: str | None
) -> list[dict]:
    """Names each column sharing a partition's name, and what the typed table did with it.

    Such a column cannot be declared under its own name, so its figures are either under another
    name or absent, and a report that says neither leaves the user to find the column missing
    from Columns, or an unfamiliar name in it, with nothing explaining why. A CSV keeps it under a
    new name, because a CSV is read by position; JSON and Parquet leave it out, because they are
    read by name and a table over the folder reads the partition's value in its place.

    Args:
      columns: The unioned columns.
      partition_keys: The manifest's detected partition keys.
      fmt: The source format, the same one the per-column figures were mapped with.

    Returns:
      One entry per such column, in union order: ``{name, outcome: "renamed", as}`` or
      ``{name, outcome: "omitted"}``, ``name`` spelled as the files spell it.

    Raises:
      KeyError: If a column or partition key is missing its name.
    """
    entries = []
    for pair in ddl.declare_columns(columns, partition_keys, fmt):
        if not pair.collides:
            continue
        if pair.declared is None:
            entries.append({"name": pair.source["name"], "outcome": "omitted"})
        else:
            entries.append(
                {"name": pair.source["name"], "outcome": "renamed", "as": pair.declared["name"]}
            )
    return entries


def _row_counts_by_file(rows: list[dict], files: list[dict]) -> list[dict]:
    """Builds the per-file row counts, keyed by object key rather than the full path.

    Reconciled against the manifest, and sorted, for two separate reasons.

    Reconciled: Athena produces no group for a file with no data rows, so a header-only CSV — a
    failed export, one of the commoner real defects — would simply be absent from this array
    rather than present with zero. A reader comparing its length to the file count would find them
    silently disagreeing, and the empty file the user most needs to know about is the one that
    disappears.

    Sorted: the grouping has no ordering clause, so Athena's row order is arbitrary and not stable
    across executions. A replay must differ only in its completion timestamp; without this, a
    re-run that produced a second execution would differ by ordering alone and the report view
    would list files in a different order each time.

    Args:
      rows: The profile query's rows.
      files: The manifest's file entries.

    Returns:
      One entry per manifest file, sorted by key.

    Raises:
      KeyError: If a file entry is missing its key.
      ValueError: If a result cell is non-empty and not a number.
    """
    counted = {
        _strip_scheme(row.get("source_file") or ""): _int(row, "row_count")
        for row in rows
        if _int(row, "is_total") == 0
    }
    return sorted(
        ({"key": entry["key"], "rows": counted.get(entry["key"], 0)} for entry in files),
        key=lambda entry: entry["key"],
    )


def _strip_scheme(path: str) -> str:
    """Reduces a full object path to its key.

    Args:
      path: The path from Athena's pseudo-column.

    Returns:
      The key, or the input unchanged when it carries no scheme.

    Raises:
      None.
    """
    if not path.startswith("s3://"):
        return path
    _, _, rest = path[len("s3://") :].partition("/")
    return rest


def _ragged(block, rows: list[dict]) -> dict:
    """Builds the ragged figure, or the skipped or not-computed variant with its reason.

    An absent block is skipped rather than not-computed: JSON and Parquet rows are not
    line-delimited fields, so the concept never applied, and "we tried and failed" and "this could
    never apply" are different things the report must not blur.

    On a degraded block the size-guard code is read first, because it is a marker this codebase
    wrote and is therefore authoritative; the line-too-long branch is a text match against
    Athena's own wording, which is a guess by comparison.

    Args:
      block: The state's ragged block, or None when the format is not line-delimited.
      rows: The ragged query's rows.

    Returns:
      The report's ragged figure.

    Raises:
      ValueError: If a result cell is non-empty and not a number.
    """
    if block is None:
        return {"status": "skipped", "reason": SKIP_RAGGED_NOT_LINE_DELIMITED}
    if block.get("status") == "not_computed":
        if block.get("reasonCode") == sql.RAGGED_QUERY_TOO_LARGE:
            reason = NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE
        elif _is_line_too_long(block.get("reason")):
            reason = NOT_COMPUTED_RAGGED_LINE_TOO_LONG
        else:
            reason = NOT_COMPUTED_RAGGED
        return {"status": "not_computed", "reason": reason}
    return {"count": _int(rows[0], "ragged_rows") if rows else 0, "note": NOTE_RAGGED}


def _duplicates(block, rows: list[dict]):
    """Builds the duplicate-row count, or the not-computed variant with its reason.

    Args:
      block: The state's duplicates block, or None.
      rows: The duplicates query's rows.

    Returns:
      The count, or the degraded figure.

    Raises:
      ValueError: If a result cell is non-empty and not a number.
    """
    if block and block.get("status") == "not_computed":
        return {"status": "not_computed", "reason": NOT_COMPUTED_DUPLICATES}
    return _int(rows[0], "duplicate_rows") if rows else 0


def source_shape(
    request: dict, manifest: dict
) -> tuple[list[dict], list[dict], str | None]:
    """Reads the three things every column list here is derived from: union, keys and format.

    One derivation, because assemble-report needs the grouped column COUNT before it reads the
    duplicates result and ``build`` needs the column LIST after it. Derived twice, a format
    resolved one way in one place and another way in the other would size the reader's field limit
    for a different statement than the one that ran, and the parse would fail the whole report.

    Args:
      request: The threaded request, which carries the format as a fallback.
      manifest: The source manifest.

    Returns:
      A ``(unioned columns, partition keys, format)`` tuple.

    Raises:
      KeyError: If a probed column is missing its name or type.
    """
    fmt = manifest.get("format") or request.get("format")
    files = manifest.get("files") or []
    return sql.union_columns(files), manifest.get("partitionKeys") or [], fmt


def _duplicate_samples(rows: list[dict], grouped: list[str], nested: bool, count: int):
    """Builds the sampled duplicate rows, or the sentence saying why there are none.

    ``columns`` is the GROUPING's column list, never the report's own ``exact.columns``: the two
    differ on a CSV whose header names a partition key, and heading the samples with the wrong one
    would put every value under its neighbour's name on a table that still looks right.

    A nested source has no samples to show and says so — but only when it actually has duplicates.
    With none, the empty table is the honest answer and a sentence explaining an absence nobody
    would have noticed is noise.

    An unparseable or absent cell yields no rows and leaves the count standing. The count and the
    samples come from the same statement but they are not the same finding: losing the examples is
    a degraded report, losing the count would be a wrong one.

    Args:
      rows: The duplicates query's rows.
      grouped: The grouped column names, from ``sql.grouped_column_names``.
      nested: Whether the source has a column the statement could not render.
      count: The duplicate-row count already read from the same result.

    Returns:
      ``{"columns": [...], "rows": [...]}``, or ``{"omitted": <sentence>}``.

    Raises:
      None.
    """
    if nested:
        return (
            {"omitted": SAMPLES_OMITTED_NESTED}
            if count > 0
            else {"columns": grouped, "rows": []}
        )

    sampled = _decode_json_array(rows[0], "duplicate_samples") if rows else []
    return {
        "columns": grouped,
        "rows": [
            {
                "repeats": int(entry[0]),
                "values": [_sample_cell(cell) for cell in entry[1:]],
            }
            for entry in sampled
            if _is_sampled_row(entry, len(grouped))
        ],
    }


def _is_sampled_row(entry, grouped: int) -> bool:
    """Reports whether one decoded entry is a sampled row this report can show.

    The arity check is the load-bearing one, and it is not defensive tidiness. A row is rendered
    POSITIONALLY against ``columns``, so a row with fewer cells than the grouping has columns leaves
    the trailing ones empty — and the page draws an absent cell as ``NULL``, which is a claim about
    the user's data that their file does not make. One with more cells silently loses its tail under
    the same rule. The two lists come from one statement and agree unless something moved between
    the query and the report: the grouping is re-derived from the manifest here, and a manifest is an
    object that can change between two reads.

    Dropping such a row is the right answer rather than padding it. A sample is an illustration, and
    one that cannot be laid out under its headers illustrates nothing; the COUNT beside it — the
    figure a user acts on — is unaffected either way.

    ``repeats`` is tested with ``isdecimal`` rather than ``isdigit`` because ``int`` is called on it
    and ``isdigit`` is true for characters ``int`` refuses, a superscript two among them. Athena's
    ``CAST(bigint AS varchar)`` emits neither, so this is the narrower test rather than a fix for a
    reachable case.

    Args:
      entry: One decoded entry of the samples cell, of any JSON type.
      grouped: How many columns the statement grouped by.

    Returns:
      True when the entry is a list of the repeat count followed by exactly one cell per column.

    Raises:
      None.
    """
    return (
        isinstance(entry, list)
        and len(entry) == grouped + 1
        and isinstance(entry[0], str)
        and entry[0].isdecimal()
    )


def _sample_cell(value):
    """Renders one cell of a sampled row, keeping an absence an absence.

    NULL travels as JSON null and must stay ``None``: passed through ``_truncate`` it would come
    back as the four-character string ``"null"``, which the browser cannot tell from a column whose
    value literally reads "null" — and the two are the difference between a missing field and a
    file with the word in it.

    Args:
      value: The decoded cell, ``None`` for NULL.

    Returns:
      ``None``, or the cell cut to ``MAX_SAMPLE_VALUE_CHARS`` with an ellipsis.

    Raises:
      None.
    """
    return None if value is None else _truncate(value)


def _encoding(block: dict, source_bytes: int) -> dict:
    """Builds the encoding figure with its explicit coverage percentage.

    The denominator is every byte in the source, not just the scannable ones. The scan's own total
    counts only the files it could read, so a folder of one tiny plain file beside many large
    compressed ones would otherwise render as complete coverage while understating the unexamined
    data enormously — a sentence that contradicts itself.

    An absent figure is not a clean one. Without that guard an empty block renders as zero invalid
    sequences over zero bytes: a green result manufactured from nothing.

    The percentage is stated whether or not it is flattering. A figure that silently meant "of the
    first fraction of a percent" would be worse than no figure at all.

    Args:
      block: The byte-scan's figure, or a status block.
      source_bytes: Every byte in the source, from the manifest.

    Returns:
      The report's encoding figure.

    Raises:
      None.
    """
    if "status" in block:
        return dict(block)
    if "bytesExamined" not in block:
        return {"status": "not_computed", "reason": NOT_COMPUTED_ENCODING}

    examined = block.get("bytesExamined") or 0
    total = source_bytes or block.get("bytesTotal") or 0
    percent = round(100 * examined / total, 2) if total else 100.0
    sampled = block.get("coverage") != "complete"
    note = (
        f"Sampled — {percent}% of bytes examined."
        if sampled
        else "Complete — every byte examined."
    )
    if block.get("filesSkipped"):
        note += f" {block['filesSkipped']} compressed file(s) were not scanned."
    return {
        "invalidUtf8Sequences": block.get("invalidUtf8Sequences", 0),
        "sampleOffsets": block.get("sampleOffsets", []),
        "coverage": block.get("coverage"),
        "coveragePercent": percent,
        "note": note,
    }


def _basename(key: str) -> str:
    """Reduces an object key to its file name.

    Args:
      key: The object key.

    Returns:
      The last path segment, or the key itself when it has none.

    Raises:
      None.
    """
    return key.rsplit("/", 1)[-1] or key


def _plural(count: int, singular: str) -> str:
    """Pluralises a noun by count.

    Args:
      count: The number of things.
      singular: The singular noun.

    Returns:
      The noun, pluralised by a trailing s where needed.

    Raises:
      None.
    """
    return singular if count == 1 else f"{singular}s"


def top_issues(exact: dict, approximate: dict, file_count: int) -> list[str]:
    """Builds the human-readable summary the report page leads with, under What to look at first.

    The completion notification carries none of it — only the location and the report link — so
    a live check looks for these lines on the report, not in the notification.

    Structural before statistical, deliberately. A file missing a column changes what every other
    number in the report means, and it is the finding most likely to explain a broken downstream
    table; a duplicate-row count is worth knowing but changes nothing else. The list is short,
    and whatever is first is what gets read.

    Shifted files share ONE line, however many there are, and it leads the cross-file findings. A
    folder whose export changed its header part-way through splits into two halves, and a line per
    file would fill the capped list with one sentence and push every other finding out. The line
    counts the shifted files and never the others, and points at the report's own Columns, the
    order every shifted file is read against.

    An empty result leads even the structural findings: zero rows over files that exist means
    every other figure is zero, and reporting no duplicates, no ragged rows and no missing values
    about nothing would be a green result over unexamined data. It is a finding rather than a
    raise, because a header-only CSV profiles to exactly this and is a genuine result the user
    needs delivered — failing the check would hand them a generic error and no report, making a
    real data defect indistinguishable from an infrastructure fault. The false-clean is fixed
    either way, because the verdict is no longer clean.

    Args:
      exact: The report's exact section.
      approximate: The report's approximate section.
      file_count: How many files were checked.

    Returns:
      The issues, capped at the configured count.

    Raises:
      KeyError: If a section is missing a figure the wording reads.
    """
    issues: list[str] = []

    if file_count and not exact["rowCount"]:
        issues.append(
            f"no rows were found in the {file_count} {_plural(file_count, 'file')} checked — "
            "the data may be empty or header-only"
        )

    shifted = [d["file"] for d in exact["crossFile"]["disagreements"] if d["shifted"]]
    if len(shifted) == 1:
        issues.append(
            f"{_basename(shifted[0])}'s columns don't line up with this report's Columns — a CSV "
            "is read by position, so its values are counted under the wrong columns"
        )
    elif shifted:
        issues.append(
            f"{len(shifted):,} files, starting with {_basename(shifted[0])}, have columns that "
            "don't line up with this report's Columns — a CSV is read by position, so their "
            "values are counted under the wrong columns"
        )

    for disagreement in exact["crossFile"]["disagreements"]:
        name = _basename(disagreement["file"])
        others = file_count - 1
        rest = f"the other {others} {_plural(others, 'file')} {'has' if others == 1 else 'have'}"
        if disagreement["missing"]:
            columns = ", ".join(f"`{c}`" for c in disagreement["missing"])
            issues.append(
                f"{name} is missing the {_plural(len(disagreement['missing']), 'column')} "
                f"{columns} that {rest}"
            )
        if disagreement["extra"]:
            columns = ", ".join(f"`{c}`" for c in disagreement["extra"])
            issues.append(
                f"{name} has the extra {_plural(len(disagreement['extra']), 'column')} "
                f"{columns}, which {rest.replace('has', 'does').replace('have', 'do')} not"
            )

    ragged = approximate["raggedRows"]
    if ragged.get("count"):
        issues.append(
            f"{ragged['count']:,} {_plural(ragged['count'], 'row')} have the wrong number "
            "of fields (approximate)"
        )

    encoding = approximate["encoding"]
    if encoding.get("invalidUtf8Sequences"):
        count = encoding["invalidUtf8Sequences"]
        qualifier = "" if encoding.get("coverage") == "complete" else ", in the part examined"
        issues.append(
            f"{count:,} invalid text {_plural(count, 'encoding')} found{qualifier} — this "
            "data may have been exported in the wrong character set"
        )

    typed = [c for c in exact["columns"] if c.get("nonParsingValues")]
    for column in sorted(typed, key=lambda c: -c["nonParsingValues"]):
        noun, adjective = (
            ("numbers", "numeric")
            if column["dominantType"].lower() in _NUMERIC_CASTS
            else ("dates", "date")
        )
        issues.append(
            f"`{column['name']}` has {column['nonParsingValues']:,} values that aren't "
            f"{noun} in an otherwise {adjective} column"
        )

    duplicates = exact["duplicateRows"]
    if isinstance(duplicates, int) and duplicates:
        issues.append(f"{duplicates:,} duplicate {_plural(duplicates, 'row')}")

    return issues[: config.DQ_TOP_ISSUES]


def _has_approximate(exact: dict, approximate: dict) -> bool:
    """Reports whether any figure is approximate, sampled, skipped or not computed.

    The report page reads this for its soft qualifier, that some figures are estimates, which is the
    normal case rather than a warning.

    It is true for every source this arc supports, and that is the classification rather than a
    bug worth routing around: ragged and encoding are filed under approximate whenever they are
    computed and under skipped when they are not, so neither has an exact branch. CSV gets an
    approximate ragged figure; JSON and Parquet get a skipped one.

    So this reads the approximate section alone. A not-computed duplicates figure and a skipped
    type-consistency column would each set it too, but neither can occur in a report that does not
    already carry one of the above, so testing them separately would assert against a state the
    arc cannot produce and guarding them separately would be two branches nothing could exercise.

    Because it never varies it carries no information on its own, which is why the incomplete flag
    exists beside it. The report banner qualifies softly on this one and warns only on that one, and
    the runs index carries only that one, because a list tag keyed to this flag sat on every row.

    Args:
      exact: The report's exact section, unused.
      approximate: The report's approximate section.

    Returns:
      True when any approximate figure carries a status, a note or a coverage percentage.

    Raises:
      None.
    """
    return any(
        "status" in figure or "note" in figure or "coveragePercent" in figure
        for figure in approximate.values()
    )


def _has_incomplete(exact: dict, approximate: dict) -> bool:
    """Reports whether a check was skipped or failed, rather than merely being approximate.

    The distinction the approximate flag cannot make. "Ragged rows over-count quoted delimiters"
    is a permanent property of the method and applies to every healthy CSV; "the duplicate-row
    query ran out of resources" means a figure the user asked for is not in front of them. Both
    set the approximate flag; only the second should make the report banner or the runs list say
    something is missing.

    False is reachable, and for CSV it is the common case: a CSV whose three queries all succeeded
    and whose bytes were all scanned has nothing skipped and nothing failed. JSON and Parquet never
    reach it, because the ragged figure is skipped for both.

    Args:
      exact: The report's exact section.
      approximate: The report's approximate section.

    Returns:
      True when any figure was skipped, failed, or only sampled.

    Raises:
      KeyError: If the exact section is missing its duplicates or columns.
    """
    if not isinstance(exact["duplicateRows"], int):
        return True
    if any(column.get("typeConsistency") == "skipped" for column in exact["columns"]):
        return True
    return any(
        "status" in figure or figure.get("coverage") == "sampled"
        for figure in approximate.values()
    )


def build(
    request: dict,
    manifest: dict,
    profile_rows: list[dict],
    ragged_rows: list[dict],
    duplicate_rows: list[dict],
    encoding_block: dict,
    completed_at: str,
) -> dict:
    """Assembles the whole report, recomputing nothing Athena already computed.

    The columns come from the shared union and ``sql.profiled_columns`` rather than a
    reimplementation: the result aliases are positional, so a list that diverged from the one the
    query was generated with would attribute every column's figures to the wrong column —
    silently, in a report that still looks entirely plausible. A missing cell reads as zero, so a
    column read one alias too far reports as clean.

    A column naming a partition key is therefore reported under the name the temp table declares
    it by in a CSV, and is absent from the per-column figures in JSON and Parquet, not skipped.
    There the temp table has no data column of that name, so there is no figure to mark skipped,
    and the portal types every column entry with a blank ratio it would have to invent. Neither
    marks the report incomplete: that banner points at a skipped or not-computed figure below it,
    and there is none. ``partitionNamedColumns`` says which happened to each such column;
    cross-file agreement still lists it under the files' name, since the files do carry it. Its
    other spellings are looked up by that name too, through the same ``ddl.declare_columns``
    pairing, because the entry itself carries the new one.

    ``exact.duplicateSamples`` is written only beside a duplicate COUNT — a figure that was not
    computed has no statement behind it to have sampled anything, and an empty table there would
    read as "no duplicates" rather than "not measured". Its columns come from
    ``sql.grouped_column_names``, which is the statement's own grouping and not this function's
    ``columns``: on a CSV whose header names a partition key the two lists differ.

    The completion timestamp is the only field a replay changes. The report key is a pure function
    of the request id, so a retry or a redelivery overwrites the same object rather than adding a
    second one, which is how this pipeline is replay-safe.

    Args:
      request: The threaded request, carrying the request id, location and the degraded-query
        blocks.
      manifest: The source manifest, whose partition keys and format map the profiled columns.
      profile_rows: The profile query's rows.
      ragged_rows: The ragged query's rows.
      duplicate_rows: The duplicates query's rows.
      encoding_block: The byte-scan's figure.
      completed_at: The completion timestamp.

    Returns:
      The full report dict.

    Raises:
      MissingProfileError: When the profile result carried no total row. Every exact figure comes
        from that one row, and without it the report would assemble perfectly happily — zero rows,
        every column clean, a clean verdict — and hand the user a green result over data nothing
        actually measured. A missing profile result is a failed check, not a clean one.
      KeyError: If the request carries no request id, or a probed column or partition key is
        missing its name.
      ValueError: If a result cell is non-empty and not a number.
    """
    files = manifest.get("files") or []
    union, partition_keys, fmt = source_shape(request, manifest)
    columns = sql.profiled_columns(union, partition_keys, fmt)
    sources = [
        pair.source["name"]
        for pair in ddl.declare_columns(union, partition_keys, fmt)
        if pair.declared is not None
    ]
    spellings = sql.other_spellings(files)

    total = next((row for row in profile_rows if _int(row, "is_total") == 1), None)
    if total is None:
        raise MissingProfileError("the profile result carried no total row")

    row_count = _int(total, "row_count")
    parquet = fmt == "parquet"

    duplicates = _duplicates(request.get("duplicates"), duplicate_rows)
    exact = {
        "rowCount": row_count,
        "rowCountsByFile": _row_counts_by_file(profile_rows, files),
        "duplicateRows": duplicates,
        "columns": [
            _column(
                index,
                column,
                total,
                row_count,
                _skip_reason(column, parquet),
                spellings.get(source, []),
            )
            for index, (column, source) in enumerate(zip(columns, sources, strict=True))
        ],
        "crossFile": cross_file(files, fmt, partition_keys),
    }
    if isinstance(duplicates, int):
        exact["duplicateSamples"] = _duplicate_samples(
            duplicate_rows,
            sql.grouped_column_names(union, partition_keys, fmt),
            sql.has_nested_column(union, partition_keys, fmt),
            duplicates,
        )
    approximate = {
        "raggedRows": _ragged(request.get("ragged"), ragged_rows),
        "encoding": _encoding(encoding_block, sum(f.get("size") or 0 for f in files)),
    }

    issues = top_issues(exact, approximate, len(files))
    return {
        "requestId": request["requestId"],
        "location": request.get("location"),
        "format": fmt,
        "fileCount": len(files),
        "verdict": "issues_found" if issues else "clean",
        "hasApproximateFigures": _has_approximate(exact, approximate),
        "hasIncompleteFigures": _has_incomplete(exact, approximate),
        "completedAt": completed_at,
        "partitionNamedColumns": partition_named_columns(union, partition_keys, fmt),
        "exact": exact,
        "approximate": approximate,
        "topIssues": issues,
    }
