"""describe-results — what the converter needs to know before a byte of data is read.

The column names and Athena types come from one ``GetQueryResults`` call with ``MaxResults=1``,
reading the result set's metadata and discarding the row; the result object's size comes from
one ``HeadObject``. The rows are never paged here or anywhere on this plane.

**Column names are user data.** They reach the notification on the two column refusals — the
user's own text returned to the user — and nowhere else: no log field and no span field carries
one, and a test asserts that absence.

Attributes:
  _CARRIED: The keys the validated state carries and this verb threads on unchanged.
"""

import logging

from cpcommon import clients, columns, config, errors, events, observability
from cpcommon.errors import TerminalError
from rccommon import notify, reasons
from rccommon.config import max_result_bytes

logger = logging.getLogger()
logger.setLevel(logging.INFO)
observability.init(service="results-conversion")

_CARRIED = (
    "requestId",
    "username",
    "format",
    "onConflict",
    "queryExecutionId",
    "resultsKey",
    "destination",
)


def _columns(execution_id: str) -> list[dict]:
    """Reads the result set's column names and types, in exactly one metadata call.

    Args:
      execution_id: The execution, already proved to be the actor's.

    Returns:
      One ``{name, type}`` per column, in result order, carrying ``precision`` and ``scale``
      where Athena reported them. **A decimal's parameters arrive nowhere else** — Athena puts
      the bare name in ``Type`` and the parameters in these sibling fields, so dropping them
      leaves the converter unable to build the column's dtype at all.

    Raises:
      TransientError: On a throttled or failing Athena call.
      Exception: Any other Athena failure, as a fault — the execution succeeded, so its
        metadata cannot legitimately be unreadable.
    """
    try:
        response = clients.athena().get_query_results(QueryExecutionId=execution_id, MaxResults=1)
    except Exception as exc:
        errors.raise_if_transient(exc, "Athena")
        raise
    info = ((response.get("ResultSet") or {}).get("ResultSetMetadata") or {}).get("ColumnInfo")
    described = []
    for column in info or []:
        entry = {"name": column.get("Name"), "type": column.get("Type")}
        for source, key in (("Precision", "precision"), ("Scale", "scale")):
            if isinstance(column.get(source), int):
                entry[key] = column[source]
        described.append(entry)
    return described


def _check_columns(described: list[dict], tokens: dict) -> None:
    """Refuses a result set whose names the written file could not carry faithfully.

    Args:
      described: The columns, as ``_columns`` returns them.
      tokens: The wording tokens the refusal carries, extended with the offending column.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_column_name`` for an empty name; ``duplicate_column`` for two
        names that collide once case-folded, naming the first.
    """
    names = [column["name"] for column in described]
    if any(not isinstance(name, str) or not name for name in names):
        raise TerminalError(reasons.INVALID_COLUMN_NAME, "a result column has no name")
    duplicates = columns.folded_duplicates(names)
    if duplicates:
        raise TerminalError(
            reasons.DUPLICATE_COLUMN,
            "two result columns collide once case-folded",
            tokens={**tokens, "column": duplicates[0]},
        )


def _size(key: str) -> int:
    """Reads the result object's size, in exactly one call.

    Args:
      key: The result object's key inside the user-space bucket.

    Returns:
      The object's size in bytes.

    Raises:
      TransientError: On a throttled or failing S3 call.
      Exception: Any other S3 failure, as a fault: the object Athena reported cannot be absent
        from a path the actor owns, and a denial is a grant defect rather than a user error.
    """
    try:
        head = clients.s3().head_object(Bucket=config.USER_SPACE_BUCKET, Key=key)
    except Exception as exc:
        errors.raise_if_transient(exc, "S3")
        raise
    return int(head["ContentLength"])


@observability.traced("describe-results")
@notify.notifies_on_failure("describe")
def handler(event, context) -> dict:
    """Step Functions entry point: describes the result set and applies the size cap.

    Args:
      event: The validated request object.
      context: The Lambda context, unused.

    Returns:
      The validated request plus ``columns`` and ``resultsBytes``, and nothing else.

    Raises:
      TerminalError: Any of the three refusals this verb registers.
    """
    return _describe(event)


def _describe(event) -> dict:
    """Reads the metadata and the size, refuses what the converter cannot hold, threads the rest.

    Args:
      event: The validated request object.

    Returns:
      The state after this verb: everything validate-authorize emitted plus the columns and the
      size.

    Raises:
      TerminalError: ``malformed_event`` when a carried key is missing, ``results_too_large``
        over the cap, or a column refusal.
    """
    carried = {key: events.require(event, key) for key in _CARRIED}
    tokens = {"format": carried["format"], "filename": carried["destination"]["key"].rsplit("/", 1)[-1]}
    described = _columns(carried["queryExecutionId"])
    _check_columns(described, tokens)
    size = _size(carried["resultsKey"])
    cap = max_result_bytes(carried["format"])
    if size > cap:
        raise TerminalError(
            reasons.RESULTS_TOO_LARGE, f"{size} bytes, over {cap}", tokens=tokens
        )
    logger.info("described %d column(s), %d byte(s) for %s", len(described), size, carried["username"])
    observability.info(
        "result set described",
        actor=carried["username"],
        format=carried["format"],
        column_count=len(described),
        results_bytes=size,
    )
    return {**carried, "columns": described, "resultsBytes": size}
