"""validate-authorize — the results-conversion Step Function's first task.

Parses the SQS record, reads the trusted actor out of the API's identity block, authorizes the
DESTINATION space, contains the destination key inside it, refuses the app-managed folders, and
proves the execution is the actor's by the path Athena wrote its result to. Read-only: nothing
is listed, read row by row, or written here.

**Ownership is a question about a path.** An execution id is a claim anyone can type; what makes
it the actor's is that Athena recorded its output under the results prefix the API starts every
one of that user's queries with — built by the one function the API and this verb share. An id
Athena does not know and an execution written elsewhere refuse with ONE code, so the refusal
cannot say whether another user's execution exists.

**A refusal is a return value from the caller's point of view**: every expected refusal is a
``TerminalError`` carrying a reason code, notified to the actor here once the actor is bound
and recorded by the machine's Catch. Only an unpredicted fault raises past that.

Attributes:
  _ALLOWED_FIELDS: The complete set of top-level request fields. Unknown fields are REJECTED
    rather than ignored: a field the producer thinks it is sending and this verb silently drops
    is a contract break that shows up as behaviour nobody asked for.
  _UUID_RE: The shape of an Athena execution id. A value of any other shape cannot name an
    execution and is refused as a malformed request rather than sent to Athena.
  _PENDING: The two Athena states in which the result set does not exist yet.
  _SUCCEEDED: The one state in which it does.
  _DML: The only statement type that writes rows.
"""

import logging
import re
from datetime import datetime

from cpcommon import actor as cpactor
from cpcommon import clients, config, errors, events, observability, results
from cpcommon.errors import TerminalError
from cpcommon.paths import has_dot_segment
from rccommon import authz, notify, paths, reasons
from rccommon.config import FORMATS, ON_CONFLICT

logger = logging.getLogger()
logger.setLevel(logging.INFO)
observability.init(service="results-conversion")

