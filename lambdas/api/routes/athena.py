"""Start, status, results and stop — the four Athena calls the workspace rides on.

**The SQL is opaque here.** It is not parsed, split, normalised, trimmed, lower-cased, validated
or logged, and it reaches ``QueryString`` byte-identical. The Data Explorer discloses the
statement it is about to bill a user for, and that disclosure is trusted BECAUSE it is the same
bytes this route received; a ``strip()`` in the middle still runs, still returns rows, still looks
right, and quietly makes the disclosure a claim about a different statement.

**Three values leave the wire entirely.** The workgroup, the results location and the caller's
identity are derived here — from this function's environment and the verified claim — so a body
naming any of them is refused rather than obeyed.

**A failed query is a 200.** The execution failing is data about the query, not a failure of the
request: ``GetQueryExecution`` succeeds and the reason arrives as a field. Six authored sentences
in the browser are chosen by reading that field, so an implementation that maps a FAILED execution
onto an error envelope retires all six at once and every failed query says "Contact the
Administrator" instead.

**Reading results too early is a 409, classified by MESSAGE and never by exception name.**
``InvalidRequestException`` is also what Athena raises for a malformed query at submit, so a
mapper keyed on the name turns a syntax error into "still running" — and passes any test that
exercises one of the two at a time, which is exactly how the original defect survived.

Attributes:
  ATHENA_MAX_RESULTS: Athena's own ceiling on ``MaxResults``, which the page size is clamped to.
  MIN_MAX_ROWS: The smallest page a caller may ask for.
  DEFAULT_MAX_ROWS: The page size when a caller names none, matching the browser's own default.
  NOT_FINISHED_MARKERS: The lowercased fragments that identify a too-early results read inside an
    ``InvalidRequestException``'s message. Two spellings, because Athena's own wording has
    carried both the machine name and the sentence.
  SYNTAX_MARKERS: The fragments that identify a statement the user can FIX inside the same
    exception. They exist so the browser can say "there is a syntax error in your query" instead
    of the generic sentence — which is reserved for what a user cannot act on.

    **They do not reproduce the browser's rules, and are not meant to.** Athena's own messages of
    this family carry ``line N:M``, which the pattern beside this tuple matches, so a column error
    refused at submit is classified here as a statement the user can fix while the same message on
    the failed-execution path reaches the browser's more specific rule about a column. The two
    paths therefore answer one message with two different sentences — accepted, because both tell
    the user to go and look at their SQL, and the rule this serves is that neither says "contact
    the administrator" for something they can fix.
  INVALID_REQUEST_CODE: The one Athena exception name this module reads, and it is ambiguous by
    itself — it covers a malformed query at submit, a results read before an execution finished,
    and a stop against an execution that already has. Each site says which of those it means and
    decides on the MESSAGE where the distinction matters.
"""

import re
from typing import Any

from apicommon import identity
from apicommon.config import athena_workgroup, user_space_bucket
from apicommon.context import RequestContext
from apicommon.envelope import ApiError
from cpcommon import observability
from cpcommon.app_managed import athena_results_prefix

ATHENA_MAX_RESULTS = 1000
MIN_MAX_ROWS = 1
DEFAULT_MAX_ROWS = 100

NOT_FINISHED_MARKERS = ("invalid_query_execution_state", "has not yet finished")

SYNTAX_MARKERS = ("syntax_error", "mismatched input", "parse error")

_LINE_COLUMN_RE = re.compile(r"line \d+:\d+")

INVALID_REQUEST_CODE = "InvalidRequestException"


def _client(context: RequestContext) -> Any:
    """The Athena client for this caller.

    Every route here is on the user plane. A catalog call made on the execution role would query
    the catalog as the function rather than as the person, which succeeds — against everybody's
    data — and is the failure the plane rule exists to stop.

    Args:
      context: The authenticated request.

    Returns:
      An Athena client carrying the caller's session tags.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
    """
    return identity.user_client("athena", context.acting_as)


def _execution_id(context: RequestContext) -> str:
    """The execution id this request named.

    Args:
      context: The authenticated request.

    Returns:
      The id from the path.

    Raises:
      None. The matcher refuses an empty segment, so a route that dispatched has one.
    """
    return context.path_params["queryExecutionId"]


def output_location(username: str) -> str:
    """Where this caller's results are written.

    **One function, deliberately.** The target environment moves this: an Identity Center enabled
    workgroup appends its own ``${user_id}`` to the results path, so what a query writes may stop
    being what a caller asked for. Everything that reads a result object back from the path it
    requested breaks that day, and it should be one edit here rather than a hunt.

    Args:
      username: The VERIFIED username, never a value from the request.

    Returns:
      The ``s3://`` prefix Athena writes to.

    Raises:
      ConfigError: If the user-space bucket is unset.
    """
    return f"s3://{user_space_bucket()}/{athena_results_prefix(f'{username}/')}"


