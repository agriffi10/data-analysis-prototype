"""The report shape, its exact/approximate tagging, and the top-issues wording (SPEC-112).

Everything here is PURE: it turns already-fetched Athena result rows, the manifest and the
byte-scan figure into the report dict. No AWS. That is what lets the tests assert the exact
report a given set of inputs produces, which matters more than usual in this module — a
subtly wrong report does not crash, it tells a user something false about their data and
they act on it.

FOUR TAGS, and the distinction is the point of the whole arc:

  exact         — type consistency, null/blank ratios, duplicate rows, row counts, and
                  cross-file column agreement. Athena computed these over every row.
  approximate   — ragged rows and encoding, WHEN COMPUTED. Each carries the reason it can
                  only be approximate, in the report, next to the number.
  skipped       — a check that could never have found anything here (encoding on Parquet
                  or .gz; type consistency on Parquet). NEVER rendered as a clean pass: a
                  green result the data did not earn is worse than no result.
  not_computed  — a check that was attempted and failed (a degraded ragged or duplicates
                  query, SPEC-111 FR-003). The report still lands, with everything else.

WHY CROSS-FILE AGREEMENT IS COMPUTED HERE AND NOT IN SQL: an Athena external table has ONE
schema for the whole folder. It would happily read a folder whose files disagree about
their columns and return a clean-looking answer — HIDING the exact disagreement the user
needs to see. So it is a reduce over inspect-source's per-file probe, not a query. It is
the check most likely to explain why a Table Builder table came out wrong.
"""

import csv
import io
import json
from collections import Counter

from . import config, sql

# ── Wording (SPEC-113 renders these verbatim; SPEC-106 forbids raw engine text) ──

#: Type consistency cannot find anything in a format that enforces types.
SKIP_TYPE_PARQUET = "Parquet enforces types in the file format, so this check cannot find anything."
SKIP_TYPE_TYPED_COLUMN = (
    "the file format defines this column's type, so it cannot hold a value that fails to parse."
)

#: Ragged rows only mean something for a line-delimited text format.
SKIP_RAGGED_NOT_LINE_DELIMITED = "not a line-delimited text format."

# BOTH caveats, never one. `split` over-reports on a quoted delimiter AND on a newline
# inside a quoted field (one logical row arriving as two physical lines). Stating only the
# first — as an earlier draft of the architecture did — would leave a user hunting for
# malformed rows that are in fact perfectly well-formed multi-line records.
NOTE_RAGGED = (
    "Approximate — over-counts rows with commas inside quotes, and rows with newlines "
    "inside quoted fields."
)

# The degraded-query reasons. NO RAW ATHENA TEXT (SPEC-106 FR-008): the engine's own
# wording names serde classes and byte offsets, which tells a user nothing and leaks
# implementation. The raw reason stays on the state block, in CloudWatch and in the
# execution history, where an operator can read it.
NOT_COMPUTED_RAGGED_LINE_TOO_LONG = (
    "a single line in this data was longer than the check can read (Athena's 200 MB limit)."
)
NOT_COMPUTED_RAGGED = "the ragged-row check couldn't be completed on this data."
# The size guard (SPEC-142 FR-003). Says what the user can DO about it, because unlike the
# two above this one has an action.
#
# NAMES BOTH CAUSES, because the guard measures the RENDERED QUERY and a file count is a
# poor proxy for its length: 300 files under a deeply nested prefix with 800-character keys
# trip it while 900 short-named files do not. Blaming the count alone would be flatly untrue
# for the first user; naming only the length would confuse the ordinary case. The action is
# the same either way, which is why one sentence can carry both.
NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE = (
    "this folder has too many files, or file names too long, for the ragged-row check to "
    "compare each file against its own columns. Please check a smaller folder."
)
NOT_COMPUTED_ENCODING = "the character-encoding check didn't produce a result."
NOT_COMPUTED_DUPLICATES = (
    "finding duplicates means comparing every column across the whole dataset, and that "
    "was too large to complete here."
)

#: Athena's wording when the raw-line table hit the 200 MB single-line limit. Matched on
#: TEXT for the same reason check-query matches its timeout: Athena reports it as a generic
#: failure with a message, not a distinct state. A miss is mild and one-way — the user gets
#: the generic sentence instead of the specific one, never a wrong outcome.
_LINE_TOO_LONG_MARKERS = ("line too long", "too long in text file", "max line length", "line length")