_ALLOWED_FIELDS = frozenset(
    {
        "requestId",
        "queryExecutionId",
        "format",
        "destination",
        "onConflict",
        "submittedAt",
        "identity",
        "traceparent",
    }
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_PENDING = frozenset({"QUEUED", "RUNNING"})
_SUCCEEDED = "SUCCEEDED"
_DML = "DML"


def _check_contract(req) -> None:
    """Fails the request if its shape is not the one this contract defines.

    Shape and vocabulary only. Every length and content cap on the destination lives in
    ``rccommon.paths``, because this verb is the one authority on the request and the route's
    validator is deliberately shape-only.

    Args:
      req: The parsed request body.

    Returns:
      None.

    Raises:
      TerminalError: ``malformed_event`` when the body is not an object, names a field outside
        the contract, or carries no usable request id; ``invalid_request`` for a format or
        conflict answer outside the closed vocabulary, an execution id that is not one, a
        submission time that is not an instant, or a destination that is not an object.
    """
    if not isinstance(req, dict):
        raise TerminalError(events.MALFORMED, "request body is not an object")
    unknown = sorted(set(req) - _ALLOWED_FIELDS)
    if unknown:
        raise TerminalError(events.MALFORMED, f"unknown request fields: {', '.join(unknown)}")
    request_id = req.get("requestId")
    if not isinstance(request_id, str) or not request_id.strip():
        raise TerminalError(events.MALFORMED, "requestId missing or not a string")
    if not events.in_vocabulary(req.get("format"), FORMATS):
        raise TerminalError(reasons.INVALID_REQUEST, f"unknown format {req.get('format')!r}")
    if not events.in_vocabulary(req.get("onConflict"), ON_CONFLICT):
        raise TerminalError(
            reasons.INVALID_REQUEST, f"unknown conflict answer {req.get('onConflict')!r}"
        )
    execution_id = req.get("queryExecutionId")
    if not isinstance(execution_id, str) or not _UUID_RE.fullmatch(execution_id):
        raise TerminalError(reasons.INVALID_REQUEST, "queryExecutionId is not an execution id")
    _check_submitted_at(req.get("submittedAt"))
    if not isinstance(req.get("destination"), dict):
        raise TerminalError(reasons.INVALID_REQUEST, "destination missing or malformed")


def _check_submitted_at(value) -> None:
    """Confirms the submission time is a real, zone-aware instant.

    Args:
      value: The request's submission time.

    Returns:
      None.

    Raises:
      TerminalError: ``invalid_request`` when it is missing, unparseable or naive.
    """
    if not isinstance(value, str) or not value:
        raise TerminalError(reasons.INVALID_REQUEST, "submittedAt missing")
    try:
        submitted = datetime.fromisoformat(value)
    except ValueError as err:
        raise TerminalError(reasons.INVALID_REQUEST, f"{value!r} is not an instant") from err
    if submitted.tzinfo is None:
        raise TerminalError(reasons.INVALID_REQUEST, f"{value!r} names no time zone")


def _describe_execution(execution_id: str) -> dict:
    """Reads the execution Athena recorded, in exactly one call.

    Args:
      execution_id: The claimed execution id.

    Returns:
      Athena's ``QueryExecution`` document.

    Raises:
      TerminalError: ``execution_not_found`` when Athena knows no such execution.
      TransientError: On a throttled or failing Athena call.
    """
    try:
        response = clients.athena().get_query_execution(QueryExecutionId=execution_id)
    except Exception as exc:
        errors.raise_if_transient(exc, "Athena")
        if errors.error_code(exc) == "InvalidRequestException":
            raise TerminalError(
                reasons.EXECUTION_NOT_FOUND, f"Athena knows no execution {execution_id}"
            ) from exc
        raise
    execution = response.get("QueryExecution")
    return execution if isinstance(execution, dict) else {}


def _owned_results_key(execution: dict, username: str) -> str:
    """Proves the execution wrote its result under the actor's own results prefix.

    Args:
      execution: Athena's ``QueryExecution`` document.
      username: The verified username.

    Returns:
      The result object's key inside the user-space bucket.

    Raises:
      TerminalError: ``execution_not_found`` when the recorded output location is absent, sits
        anywhere else, or carries a dot segment — the same code as an unknown id, on purpose.
    """
    bucket = config.USER_SPACE_BUCKET
    location = (execution.get("ResultConfiguration") or {}).get("OutputLocation")
    prefix = results.user_results_prefix(bucket, username)
    if not isinstance(location, str) or not location.startswith(prefix):
        raise TerminalError(
            reasons.EXECUTION_NOT_FOUND, "the execution's output is not under the actor's results"
        )
    key = location[len(f"s3://{bucket}/") :]
    # The prefix check is a startswith, so a location Athena reported as
    # `.../athenaresults/../../bob/x.csv` passes it while naming another user's object. Nothing
    # writes such a location today — the API builds one from the verified username alone — but
    # this is the one place an S3-supplied path becomes a key the converter will read, and a
    # containment rule that holds only while every producer stays careful is not a rule.
    if has_dot_segment(key):
        raise TerminalError(
            reasons.EXECUTION_NOT_FOUND, "the execution's output location carries a dot segment"
        )
    return key


def _check_result_set(execution: dict) -> None:
    """Confirms the execution finished, successfully, with a statement that writes rows.

    Args:
      execution: Athena's ``QueryExecution`` document.

    Returns:
      None.

    Raises:
      TerminalError: ``execution_not_finished`` while queued or running, ``execution_failed``
        for any terminal state but success, ``no_result_set`` for a statement that is not DML.
    """
    state = (execution.get("Status") or {}).get("State")
    if state in _PENDING:
        raise TerminalError(reasons.EXECUTION_NOT_FINISHED, f"execution is {state}")
    if state != _SUCCEEDED:
        raise TerminalError(reasons.EXECUTION_FAILED, f"execution ended {state!r}")
    statement = execution.get("StatementType")
    if statement != _DML:
        raise TerminalError(reasons.NO_RESULT_SET, f"statement type is {statement!r}")


@observability.traced("validate-authorize")
@notify.notifies_on_failure("validate", notify_terminal=False)
def handler(event, context) -> dict:
    """Step Functions entry point: parses, verifies, authorizes and proves ownership.

    ``@traced`` is outermost, above ``@notifies_on_failure``: the latter catches on its way
    out, so if it were outermost the span would close as successful on an invocation that
    actually failed and notified. An unexpected failure here happens against the raw SQS array
    with no trusted actor yet, so the wrapper's failure emit is a safe no-op in that window.

    Args:
      event: The EventBridge Pipe envelope carrying the SQS record.
      context: The Lambda context, unused.

    Returns:
      The validated request the downstream states consume.

    Raises:
      TerminalError: ``unauthorized`` before the actor is bound, or any validation reason after.
    """
    return _validate_and_authorize(event)


def _validate_and_authorize(event) -> dict:
    """Reads the trusted actor, authorizes the destination, and proves the execution is theirs.

    The actor comes from the ``identity`` block the API stamped, never from a body username and
    never from a flat ``actor`` field. From the point the actor is known, a refusal notifies
    them before the Catch records it; a failure before it has no trusted recipient and stays
    notification-free.

    The request id rides on that refusal from the start, a contract refusal included, because a
    reader settles its in-flight record by matching it and the payload drops an id that is not a
    usable string. The format joins it only once validated, since it is rendered into the sentence.

    Args:
      event: The EventBridge Pipe envelope.

    Returns:
      Exactly: request id, username, format, conflict answer, execution id, result key and the
      resolved destination. A downstream state reading a key that is absent raises an
      uncatchable ``States.Runtime``, so the key set is a contract the machine's own test pins.

    Raises:
      TerminalError: ``unauthorized`` for an unusable identity block, or any reason this plane
        registers.
    """
    req = events.parse_sqs_request(event, reason="unauthorized")
    who = cpactor.trusted_actor(req)
    observability.stamp(
        actor=who.username, assurance=who.assurance, delegated_by=who.delegated_by
    )
    username = who.username
    tokens: dict[str, str] = {}
    notified = {"username": username, "requestId": req.get("requestId"), "format": None}
    try:
        _check_contract(req)
        notified["format"] = tokens["format"] = req["format"]
        destination = req["destination"]
        prefix = paths.check_prefix(destination.get("prefix"))
        filename = paths.check_filename(destination.get("filename"))
        tokens["filename"] = filename
        space = authz.authorize_destination(username, destination.get("space"))
        key = paths.destination_key(space["root"], prefix, filename)
        folder = paths.protected_refusal(space["root"], key)
        if folder is not None:
            raise TerminalError(
                reasons.PROTECTED_LOCATION, f"{folder}/ is managed by the portal"
            )
        execution = _describe_execution(req["queryExecutionId"])
        results_key = _owned_results_key(execution, username)
        _check_result_set(execution)
    except TerminalError as err:
        err.tokens = {**tokens, **err.tokens}
        notify.emit_failure(notified, err, "validate")
        raise
    validated = {
        "traceparent": observability.run_traceparent(),
        "requestId": req["requestId"],
        "username": username,
        "format": req["format"],
        "onConflict": req["onConflict"],
        "queryExecutionId": req["queryExecutionId"],
        "resultsKey": results_key,
        "destination": {
            "bucket": space["bucket"],
            "key": key,
            "prefix": prefix,
            "spaceKind": space["kind"],
            "spaceName": space["name"],
        },
    }
    logger.info("validated a %s conversion for %s into %s", req["format"], username, space["kind"])
    observability.info(
        "results conversion validated",
        actor=username,
        format=req["format"],
        on_conflict=req["onConflict"],
        space_kind=space["kind"],
    )
    return validated
