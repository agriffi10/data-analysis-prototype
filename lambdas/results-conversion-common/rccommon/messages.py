"""User-facing notification text for results-conversion failures.

One place maps each reason code to friendly text, so every verb and its tests agree on the
wording. Kept ASCII. The resolution itself is ``cpcommon.messages``, which also marks these
codes valid so they pass ``TerminalError``'s raise-time validation.

``forbidden`` and ``malformed_event`` are deliberately absent — both are shared base codes and
resolve through the base table, which refuses a domain redefining either.

**No raw AWS text is ever interpolated into any of these.** The one piece of user data that
does reach a sentence is the user's own: the file name they chose, and on the two column
refusals the column name they wrote — returned to the user who wrote it and going nowhere else.

The success sentence lives here too, and it is NOT built from the failure resolver: it has no
reason code, no prefix and no fallback, and threading it through a table keyed by refusals would
make every future refusal a candidate for wording that reads as a success.

Attributes:
  _PRECISION_NOTE: The one sentence an ``.xlsx`` earns when its frame holds a number Excel
    cannot store exactly. Stated rather than hidden, and stated without naming a column or a
    value — a notification says what happened, never what the data was.
  _BODIES: Reason code to the clause following the prefix. ``{filename}`` is filled from the
    raise site where the name is known and blanks otherwise; ``{maxBytes}`` is filled from the
    cap for THAT FORMAT by ``failure_message``, so the sentence cannot drift from the constant
    that enforces it and cannot quote Parquet's ceiling at someone saving a spreadsheet;
    ``{maxCells}`` is filled from the cell cap the same way; ``{rows}``, ``{columns}`` and
    ``{count}`` are the converter's own counts of the result; ``{column}`` is the user's own
    column name; ``{timeout}`` is filled from the machine's own ceiling, so the sentence cannot
    outlive the number it describes.
  resolver: The domain-scoped resolver, carrying this plane's prefix and fallback.
"""

from cpcommon import messages as _cpmessages

from . import reasons
from .config import (
    EXCEL_MAX_CELLS,
    FORMAT_LABELS,
    MACHINE_TIMEOUT_SECONDS,
    max_result_bytes,
)

_BODIES = {
    reasons.INVALID_REQUEST: (
        "the file name or folder is not one that can be used. Please choose another and try again."
    ),
    reasons.PROTECTED_LOCATION: (
        '"{filename}" can\'t be saved there, because that folder is managed by the portal. '
        "Please choose another folder."
    ),
    reasons.EXECUTION_NOT_FOUND: (
        "that query's results could not be found. Please run the query again and save from its "
        "results."
    ),
    reasons.EXECUTION_NOT_FINISHED: (
        "that query hasn't finished yet. Please wait for it to complete and try again."
    ),
    reasons.EXECUTION_FAILED: (
        "that query didn't complete successfully, so there are no results to save."
    ),
    reasons.NO_RESULT_SET: "that statement produced no rows, so there is nothing to save.",
    reasons.RESULTS_TOO_LARGE: (
        "the results are larger than {maxBytes} and can't be converted. Please narrow the query "
        "and try again."
    ),
    reasons.DUPLICATE_COLUMN: (
        'the results have more than one column called "{column}" once case is ignored, so the '
        "file would not carry the names you saw. Please rename one in the query and run it again."
    ),
    reasons.INVALID_COLUMN_NAME: (
        "one of the result columns has no name. Please name every column in the query and run it "
        "again."
    ),
    reasons.INVALID_COLUMNS: (
        "the columns chosen for this file don't match the query's results, so nothing was saved."
    ),
    reasons.UNSUPPORTED_COLUMN_TYPE: (
        'the column "{column}" has a type that can\'t be written to "{filename}". Please cast '
        "it in the query, for example to text, and run it again."
    ),
    reasons.RESULTS_UNREADABLE: (
        'part of the results could not be read, so "{filename}" was not written. If a column\'s '
        "values don't all match the type the query gave it, casting that column will fix it; if "
        "some values run over more than one line, replacing those line breaks in the query will. "
        "Then run the query again."
    ),
    reasons.EXCEL_ROW_LIMIT: (
        'the results have {count} rows, which is more than a spreadsheet can hold, so '
        '"{filename}" was not written. Please save them as Parquet instead, or narrow the query.'
    ),
    reasons.EXCEL_CELL_LIMIT: (
        "the results have {rows} rows and {columns} columns ({count} cells), which is more than "
        'the {maxCells} cells an Excel file can be made from here, so "{filename}" was not '
        "written. Please save them as Parquet instead, or narrow the query."
    ),
    reasons.EXCEL_EXHAUSTED: (
        "the conversion ran out of time or memory before it finished, so nothing was saved. "
        "Please save them as Parquet instead, or narrow the query."
    ),
    reasons.TOO_MANY_COLUMNS: (
        'the results have {count} columns, which is more than "{filename}" can be built from. '
        "Please select fewer columns in the query and run it again."
    ),
    reasons.DESTINATION_OCCUPIED: (
        'a file called "{filename}" is already in that folder, so nothing was saved. Please '
        "choose another name, or save again and choose to replace it."
    ),
    reasons.UNEXPECTED: "something went wrong, so nothing was saved. Please try again.",
    reasons.CONVERSION_TIMED_OUT: (
        "the conversion was still running after {timeout} and was stopped. Nothing was saved."
    ),
}