#: The casts the profile query tried, in report order (must match dqcommon.sql).
_CAST_TYPES = ("bigint", "double", "timestamp", "date")
_NUMERIC_CASTS = frozenset({"bigint", "double"})

#: Which bounded sample matches a dominant type's FAMILY. A numeric-dominant column wants
#: examples of values that are not numbers; a temporal one wants values that are not dates.
_SAMPLE_FOR = {"bigint": "non_numeric", "double": "non_numeric", "timestamp": "non_temporal", "date": "non_temporal"}

#: A column whose dominant type covers too little of its non-null values is not a broken
#: numeric column — it is free text that happens to contain numbers.
_TEXT = "text"

#: Longest offending-value example the report will carry (see _json_array).
MAX_SAMPLE_VALUE_CHARS = 200


class MissingProfileError(ValueError):
    """The profile result had no total row; the caller raises the terminal."""


def parse_result(body: bytes) -> list[dict]:
    """Parse an Athena CSV result file into header-keyed rows.

    Athena quotes result fields, so ``csv`` handles embedded commas, quotes and newlines
    correctly — which the offending-value samples genuinely contain, since they are drawn
    from the worst-formed values in the column. A NULL arrives as an empty field and is
    indistinguishable from an empty string; every field this module reads is either a
    number or a JSON array, so that ambiguity cannot reach a figure.

    Safe to read whole: every result set here is O(files x columns) or exactly one row —
    never O(rows) (SPEC-111 FR-003).

    Decoded with ``errors="replace"`` rather than strictly. Hive's text readers already
    substitute U+FFFD, so Athena's result file should always be valid UTF-8 — but the
    offending-value samples in it are literally the worst-formed values in the user's data,
    on a source this check flagged BECAUSE it may be mis-encoded. A UnicodeDecodeError here
    would escape as a raw Python error after every query had already run, to spare a
    replacement character in one example value.
    """
    return list(csv.DictReader(io.StringIO(body.decode("utf-8", errors="replace"))))


def _int(row: dict, key: str) -> int:
    value = (row.get(key) or "").strip()
    return int(value) if value else 0


