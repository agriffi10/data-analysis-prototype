"""The results-conversion front door: what it accepts, what it refuses, and by which code.

Pure logic, AWS stubbed. The cases that matter are the ones an attacker or a careless caller
would reach for: a space that is not theirs, a key that escapes the space, a folder the portal
owns, and an execution id that names somebody else's results.
"""

import json
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results-conversion-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_validate_authorize as v
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError

EXECUTION_ID = "11111111-2222-4333-8444-555555555555"


class FakeAthena:
    def __init__(self, execution=None, error=None):
        self.execution = execution
        self.error = error
        self.calls = []

    def get_query_execution(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"QueryExecution": self.execution}


def _execution(location=None, state="SUCCEEDED", statement="DML"):
    return {
        "Status": {"State": state},
        "StatementType": statement,
        "ResultConfiguration": {
            "OutputLocation": location
            or f"s3://{config.USER_SPACE_BUCKET}/alice/system_settings/athenaresults/{EXECUTION_ID}.csv"
        },
    }


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "x"}}, "GetQueryExecution")


def _setup(spaces=None, execution=..., error=None):
    """Stubs the registry, Athena and the notification sink; returns the sink and the client."""
    sent = []
    v.authz.reg.load = lambda name: (spaces or {}).get(name)
    v.notify.emit_notification = lambda user, message, **kw: sent.append((user, message, kw))
    athena = FakeAthena(_execution() if execution is ... else execution, error)
    clients._athena = athena
    return sent, athena


def _body(destination=..., identity=True, actor="alice", **overrides):
    body = {
        "requestId": "req-1",
        "queryExecutionId": EXECUTION_ID,
        "format": "parquet",
        "destination": (
            {"space": {"kind": "personal", "name": "alice"}, "prefix": "out/", "filename": "q1.parquet"}
            if destination is ...
            else destination
        ),
        "onConflict": "refuse",
        "submittedAt": "2026-09-05T12:00:00+00:00",
    }
    if identity:
        body["identity"] = {"actor": actor, "delegated_by": None, "assurance": "interactive"}
    body.update(overrides)
    return body


def _event(body=None):
    return [{"body": json.dumps(_body() if body is None else body)}]


def _refused(body, **setup):
    sent, athena = _setup(**setup)
    with pytest.raises(TerminalError) as err:
        v.handler(_event(body), None)
    return err.value, sent, athena


def test_a_personal_request_is_validated_into_exactly_the_contracted_keys():
    sent, athena = _setup()
    validated = v.handler(_event(), None)
    assert sent == []
    # Minted per invocation; popped so the rest stays an exact equality.
    assert validated.pop("traceparent").startswith("00-")
    assert validated == {
        "requestId": "req-1",
        "username": "alice",
        "format": "parquet",
        "onConflict": "refuse",
        "queryExecutionId": EXECUTION_ID,
        "resultsKey": f"alice/system_settings/athenaresults/{EXECUTION_ID}.csv",
        "columnIndexes": None,
        "destination": {
            "bucket": config.USER_SPACE_BUCKET,
            "key": "alice/out/q1.parquet",
            "prefix": "out/",
            "spaceKind": "personal",
            "spaceName": "alice",
        },
    }
    assert len(athena.calls) == 1 and athena.calls[0] == {"QueryExecutionId": EXECUTION_ID}


def test_a_message_with_no_identity_block_is_refused_before_any_call_is_made():
    """no_identity_block: the fail-closed case every queue consumer proves for itself."""
    err, sent, athena = _refused(_body(identity=False, actor="alice"))
    assert err.reason == "unauthorized"
    assert athena.calls == [] and sent == []


def test_a_flat_actor_beside_no_block_is_never_read():
    """A flat field is refused as an absent block, never resolved as a username."""
    err, sent, athena = _refused({**_body(identity=False), "actor": "alice"})
    assert err.reason == "unauthorized"
    assert athena.calls == [] and sent == []


def test_an_unknown_or_absent_assurance_fails_closed():
    body = _body()
    body["identity"]["assurance"] = "anonymous"
    assert _refused(body)[0].reason == "unsupported_assurance"
    del body["identity"]["assurance"]
    assert _refused(body)[0].reason in {"unsupported_assurance", "unauthorized"}