resolver = _cpmessages.register(
    _BODIES,
    prefix="Couldn't save the query results{asFormat}: ",
    access_denied="You don't have access to save results there.",
    fallback="something went wrong.",
    blank_unfilled=True,
)


_PRECISION_NOTE = (
    " Excel stores numbers as approximate values, so very large whole numbers and long decimals "
    "in this file may be rounded."
)


def success_message(filename: str, fmt: str, rows: int, precision_note: bool = False) -> str:
    """Renders the one sentence a user reads when their results were saved.

    Args:
      filename: The file name they chose.
      fmt: The output format.
      rows: How many data rows the file holds. Zero is a real answer and reads as one.
      precision_note: Whether the frame held a number Excel cannot store exactly.

    Returns:
      The rendered message.

    Raises:
      None.
    """
    label = FORMAT_LABELS.get(fmt, fmt)
    plural = "row" if rows == 1 else "rows"
    sentence = f'Saved {rows:,} {plural} as {label} to "{filename}".'
    return f"{sentence}{_PRECISION_NOTE}" if precision_note else sentence


def _human_duration(seconds: int) -> str:
    """Renders a duration in the unit a person would say.

    Args:
      seconds: The duration.

    Returns:
      ``"an hour"``, ``"2 hours"`` or ``"45 minutes"``, whichever reads naturally.

    Raises:
      None.
    """
    if seconds == 3600:
        return "an hour"
    if seconds % 3600 == 0:
        return f"{seconds // 3600} hours"
    return f"{seconds // 60} minutes"


def _human_bytes(count: int) -> str:
    """Renders a byte count in the unit a person would say.

    Args:
      count: The byte count.

    Returns:
      ``"1 GB"``, ``"512 MB"`` or ``"64 KB"``, whichever unit divides it exactly first.

    Raises:
      None.
    """
    for unit, size in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if count % size == 0:
            return f"{count // size} {unit}"
    return f"{count} bytes"


def failure_message(reason: str, tokens: dict | None = None) -> str:
    """Renders the sentence a user reads for one failure.

    The format is turned into the prefix's ``{asFormat}`` clause here, and the caps are filled
    from their constants, so no raise site has to know either. The byte cap differs BY FORMAT, so
    it is read from the format's own number rather than from one constant — a size refused for
    Excel sits comfortably inside Parquet's, and quoting the wrong one would tell a user their
    results are too large when they are not.

    **Every integer is rendered with thousands separators**, the counts the converter puts on
    the state included: they arrive as integers, and a sentence naming "15728625 cells" is one a
    reader has to count the digits of. A ``bool`` is an ``int`` to Python and is not a count, so
    it is rendered as it is.

    Args:
      reason: The reason code.
      tokens: The raise site's tokens: ``format``, ``filename``, ``column`` and the counts,
        where known.

    Returns:
      The rendered message.

    Raises:
      None.
    """
    filled = dict(tokens or {})
    fmt = str(filled.pop("format", ""))
    label = FORMAT_LABELS.get(fmt, "")
    filled["asFormat"] = f" as {label}" if label else ""
    filled.setdefault("maxBytes", _human_bytes(max_result_bytes(fmt)))
    filled.setdefault("maxCells", EXCEL_MAX_CELLS)
    filled.setdefault("timeout", _human_duration(MACHINE_TIMEOUT_SECONDS))
    return resolver.message(reason, **{k: _rendered(v) for k, v in filled.items()})


def _rendered(value) -> str:
    """Renders one wording token as the text a sentence carries.

    Args:
      value: The token's value.

    Returns:
      An integer with thousands separators, and anything else as ``str`` renders it.

    Raises:
      None.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)