def start(context: RequestContext) -> dict[str, Any]:
    """Starts a query and returns its execution id.

    Args:
      context: The authenticated request, carrying ``sql`` and an optional ``database``.

    Returns:
      The execution id.

    Raises:
      ApiError: ``QuerySyntaxError`` when Athena refuses the STATEMENT, ``InvalidRequest`` when
        it refuses the request for any other reason, and ``InternalError`` if it accepts the call
        and returns no id.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      ConfigError: If the workgroup or the bucket is unset.
      Exception: Whatever Athena raised, for the classifier above.
    """
    body = context.body if isinstance(context.body, dict) else {}
    sql = str(body.get("sql", ""))
    database = body.get("database")

    request: dict[str, Any] = {
        "QueryString": sql,
        "WorkGroup": athena_workgroup(),
        "ResultConfiguration": {"OutputLocation": output_location(context.acting_as.username)},
    }
    if database:
        request["QueryExecutionContext"] = {"Database": str(database)}

    observability.stamp(sql_bytes=len(sql.encode("utf-8")))
    if database:
        observability.stamp(database=str(database))

    try:
        response = _client(context).start_query_execution(**request)
    except Exception as exc:
        if identity.aws_error_code(exc) == INVALID_REQUEST_CODE:
            if _is_syntax_error(exc):
                raise ApiError("QuerySyntaxError", "athena rejected the statement") from exc
            raise ApiError("InvalidRequest", "athena refused the request at submit") from exc
        raise
    execution_id = response.get("QueryExecutionId")
    if not execution_id:
        raise ApiError("InternalError", "athena accepted the query and returned no execution id")

    observability.stamp(execution_id=str(execution_id))
    return {"queryExecutionId": str(execution_id)}


def status(context: RequestContext) -> dict[str, Any]:
    """Reports one execution's state, verbatim.

    ``stateChangeReason`` is Athena's engine text and travels unchanged — never truncated, never
    mapped to a code, never merged into an error's ``detail``. It is also never a log field: the
    engine quotes the offending value back, so the reason routinely carries a user's own cell
    contents.

    Args:
      context: The authenticated request.

    Returns:
      The execution's state, reason, statistics and results location.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Whatever Athena raised, for the classifier above.
    """
    execution_id = _execution_id(context)
    observability.stamp(execution_id=execution_id)

    response = _client(context).get_query_execution(QueryExecutionId=execution_id)
    execution = response.get("QueryExecution") or {}
    state = (execution.get("Status") or {}).get("State") or "QUEUED"
    statistics = execution.get("Statistics") or {}

    observability.stamp(state=str(state))
    return {
        "queryExecutionId": execution_id,
        "state": str(state),
        "stateChangeReason": (execution.get("Status") or {}).get("StateChangeReason"),
        "dataScannedBytes": statistics.get("DataScannedInBytes"),
        "engineExecutionTimeMillis": statistics.get("EngineExecutionTimeInMillis"),
        "outputLocation": (execution.get("ResultConfiguration") or {}).get("OutputLocation"),
    }


def results(context: RequestContext) -> dict[str, Any]:
    """Returns one page of a succeeded query's results.

    Args:
      context: The authenticated request, carrying an optional ``nextToken`` and ``maxRows``.

    Returns:
      The page's columns, rows and continuation token.

    Raises:
      ApiError: ``InvalidRequest`` for a page size outside its range; ``QueryNotFinished`` when
        the execution has not finished, distinguished from a malformed query by the MESSAGE.
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Whatever Athena raised, for the classifier above.
    """
    execution_id = _execution_id(context)
    observability.stamp(execution_id=execution_id)
    token = context.query.get("nextToken")
    page_size = _page_size(context.query.get("maxRows"))

    request: dict[str, Any] = {
        "QueryExecutionId": execution_id,
        "MaxResults": min(page_size + 1 if not token else page_size, ATHENA_MAX_RESULTS),
    }
    if token:
        request["NextToken"] = token

    try:
        response = _client(context).get_query_results(**request)
    except Exception as exc:
        if _is_not_finished(exc):
            raise ApiError("QueryNotFinished", "the execution has not reached SUCCEEDED") from exc
        if identity.aws_error_code(exc) == INVALID_REQUEST_CODE:
            raise ApiError("InvalidRequest", "athena refused the results request") from exc
        raise

    result_set = response.get("ResultSet") or {}
    columns = [
        {"name": str(column.get("Name") or ""), "type": str(column.get("Type") or "")}
        for column in (result_set.get("ResultSetMetadata") or {}).get("ColumnInfo") or []
    ]
    rows = [
        [cell.get("VarCharValue") for cell in (row.get("Data") or [])]
        for row in result_set.get("Rows") or []
    ]
    if not token:
        rows = _without_header(rows, columns)

    observability.stamp(row_count=len(rows), column_count=len(columns))
    return {"columns": columns, "rows": rows, "nextToken": response.get("NextToken")}