def test_another_users_personal_space_and_a_missing_shared_space_read_the_same_sentence():
    """Neither refusal may be an existence oracle."""
    other = _refused(_body(destination={"space": {"kind": "personal", "name": "bob"}, "prefix": "", "filename": "a.parquet"}))[0]
    absent = _refused(_body(destination={"space": {"kind": "shared", "name": "ghost"}, "prefix": "", "filename": "a.parquet"}))[0]
    excluded = _refused(
        _body(destination={"space": {"kind": "shared", "name": "team"}, "prefix": "", "filename": "a.parquet"}),
        spaces={"team": {"status": "active", "members": ["carol"]}},
    )[0]
    assert other.reason == absent.reason == excluded.reason == "forbidden"
    assert other.detail == absent.detail == excluded.detail


@pytest.mark.parametrize("kind", ["admin", "", None, 1, ["shared"]], ids=["unknown", "empty", "null", "int", "list"])
def test_the_space_kind_vocabulary_is_closed(kind):
    """An unknown kind must not fall through to a branch. Without this the attacker's own value
    reaches `destination.spaceKind` on the state — a non-string one included."""
    err, sent, athena = _refused(
        _body(destination={"space": {"kind": kind, "name": "alice"}, "prefix": "", "filename": "a.parquet"}),
        spaces={"alice": {"status": "active", "members": ["alice"]}},
    )
    assert err.reason == "forbidden"
    assert athena.calls == []
    assert [user for user, _, _ in sent] == ["alice"]


def test_a_shared_space_the_actor_is_an_active_member_of_resolves_to_the_shared_bucket():
    _setup(spaces={"team": {"status": "active", "members": ["alice"]}})
    validated = v.handler(_event(_body(destination={"space": {"kind": "shared", "name": "team"}, "prefix": "", "filename": "a.parquet"})), None)
    assert validated["destination"] == {
        "bucket": config.SHARED_SPACE_BUCKET, "key": "team/a.parquet", "prefix": "", "spaceKind": "shared", "spaceName": "team",
    }


def test_a_deleting_space_and_a_registry_denial_are_told_apart():
    deleting = _refused(
        _body(destination={"space": {"kind": "shared", "name": "team"}, "prefix": "", "filename": "a.parquet"}),
        spaces={"team": {"status": "deleting", "members": ["alice"]}},
    )[0]
    assert deleting.reason == "forbidden"

    def denied(name):
        raise ClientError({"Error": {"Code": "AccessDenied", "Message": "x"}}, "GetObject")

    _setup()
    v.authz.reg.load = denied
    with pytest.raises(ClientError):
        v.handler(_event(_body(destination={"space": {"kind": "shared", "name": "team"}, "prefix": "", "filename": "a.parquet"})), None)


@pytest.mark.parametrize(
    "destination",
    [
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "../bob/", "filename": "a.parquet"},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "out", "filename": "a.parquet"},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": "a/b.parquet"},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": ".."},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": "a\x01.parquet"},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": ""},
        # The PREFIX half of the control-character rule. `check_filename` had a row here and
        # `check_prefix` did not, so the prefix's own refusal was a guard nothing held — and a
        # newline in a folder reaches an operator's plain-text log through the key it becomes.
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "out\n/", "filename": "a.parquet"},
        {"space": {"kind": "personal", "name": "alice"}, "prefix": "out\x00/", "filename": "a.parquet"},
    ],
    ids=[
        "dot-segment",
        "prefix-without-slash",
        "slash-in-name",
        "dot-dot-name",
        "control-char",
        "empty-name",
        "newline-in-prefix",
        "nul-in-prefix",
    ],
)
def test_a_malformed_destination_is_invalid_request(destination):
    err, sent, athena = _refused(_body(destination=destination))
    assert err.reason == "invalid_request"
    assert athena.calls == [], "a malformed request must not reach Athena"
    assert [user for user, _, _ in sent] == ["alice"]


def test_each_cap_refuses_exactly_one_byte_over_and_accepts_the_cap_itself():
    _setup()
    at_cap = _body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": "x" * 255})
    assert v.handler(_event(at_cap), None)["destination"]["key"] == "alice/" + "x" * 255
    over = _body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": "x" * 256})
    assert _refused(over)[0].reason == "invalid_request"
    prefix_at_cap = _body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "p" * 1023 + "/", "filename": "a"})
    _setup()
    assert v.handler(_event(prefix_at_cap), None)["destination"]["prefix"].endswith("/")
    prefix_over = _body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "p" * 1024 + "/", "filename": "a"})
    assert _refused(prefix_over)[0].reason == "invalid_request"