def _json_array(row: dict, key: str) -> list:
    """Decode one bounded sample array.

    The query renders these with ``json_format`` precisely so this is a parse rather than a
    guess: Athena's bare array rendering (``[N/A, -, 1,024]``) leaves the elements unquoted,
    and a value containing a comma — the canonical CSV defect, and often the very reason the
    column was flagged — would split into two wrong examples.
    """
    raw = (row.get(key) or "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(parsed, list):
        # json_format renders a NULL aggregate — max_by matched no row — as the string
        # "null". Passed through, that would put `sampleOffending: null` in the report where
        # SPEC-113 expects a list.
        return []
    # Each VALUE is bounded too, not just the count. DQ_OFFENDING_VALUE_SAMPLE caps how many
    # examples a column contributes; nothing caps how long one is, and an Athena varchar has
    # no length limit. Ten multi-megabyte values across 200 columns would bloat the report
    # object itself — and an example that long tells the reader nothing a truncated one
    # doesn't.
    return [_truncate(value) for value in parsed]


def _truncate(value):
    text = value if isinstance(value, str) else json.dumps(value)
    return text if len(text) <= MAX_SAMPLE_VALUE_CHARS else text[:MAX_SAMPLE_VALUE_CHARS] + "…"


def _is_line_too_long(reason) -> bool:
    lowered = (reason or "").lower()
    return any(marker in lowered for marker in _LINE_TOO_LONG_MARKERS)


def _skip_reason(column: dict, parquet: bool) -> str:
    """Why type consistency was not checked for this column, or "" when it was.

    Two different reasons, and they must not be collapsed: Parquet skips EVERY column
    because the format enforces types, while a typed column in a JSON source skips because
    that particular column cannot hold an unparseable value. Both are honest skips; a user
    reading "Parquet enforces types" under a JSON report would rightly not believe the rest.
    """
    if parquet:
        return SKIP_TYPE_PARQUET
    return "" if column["type"] == "string" else SKIP_TYPE_TYPED_COLUMN


def _column(index: int, column: dict, total: dict, row_count: int, skip_reason: str) -> dict:
    """Build one column's exact findings from the profile query's total row."""
    alias = f"c{index}"
    missing = _int(total, f"{alias}_missing")
    non_null = row_count - missing
    entry = {
        "name": column["name"],
        "nullBlankRatio": round(missing / row_count, 4) if row_count else 0.0,
    }

    if skip_reason:
        # SKIPPED, never a clean pass. A green type-consistency result on Parquet would be
        # a result the data never earned — the format guarantees it, the check never ran.
        entry["typeConsistency"] = "skipped"
        entry["reason"] = skip_reason
        return entry

    if not non_null:
        # Every value is null or blank. There is no dominant type to find, and calling it
        # numeric-and-clean would be an invention.
        entry.update(dominantType=_TEXT, nonParsingValues=0, sampleOffending=[])
        return entry

    dominant, failures = min(
        ((cast, _int(total, f"{alias}_not_{cast}")) for cast in _CAST_TYPES),
        key=lambda pair: (pair[1], _CAST_TYPES.index(pair[0])),
    )
    if (non_null - failures) / non_null < config.DQ_TYPE_DOMINANCE_THRESHOLD:
        # Below the threshold this is free text, not a broken numeric column. Reporting the
        # majority of its values as "offending" would be noise the user has to wade past.
        entry.update(dominantType=_TEXT, nonParsingValues=0, sampleOffending=[])
        return entry

    entry.update(
        dominantType=dominant.upper(),
        nonParsingValues=failures,
        sampleOffending=_json_array(total, f"{alias}_sample_{_SAMPLE_FOR[dominant]}"),
    )
    return entry


def cross_file(files: list[dict]) -> dict:
    """Whether every file presents the same columns, and exactly where they differ.

    The baseline is the MODAL column set, not the first file's and not the union. The union
    would make every disagreement look like a missing column and never an extra one; the
    first file's would blame all 999 others when file 0 is the odd one out. The modal set
    names the minority, which is the file the user has to go and fix.

    THE ONE CASE WHERE THAT CLAIM DOES NOT HOLD is exactly two files that disagree: there is
    no majority, ``most_common`` breaks the tie on insertion order, and the SECOND file is
    always the one named. The finding itself is still true and still points at the right
    pair of files — but which of the two is "the odd one" is arbitrary, and no amount of
    counting can settle it, because the data does not say.
    """
    if not files:
        return {"columnsAgree": True, "disagreements": []}

    # A single file flows through the general path rather than short-circuiting: it produces
    # the identical answer (its own signature is the modal one, so it never disagrees with
    # itself), and a special case that changes no behaviour is a branch nothing can test.
    signatures = [tuple(sorted(c["name"] for c in (f.get("columns") or []))) for f in files]
    baseline = set(Counter(signatures).most_common(1)[0][0])

    disagreements = [
        {
            "file": entry["key"],
            "missing": sorted(baseline - set(signature)),
            "extra": sorted(set(signature) - baseline),
        }
        # strict=False keeps today's behaviour explicit. strict=True would be the stronger
        # claim, but it turns a length mismatch into a raise in the report path — a change
        # worth making deliberately, with the callers characterised, not as a lint fix.
        for entry, signature in zip(files, signatures, strict=False)
        if set(signature) != baseline
    ]
    return {"columnsAgree": not disagreements, "disagreements": disagreements}


def _row_counts_by_file(rows: list[dict], files: list[dict]) -> list[dict]:
    """Per-file row counts, keyed by object key rather than the ``$path`` S3 URI.

    RECONCILED AGAINST THE MANIFEST, and SORTED, for two separate reasons.

    Reconciled: Athena produces no ``"$path"`` group for a file with no data rows, so a
    header-only CSV — a failed export, one of the commoner real defects — would simply be
    ABSENT from this array rather than present with zero. A reader comparing its length to
    ``fileCount`` would find them silently disagreeing, and the empty file the user most
    needs to know about is the one that disappears.

    Sorted: a ``GROUP BY GROUPING SETS`` has no ORDER BY, so Athena's row order is arbitrary
    and not stable across executions. FR-003 requires a replay to differ ONLY in
    ``completedAt``; without this, a re-run that produced a second Athena execution would
    differ by ordering alone and SPEC-113 would list files in a different order each time.
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
    """``s3://bucket/a/b.csv`` -> ``a/b.csv``."""
    if not path.startswith("s3://"):
        return path
    _, _, rest = path[len("s3://") :].partition("/")
    return rest


def _ragged(block, rows: list[dict]) -> dict:
    """The ragged figure, or the skipped/not_computed variant carrying its reason."""
    if block is None:
        # null, not not_computed: JSON and Parquet rows are not line-delimited fields, so
        # the concept never applied. "We tried and failed" and "this could never apply" are
        # different things and the report must not blur them.
        return {"status": "skipped", "reason": SKIP_RAGGED_NOT_LINE_DELIMITED}
    if block.get("status") == "not_computed":
        # reasonCode FIRST: it is a marker this codebase wrote (start-profile-query's size
        # guard), so it is authoritative. The line-too-long branch below is a text match
        # against Athena's own wording, which is a guess by comparison.
        if block.get("reasonCode") == sql.RAGGED_QUERY_TOO_LARGE:
            reason = NOT_COMPUTED_RAGGED_QUERY_TOO_LARGE
        elif _is_line_too_long(block.get("reason")):
            reason = NOT_COMPUTED_RAGGED_LINE_TOO_LONG
        else:
            reason = NOT_COMPUTED_RAGGED
        return {"status": "not_computed", "reason": reason}
    return {"count": _int(rows[0], "ragged_rows") if rows else 0, "note": NOTE_RAGGED}


def _duplicates(block, rows: list[dict]):
    """The duplicate-row count, or the not_computed variant carrying its reason."""
    if block and block.get("status") == "not_computed":
        return {"status": "not_computed", "reason": NOT_COMPUTED_DUPLICATES}
    return _int(rows[0], "duplicate_rows") if rows else 0


def _encoding(block: dict, source_bytes: int) -> dict:
    """The encoding figure with its explicit coverage percentage, or the skipped variant.

    THE DENOMINATOR IS EVERY BYTE IN THE SOURCE, not just the scannable ones. byte-scan's
    own ``bytesTotal`` counts only the files it could read, so a folder of one 13-byte .csv
    beside ninety-nine 1 GiB .csv.gz would otherwise render:

        "Sampled — 100.0% of bytes examined. 99 compressed file(s) were not scanned."

    — a sentence that contradicts itself and understates the unexamined data by ~99 GB.
    Phase 1 fixed the "complete" LABEL for this case and left the percentage wrong; this is
    the other half.
    """
    if "status" in block:
        return dict(block)
    if "bytesExamined" not in block:
        # An absent figure is not a clean one. Without this, an empty block renders as zero
        # invalid sequences over zero bytes — a green result manufactured from nothing.
        return {"status": "not_computed", "reason": NOT_COMPUTED_ENCODING}

    examined = block.get("bytesExamined") or 0
    total = source_bytes or block.get("bytesTotal") or 0
    percent = round(100 * examined / total, 2) if total else 100.0
    sampled = block.get("coverage") != "complete"
    # The percentage is stated whether or not it is flattering. A figure that silently
    # meant "of the first 0.8%" would be worse than no figure at all.
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
    return key.rsplit("/", 1)[-1] or key


def _plural(count: int, singular: str) -> str:
    return singular if count == 1 else f"{singular}s"


def top_issues(exact: dict, approximate: dict, file_count: int) -> list[str]:
    """The human-readable summary SPEC-114's notification body is built from.

    STRUCTURAL BEFORE STATISTICAL, deliberately. A file missing a column changes what every
    other number in the report means, and it is the finding most likely to explain a broken
    downstream table; a duplicate-row count is worth knowing but changes nothing else. A
    notification is a sentence or two — whatever is first is what gets read.
    """
    issues: list[str] = []

    # FIRST, above even the structural findings: zero rows over files that exist means
    # every other figure in this report is zero, and reporting "no duplicates, no ragged
    # rows, no missing values" about nothing would be a green result over unexamined data
    # (SPEC-151 FR-002).
    #
    # A FINDING, NOT A RAISE. FR-002's wording says "raises or refuses", but a header-only
    # CSV — which report._row_counts_by_file's own docstring calls "a failed export, one of
    # the commoner real defects" — profiles to exactly this and is a genuine result the user
    # needs delivered. Failing the check would hand them "something went wrong" and no
    # report, making a real data defect indistinguishable from an infrastructure fault. The
    # false-clean this FR exists to remove is fixed either way, because the verdict is no
    # longer `clean`.
    if file_count and not exact["rowCount"]:
        issues.append(
            f"no rows were found in the {file_count} {_plural(file_count, 'file')} checked — "
            "the data may be empty or header-only"
        )

    for disagreement in exact["crossFile"]["disagreements"]:
        name = _basename(disagreement["file"])
        others = file_count - 1
        # "the other 1 files have" would ship straight into a notification body.
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
    """True when ANY figure is approximate, sampled, skipped or not computed (FR-003).

    SPEC-114 reads this so a notification never claims an unqualified "clean" over a sampled
    scan or a check that never ran.

    IT IS TRUE FOR EVERY SOURCE THIS ARC SUPPORTS, and that is FR-003's classification
    rather than a bug worth routing around: ragged and encoding are filed under APPROXIMATE
    whenever they are computed and under SKIPPED when they are not, so neither has an exact
    branch. CSV gets an approximate ragged figure; JSON and Parquet get a skipped one.

    So this reads the approximate section ALONE. A not-computed duplicates figure and a
    skipped type-consistency column would each set it too — but neither can occur in a
    report that does not already carry one of the above, so testing them separately would
    assert against a state the arc cannot produce, and guarding them separately would be
    two branches nothing could ever exercise.

    Because it never varies it carries no information on its own, which is why
    ``_has_incomplete`` exists beside it (user decision). SPEC-114 qualifies softly on this
    one — "some figures are estimates", the normal case — and warns only on that one.
    """
    return any(
        "status" in figure or "note" in figure or "coveragePercent" in figure
        for figure in approximate.values()
    )


def _has_incomplete(exact: dict, approximate: dict) -> bool:
    """True when a check was SKIPPED or FAILED, rather than merely being approximate.

    The distinction ``hasApproximateFigures`` cannot make (user decision). "Ragged rows
    over-count quoted commas" is a permanent property of the method and applies to every
    healthy CSV; "the duplicate-row query ran out of resources" means a figure the user
    asked for is not in front of them. Both set the approximate flag; only the second should
    make a notification say something is missing.

    FALSE is reachable and is the common case: a CSV whose three queries all succeeded and
    whose bytes were all scanned has nothing skipped and nothing failed.
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
    """Assemble the whole report. Recomputes nothing Athena already computed."""
    fmt = manifest.get("format") or request.get("format")
    files = manifest.get("files") or []
    # sql.union_columns, NOT a reimplementation: the c{i} aliases in the result set are
    # POSITIONAL, so an order that diverged from the one the query was generated with would
    # attribute every column's figures to the wrong column — silently, in a report that
    # still looks entirely plausible.
    columns = sql.union_columns(files)

    total = next((row for row in profile_rows if _int(row, "is_total") == 1), None)
    if total is None:
        # EVERY exact figure comes from this one row. Without it the report would assemble
        # perfectly happily — zero rows, every column "text" and clean, verdict CLEAN — and
        # hand the user a green result over data nothing actually measured. A missing
        # profile result is a failed check, not a clean one.
        raise MissingProfileError("the profile result carried no total row")

    row_count = _int(total, "row_count")
    parquet = fmt == "parquet"

    exact = {
        "rowCount": row_count,
        "rowCountsByFile": _row_counts_by_file(profile_rows, files),
        "duplicateRows": _duplicates(request.get("duplicates"), duplicate_rows),
        "columns": [
            _column(index, column, total, row_count, _skip_reason(column, parquet))
            for index, column in enumerate(columns)
        ],
        "crossFile": cross_file(files),
    }
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
        # The flag that actually varies: something was skipped or failed, as opposed to
        # something being approximate by nature. SPEC-114 warns on this one.
        "hasIncompleteFigures": _has_incomplete(exact, approximate),
        # THE ONLY FIELD A REPLAY CHANGES. The key is a pure function of requestId, so a
        # retry or an SQS redelivery overwrites the same object rather than adding a second
        # one — which is how this pipeline is replay-safe, since no verb in this codebase
        # does request-id idempotency checking.
        "completedAt": completed_at,
        "exact": exact,
        "approximate": approximate,
        "topIssues": issues,
    }
