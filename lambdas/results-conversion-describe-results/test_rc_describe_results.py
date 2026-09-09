"""describe-results: one metadata call, one size read, and the refusals between them."""

import json
import os
import sys

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results-conversion-common"))
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import rc_describe_results as d
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from rccommon.config import MAX_RESULT_COLUMNS, max_result_bytes

EXECUTION_ID = "11111111-2222-4333-8444-555555555555"


class FakeAthena:
    def __init__(self, columns):
        self.columns = columns
        self.calls = []

    def get_query_results(self, **kwargs):
        self.calls.append(kwargs)
        info = []
        for column in self.columns:
            name, type_name, *parameters = column
            # Athena reports a decimal's parameters HERE and not in `Type`, so a fixture that
            # only ever supplies two fields cannot exercise the one column that needs them.
            keyed = dict(zip(("Precision", "Scale"), parameters, strict=False))
            info.append({"Name": name, "Type": type_name, **keyed})
        return {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": info},
                "Rows": [{"Data": [{"VarCharValue": c[0]} for c in self.columns]}],
            }
        }


class FakeS3:
    def __init__(self, size=1234, error=None):
        self.size, self.error, self.calls = size, error, []

    def head_object(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {"ContentLength": self.size}


def _validated():
    return {
        "requestId": "req-1",
        "username": "alice",
        "format": "xlsx",
        "onConflict": "refuse",
        "queryExecutionId": EXECUTION_ID,
        "resultsKey": f"alice/athenaresults/{EXECUTION_ID}.csv",
        "destination": {"bucket": "user-bkt", "key": "alice/out/q1.xlsx", "prefix": "out/", "spaceKind": "personal", "spaceName": "alice"},
    }


def _setup(columns=(("id", "bigint"), ("name", "varchar")), size=1234, s3_error=None):
    sent = []
    d.notify.emit_notification = lambda user, message, **kw: sent.append((user, message, kw))
    athena, s3 = FakeAthena(list(columns)), FakeS3(size, s3_error)
    clients._athena, clients._s3 = athena, s3
    return sent, athena, s3


def test_the_columns_and_the_size_are_read_once_each_and_threaded_with_the_request():
    sent, athena, s3 = _setup()
    described = d.handler(_validated(), None)
    # This verb MINTS the key rather than carrying it: `_CARRIED` is a fixed tuple read through
    # `events.require`, so adding it there would make a logging value a required field and a
    # missing one a TerminalError.
    assert described.pop("traceparent").startswith("00-")
    assert described == {
        **_validated(),
        "columns": [{"name": "id", "type": "bigint"}, {"name": "name", "type": "varchar"}],
        "resultsBytes": 1234,
    }
    assert athena.calls == [{"QueryExecutionId": EXECUTION_ID, "MaxResults": 1}]
    assert s3.calls == [{"Bucket": "user-bkt", "Key": f"alice/athenaresults/{EXECUTION_ID}.csv"}]
    assert sent == []


def test_a_decimals_precision_and_scale_are_carried_and_nothing_else_gains_them():
    """Athena reports `decimal` bare and puts the parameters in sibling fields, so a describe
    that drops them leaves the converter unable to type the column at all. Every other type
    carries its parameters in the string, and must not gain the keys."""
    _setup(columns=(("amount", "decimal", 10, 2), ("name", "varchar")))
    described = d.handler(_validated(), None)["columns"]
    assert described == [
        {"name": "amount", "type": "decimal", "precision": 10, "scale": 2},
        {"name": "name", "type": "varchar"},
    ]


def test_a_result_set_wider_than_the_state_can_carry_is_refused_before_it_is_put_on_one():
    """The cap is the TRANSPORT's, not a file format's, and it fires here or nowhere.

    The described columns ride on the Step Functions state, capped at 256 KB. Measured across
    realistic column entries, that boundary falls between about 2,500 columns (a long name plus
    a decimal's precision and scale) and about 6,400 (a short name and a bare type) — so
    Excel's own 16,384-column ceiling is two to three times past what the state can carry and
    could never have been reached. Above the cap the payload fails as an uncatchable error
    before any named refusal runs, which is why this refusal is the one that exists and why it
    applies to every format rather than to Excel alone.
    """
    cap = MAX_RESULT_COLUMNS
    sent, _, _ = _setup(columns=tuple((f"c{i}", "varchar") for i in range(cap + 1)))
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)

    assert err.value.reason == "too_many_columns"
    assert str(err.value.tokens["count"]) == str(cap + 1)
    assert len(sent) == 1 and sent[0][0] == "alice"
    assert f"{cap + 1} columns" in sent[0][1], "the sentence names the count the user has"
    assert '"q1.xlsx"' in sent[0][1], "and the file they asked for"
    assert "{" not in sent[0][1]