@pytest.mark.parametrize(
    "prefix",
    [
        "system_settings/athenaresults/",
        "system_settings/archive/",
        "shared_tables/",
        "user_settings/",
        "_data-quality-reports/",
        "backups/system_settings/archive/",
    ],
)
def test_an_app_managed_folder_is_refused_at_any_depth_with_the_file_named(prefix):
    """The prefixes are the folders' SEGMENTS since the move, not their names.

    Two of the six moved under ``system_settings/`` and this list mirrors the execution role's
    DENY, which moved with them; the other four did not move and stay at depth one. The last row
    is the any-depth case, and it carries the pair for the same reason.
    """
    err, sent, athena = _refused(_body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": prefix, "filename": "q1.parquet"}))
    assert err.reason == "protected_location"
    assert athena.calls == []
    assert '"q1.parquet"' in sent[0][1] and "as Parquet" in sent[0][1]


@pytest.mark.parametrize("prefix", ["athenaresults/", "archive/", "backups/archive/"])
def test_the_name_a_moving_folder_LEFT_is_an_ordinary_destination(prefix):
    """The half the narrowing added, and the half nothing else in this file would catch.

    This verb refused these three until the Deny it mirrors moved. Over-refusal fails safe, so a
    suite that only asserts refusals stays green through it — and here it was user-reachable: the
    same change released these folders from the browser's picker, so *Save results* offered a
    destination this verb rejected.
    """
    _setup()
    validated = v.handler(
        _event(_body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": prefix, "filename": "q1.parquet"})),
        None,
    )
    assert validated["destination"]["key"] == f"alice/{prefix}q1.parquet"


def test_a_file_merely_named_like_a_protected_folder_is_a_file():
    _setup()
    validated = v.handler(_event(_body(destination={"space": {"kind": "personal", "name": "alice"}, "prefix": "", "filename": "archive"})), None)
    assert validated["destination"]["key"] == "alice/archive"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("format", "csv", "invalid_request"),
        ("format", "tsv", "invalid_request"),
        ("onConflict", "ask", "invalid_request"),
        ("queryExecutionId", "not-an-id", "invalid_request"),
        ("submittedAt", "yesterday", "invalid_request"),
        ("submittedAt", "2026-09-05T12:00:00", "invalid_request"),
        ("extra", 1, "malformed_event"),
    ],
)
def test_the_vocabulary_is_closed(field, value, reason):
    assert _refused(_body(**{field: value}))[0].reason == reason


def test_an_output_location_carrying_a_dot_segment_is_refused():
    """A startswith on the prefix passes a location that then escapes it. Nothing writes one
    today; this is the only place an S3-supplied path becomes a key the converter will read."""
    escaping = _execution(
        location=f"s3://{config.USER_SPACE_BUCKET}/alice/system_settings/athenaresults/../../bob/secret.csv"
    )
    err, _sent, _athena = _refused(_body(), execution=escaping)
    assert err.reason == "execution_not_found"


def test_an_id_athena_does_not_know_and_another_users_execution_share_one_code():
    unknown = _refused(_body(), execution=None, error=_client_error("InvalidRequestException"))[0]
    elsewhere = _refused(_body(), execution=_execution(location=f"s3://{config.USER_SPACE_BUCKET}/bob/system_settings/athenaresults/{EXECUTION_ID}.csv"))[0]
    assert unknown.reason == elsewhere.reason == "execution_not_found"
    prefix_cousin = _refused(_body(), execution=_execution(location=f"s3://{config.USER_SPACE_BUCKET}/alice2/system_settings/athenaresults/x.csv"))[0]
    assert prefix_cousin.reason == "execution_not_found"


def test_a_throttled_athena_read_is_transient_not_terminal():
    _setup(execution=None, error=_client_error("ThrottlingException"))
    with pytest.raises(TransientError):
        v.handler(_event(), None)


