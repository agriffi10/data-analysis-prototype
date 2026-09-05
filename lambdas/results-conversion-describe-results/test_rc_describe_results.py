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
from rccommon.config import RESULTS_MAX_BYTES

EXECUTION_ID = "11111111-2222-4333-8444-555555555555"


class FakeAthena:
    def __init__(self, columns):
        self.columns = columns
        self.calls = []

    def get_query_results(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ResultSet": {
                "ResultSetMetadata": {"ColumnInfo": [{"Name": n, "Type": t} for n, t in self.columns]},
                "Rows": [{"Data": [{"VarCharValue": n} for n, _ in self.columns]}],
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
    assert described == {
        **_validated(),
        "columns": [{"name": "id", "type": "bigint"}, {"name": "name", "type": "varchar"}],
        "resultsBytes": 1234,
    }
    assert athena.calls == [{"QueryExecutionId": EXECUTION_ID, "MaxResults": 1}]
    assert s3.calls == [{"Bucket": "user-bkt", "Key": f"alice/athenaresults/{EXECUTION_ID}.csv"}]
    assert sent == []


def test_an_empty_result_set_is_a_valid_file_with_a_header():
    _setup(size=0)
    assert d.handler(_validated(), None)["resultsBytes"] == 0


def test_a_result_over_the_cap_is_refused_naming_the_cap_and_the_file():
    sent, _, _ = _setup(size=RESULTS_MAX_BYTES + 1)
    with pytest.raises(TerminalError) as err:
        d.handler(_validated(), None)
    assert err.value.reason == "results_too_large"
    assert len(sent) == 1 and sent[0][0] == "alice"
    assert "1 GB" in sent[0][1] and "as Excel" in sent[0][1]
    _setup(size=RESULTS_MAX_BYTES)
    assert d.handler(_validated(), None)["resultsBytes"] == RESULTS_MAX_BYTES


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
