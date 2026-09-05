"""User-facing notification text for results-conversion failures.

One place maps each reason code to friendly text, so every verb and its tests agree on the
wording. Kept ASCII. The resolution itself is ``cpcommon.messages``, which also marks these
codes valid so they pass ``TerminalError``'s raise-time validation.

``forbidden`` and ``malformed_event`` are deliberately absent — both are shared base codes and
resolve through the base table, which refuses a domain redefining either.

**No raw AWS text is ever interpolated into any of these.** The one piece of user data that
does reach a sentence is the user's own: the file name they chose, and on the two column
refusals the column name they wrote — returned to the user who wrote it and going nowhere else.

Attributes:
  _BODIES: Reason code to the clause following the prefix. ``{filename}`` is filled from the
    raise site where the name is known and blanks otherwise; ``{maxBytes}`` is filled from the
    cap by ``failure_message`` so the sentence cannot drift from the constant that enforces it;
    ``{column}`` is the user's own column name; ``{timeout}`` is filled from the machine's own
    ceiling, so the sentence cannot outlive the number it describes.
  resolver: The domain-scoped resolver, carrying this plane's prefix and fallback.
"""

from cpcommon import messages as _cpmessages

from . import reasons
from .config import FORMAT_LABELS, MACHINE_TIMEOUT_SECONDS, RESULTS_MAX_BYTES

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

    The format is turned into the prefix's ``{asFormat}`` clause here, and the cap is filled
    from the constant, so no raise site has to know either.

    Args:
      reason: The reason code.
      tokens: The raise site's tokens: ``format``, ``filename`` and ``column`` where known.

    Returns:
      The rendered message.

    Raises:
      None.
    """
    filled = dict(tokens or {})
    label = FORMAT_LABELS.get(str(filled.pop("format", "")), "")
    filled["asFormat"] = f" as {label}" if label else ""
    filled.setdefault("maxBytes", _human_bytes(RESULTS_MAX_BYTES))
    filled.setdefault("timeout", _human_duration(MACHINE_TIMEOUT_SECONDS))
    return resolver.message(reason, **{k: str(v) for k, v in filled.items()})