def test_the_width_cap_is_the_threshold_it_says_it_is():
    """The positive control for the refusal above: exactly at the cap is accepted, so the test
    is about the boundary rather than about any large number at all."""
    _setup(columns=tuple((f"c{i}", "varchar") for i in range(MAX_RESULT_COLUMNS)))
    described = d.handler(_validated(), None)
    assert len(described["columns"]) == MAX_RESULT_COLUMNS


def test_the_width_refusal_comes_before_the_name_checks():
    """A result set both too wide AND carrying a duplicate name refuses for the width, because
    the width is what stops the state being built at all — a duplicate is a fact about data the
    state could have carried."""
    columns = [(f"c{i}", "varchar") for i in range(MAX_RESULT_COLUMNS + 1)]
    columns[0] = ("Total", "varchar")
    columns[1] = ("total", "varchar")
    _setup(columns=tuple(columns))
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)
    assert err.value.reason == "too_many_columns"


def test_an_empty_result_set_is_a_valid_file_with_a_header():
    _setup(size=0)
    assert d.handler(_validated(), None)["resultsBytes"] == 0


def test_a_result_over_the_cap_is_refused_naming_the_cap_and_the_file():
    """The cap applied is the one for the format the request asked for.

    `_validated()` asks for `xlsx`, the memory-bound format and by far the smallest cap — so a
    size the spreadsheet path refuses sits comfortably inside JSON's, and the second half here
    proves the two really are different numbers rather than one constant reached by two names.
    """
    excel_cap = max_result_bytes("xlsx")
    sent, _, _ = _setup(size=excel_cap + 1)
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)
    assert err.value.reason == "results_too_large"
    assert len(sent) == 1 and sent[0][0] == "alice"
    from rccommon.messages import _human_bytes

    assert _human_bytes(excel_cap) in sent[0][1] and "as Excel" in sent[0][1]
    _setup(size=excel_cap)
    assert d.handler(_validated(), None)["resultsBytes"] == excel_cap

    assert max_result_bytes("json") > excel_cap
    _setup(size=excel_cap + 1)
    assert d.handler({**_validated(), "format": "json"}, None)["resultsBytes"] == excel_cap + 1


def test_a_case_folded_duplicate_names_the_column_to_the_user_and_nowhere_else(captured_events):
    sent, _, _ = _setup(columns=(("Total", "bigint"), ("total", "double")))
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)
    assert err.value.reason == "duplicate_column"
    assert '"Total"' in sent[0][1]
    narrated = json.dumps(captured_events.events)
    assert "Total" not in narrated and "total" not in narrated.replace("results_too_large", "")


def test_an_empty_column_name_is_refused():
    sent, _, _ = _setup(columns=(("", "bigint"),))
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)
    assert err.value.reason == "invalid_column_name"
    assert len(sent) == 1


def test_a_missing_result_object_is_a_fault_not_a_refusal():
    sent, _, _ = _setup(s3_error=ClientError({"Error": {"Code": "404", "Message": "x"}}, "HeadObject"))
    with pytest.raises(ClientError):
        d.handler(_validated(), None)
    assert [message.startswith("Couldn't save the query results as Excel: something went wrong") for _, message, _ in sent] == [True]


def test_a_throttled_read_is_transient():
    _setup(s3_error=ClientError({"Error": {"Code": "SlowDown", "Message": "x"}}, "HeadObject"))
    with pytest.raises(TransientError):
        d.handler(_validated(), None)


def test_no_column_name_reaches_a_span_on_the_happy_path(captured_events):
    _setup(columns=(("secret_column_name", "varchar"),))
    d.handler(_validated(), None)
    assert "secret_column_name" not in json.dumps(captured_events.events)
    assert captured_events.messages("result set described")