def _page_size(raw: str | None) -> int:
    """Reads and bounds the requested page size.

    A query string carries strings, so the range check cannot live in the contract's declaration
    and lives here. The browser never sends an out-of-range value, which is exactly why the check
    has to exist: nothing else would notice.

    Args:
      raw: The caller's ``maxRows``, or None.

    Returns:
      The page size to request.

    Raises:
      ApiError: ``InvalidRequest`` if the value is not an integer within range.
    """
    if raw is None:
        return DEFAULT_MAX_ROWS
    try:
        size = int(raw)
    except ValueError as exc:
        raise ApiError("InvalidRequest", "maxRows is not an integer") from exc
    if not MIN_MAX_ROWS <= size <= ATHENA_MAX_RESULTS:
        raise ApiError("InvalidRequest", "maxRows is outside its permitted range")
    return size


def _without_header(rows: list[list[Any]], columns: list[dict[str, str]]) -> list[list[Any]]:
    """Drops Athena's repeated column-name row from the first page of a SELECT.

    Athena repeats the column names as the first row of the FIRST page only, and only for a
    SELECT. The row is dropped when it matches the column metadata element for element — which
    means a first data row that genuinely equals its own headers is dropped too. That is today's
    behaviour and it is preserved rather than quietly fixed here, because fixing it is a
    behaviour change belonging to whichever spec wants the behaviour.

    Args:
      rows: The page's rows.
      columns: The page's columns.

    Returns:
      The rows, without the header row.

    Raises:
      None.
    """
    if not rows:
        return rows
    first = rows[0]
    if len(first) == len(columns) and all(
        cell == column["name"] for cell, column in zip(first, columns, strict=True)
    ):
        return rows[1:]
    return rows


def _athena_message(exc: BaseException) -> str:
    """The service's own message, lowercased, or the empty string.

    Read to CLASSIFY and for nothing else: it reaches no response body — ``detail`` is authored
    at the raise site — and no log field, because Athena quotes a user's own values back in it.

    Args:
      exc: The exception Athena raised.

    Returns:
      The lowercased message, empty when there is none to read.

    Raises:
      None.
    """
    response = getattr(exc, "response", None)
    error = response.get("Error") if isinstance(response, dict) else None
    return str(error.get("Message", "") if isinstance(error, dict) else "").lower()


def _is_syntax_error(exc: BaseException) -> bool:
    """Whether Athena refused this statement for something the USER can fix.

    **Not every submit-time refusal is one.** An unusable workgroup and a malformed request
    parameter arrive under the same exception name and are nobody's to fix but an operator's, so
    they keep the generic sentence. Only a statement Athena could not parse gets wording that
    tells the user to go and look at their SQL.

    Most syntax errors never reach here at all — Athena accepts the query and the execution
    reaches FAILED, where the reason travels on a 200 and the browser reads it. This covers the
    subset rejected at submit, which used to arrive with the engine's own text and now arrives as
    a code.

    Args:
      exc: The exception Athena raised.

    Returns:
      True if the statement itself was refused.

    Raises:
      None.
    """
    message = _athena_message(exc)
    return any(marker in message for marker in SYNTAX_MARKERS) or bool(
        _LINE_COLUMN_RE.search(message)
    )


def _is_not_finished(exc: BaseException) -> bool:
    """Whether this failure is a results read against an execution that has not finished.

    **Keyed on the message, never on the exception name.** ``InvalidRequestException`` is also
    what Athena raises for a MALFORMED_QUERY at submit; a name-keyed classifier turns a syntax
    error into "the query is still running", and passes every test that exercises one of the two
    conditions at a time.

    The message is read here and reaches nothing else: not the response body, whose ``detail`` is
    authored above, and not a log field.

    Args:
      exc: The exception Athena raised.

    Returns:
      True if this is the too-early read.

    Raises:
      None.
    """
    if identity.aws_error_code(exc) != INVALID_REQUEST_CODE:
        return False
    message = _athena_message(exc)
    return any(marker in message for marker in NOT_FINISHED_MARKERS)


def stop(context: RequestContext) -> dict[str, Any]:
    """Stops one execution.

    **A refusal Athena raises for this call is reported as success**, and the whole family is
    taken rather than the terminal case alone: ``InvalidRequestException`` covers an execution
    that has already finished and an id Athena will not accept, and the caller cannot act on
    either. Today's browser swallows every ``stopQuery`` failure at the call site, so answering
    200 preserves what a user sees exactly; the poller reports the real state either way.

    **No ownership check, and none is removed.** Athena authorizes these calls by WORKGROUP and
    this deployment has one, so a caller holding another user's execution id can already stop it.
    That is a pre-existing exposure recorded against the spec, not something this route invents
    or is free to close — a real fix needs an execution-to-owner record that does not exist. What
    ships instead is attribution: the span carries the actor and the execution id.

    Args:
      context: The authenticated request.

    Returns:
      An empty object.

    Raises:
      IdentityUnavailableError: If the caller's role cannot be assumed.
      Exception: Whatever Athena raised, for the classifier above.
    """
    execution_id = _execution_id(context)
    observability.stamp(execution_id=execution_id)

    try:
        _client(context).stop_query_execution(QueryExecutionId=execution_id)
    except Exception as exc:
        if identity.aws_error_code(exc) == INVALID_REQUEST_CODE:
            return {}
        raise
    return {}