@pytest.mark.parametrize(
    ("state", "statement", "reason"),
    [
        ("QUEUED", "DML", "execution_not_finished"),
        ("RUNNING", "DML", "execution_not_finished"),
        ("FAILED", "DML", "execution_failed"),
        ("CANCELLED", "DML", "execution_failed"),
        ("SUCCEEDED", "DDL", "no_result_set"),
        ("SUCCEEDED", "UTILITY", "no_result_set"),
    ],
)
def test_only_a_succeeded_dml_execution_proceeds(state, statement, reason):
    err, sent, _ = _refused(_body(), execution=_execution(state=state, statement=statement))
    assert err.reason == reason
    assert len(sent) == 1 and sent[0][0] == "alice"


def test_a_refusal_after_identity_notifies_the_actor_exactly_once_with_the_request_id():
    err, sent, _ = _refused(_body(), execution=_execution(state="RUNNING"))
    assert err.reason == "execution_not_finished"
    assert len(sent) == 1
    user, message, kwargs = sent[0]
    assert user == "alice" and message.startswith("Couldn't save the query results as Parquet: ")
    assert kwargs["payload"] == {"requestId": "req-1", "format": "parquet"}


def test_a_CONTRACT_refusal_carries_the_request_id_but_not_the_format_it_refused():
    """The id was named only after the contract passed, so a contract refusal carried no payload
    at all. The format is the half that must wait: it is rendered into the sentence, and here it
    is the very field that failed."""
    err, sent, _ = _refused(_body(format="csv"))

    assert err.reason == "invalid_request"
    assert [kwargs["payload"] for _, _, kwargs in sent] == [{"requestId": "req-1"}]


@pytest.mark.parametrize("request_id", [None, 7], ids=["missing", "not-a-string"])
def test_a_request_with_no_usable_id_reaches_the_contracts_own_refusal_and_names_no_id(request_id):
    """The id is read before the contract has checked it, so reading it must not be what fails: a
    subscript would raise outside the refusal's own handler and the actor would be told nothing
    specific. What the payload cannot use it drops, rather than forwarding it."""
    body = _body()
    if request_id is None:
        del body["requestId"]
    else:
        body["requestId"] = request_id

    err, sent, _ = _refused(body)

    assert err.reason == "malformed_event"
    assert [kwargs.get("payload") for _, _, kwargs in sent] == [None]


def test_the_identity_is_stamped_on_the_span(captured_events):
    _setup()
    v.handler(_event(), None)
    stamped = [e for e in captured_events.events if (e.get("fields") or {}).get("actor") == "alice"]
    assert stamped, "the verified actor never reached a span"


@pytest.mark.parametrize(
    ("field", "detail"),
    [
        ("format", "unknown format ['parquet']"),
        ("onConflict", "unknown conflict answer ['refuse']"),
    ],
    ids=["format", "on-conflict"],
)
def test_an_unhashable_vocabulary_field_reaches_this_plane_s_own_refusal(field, detail):
    """A list in either field HASHES on the way into its membership test, so before the type check
    each raised TypeError there — reported as an unexpected error, with this plane's own reason
    code never rendered onto the execution."""
    err, _sent, _athena = _refused(_body(**{field: [_body()[field]]}))

    assert err.reason == "invalid_request"
    assert err.detail == detail


# ── The chosen columns, emitted before anything can send them (SPEC-239) ────


def test_the_validated_state_always_carries_the_chosen_columns_even_as_null():
    """A Pass state's JSONPath hard-fails on an ABSENT key, so the key can never be conditional:
    the machine is taught to read it in a later release, and by then every live image must
    already be returning it. Null is what "the request named no columns" looks like on the
    state, and in this release it is the only value the key can take."""
    _setup()
    validated = v.handler(_event(), None)

    assert "columnIndexes" in validated
    assert validated["columnIndexes"] is None


def test_the_field_itself_is_not_admitted_yet_and_that_is_what_makes_the_order_safe():
    """The plane's allowed-field set is held equal to the API's declared fields by a fleet guard,
    and the API does not declare this one yet. So the verb returns the key while no caller can
    send it — the only safe order, because `Deploy Infrastructure` and `Deploy Lambdas` run on
    one push with no ordering, and a Pass state may not read a key a live image does not return.
    The release that adds the field to the contract adds it here too."""
    error, _, athena = _refused(_body(columnIndexes=[0, 2]))

    assert error.reason == "malformed_event"
    assert "columnIndexes" in error.detail
    assert athena.calls == [], "an unknown field is refused before the execution is described"
