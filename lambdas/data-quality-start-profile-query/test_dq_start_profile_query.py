"""Unit tests for the data-quality start-profile-query Lambda (SPEC-111 FR-003).

AWS stubbed: ``athena.start_query`` and the manifest loader are replaced on the verb
module. The properties under test are the ones that make a retry safe and the results
land in the right space.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import pytest  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import messages  # noqa: E402

import dq_start_profile_query as v  # noqa: E402

BUCKET = "dq-user-bkt"
REQUEST_ID = "7f3ac19d-2b4e-4c8a-9f01-6d5e3a7b8c02"
HEX32 = "7f3ac19d2b4e4c8a9f016d5e3a7b8c02"


def _event(**overrides):
    event = {
        "requestId": REQUEST_ID,
        "actor": "alice",
        "space": {"kind": "personal", "bucket": BUCKET, "prefix": "alice/"},
        "location": "alice/sales",
        "reportPrefix": f"alice/_data-quality-reports/{REQUEST_ID}/",
        "manifestKey": f"alice/_data-quality-reports/{REQUEST_ID}/manifest.json",
        "format": "csv",
        "database": "alice",
        "tempTable": f"dq_tmp_{HEX32}",
        "tempRawTable": f"dq_tmp_raw_{HEX32}",
    }
    event.update(overrides)
    return event


_MANIFEST = {
    "partitionKeys": [],
    "files": [
        {
            "key": "alice/sales/jan.csv",
            "size": 1,
            "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
        }
    ],
}


@pytest.fixture
def started(monkeypatch):
    """Capture every start_query call; return the list of kwargs."""
    calls = []

    def _start(**kw):
        calls.append(kw)
        return f"qid-{len(calls)}"

    monkeypatch.setattr(v.athena, "start_query", _start)
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: _MANIFEST)
    return calls


def _by_token(calls):
    return {kw["client_request_token"]: kw for kw in calls}


# ── The three queries ────────────────────────────────────────────────────────


def test_csv_starts_all_three_queries(started):
    out = v.handler(_event(), None)

    assert len(started) == 3
    assert out["profile"]["queryExecutionId"] == "qid-1"
    assert out["ragged"]["queryExecutionId"] == "qid-2"
    assert out["duplicates"]["queryExecutionId"] == "qid-3"


def test_json_starts_two_queries_and_marks_ragged_not_applicable(started):
    out = v.handler(_event(format="json", tempRawTable=None), None)

    assert len(started) == 2
    # null, NOT a not_computed block: "never applicable" and "we tried and failed" are
    # different findings and the report must not blur them.
    assert out["ragged"] is None
    assert out["profile"]["status"] == "QUEUED"
    assert out["duplicates"]["status"] == "QUEUED"


def test_parquet_starts_two_queries(started):
    out = v.handler(_event(format="parquet", tempRawTable=None), None)
    assert len(started) == 2
    assert out["ragged"] is None


def test_the_profile_query_is_started_first(started):
    """If the backbone cannot even be submitted, starting the cheap ones first would
    leave two orphan executions running for a request nobody will read."""
    v.handler(_event(), None)
    assert started[0]["client_request_token"].endswith("-profile")


def test_the_ragged_query_runs_against_the_raw_table(started):
    v.handler(_event(), None)
    ragged = _by_token(started)[f"{HEX32}-ragged"]
    assert f"dq_tmp_raw_{HEX32}" in ragged["query"]
    assert "cardinality(split(" in ragged["query"]


def test_the_ragged_query_compares_against_the_column_count(started):
    v.handler(_event(), None)
    ragged = _by_token(started)[f"{HEX32}-ragged"]
    # The manifest has two columns, and partition keys are NOT in the physical header.
    assert "<> 2" in ragged["query"]


def test_the_duplicates_query_runs_against_the_typed_table(started):
    v.handler(_event(), None)
    dupes = _by_token(started)[f"{HEX32}-dupes"]
    assert f"dq_tmp_{HEX32}" in dupes["query"]
    assert "duplicate_rows" in dupes["query"]


# ── Idempotent submission (FR-003) ───────────────────────────────────────────


def test_every_submission_carries_a_client_request_token(started):
    """Without one, an SFN Retry after a post-submission transient error starts a SECOND
    query — the pipeline then polls one execution while another runs unwatched."""
    v.handler(_event(), None)
    assert all(kw.get("client_request_token") for kw in started)


def test_the_three_tokens_are_distinct(started):
    v.handler(_event(), None)
    tokens = [kw["client_request_token"] for kw in started]
    assert len(set(tokens)) == 3


def test_the_tokens_are_pure_functions_of_the_request_id(started):
    """A retry must re-attach to the ORIGINAL executions, which only works if the token
    is reproducible from the request alone."""
    v.handler(_event(), None)
    first = [kw["client_request_token"] for kw in started]

    started.clear()
    v.handler(_event(), None)
    assert [kw["client_request_token"] for kw in started] == first
    assert first == [f"{HEX32}-profile", f"{HEX32}-ragged", f"{HEX32}-dupes"]


def test_the_tokens_carry_no_hyphens_from_the_uuid(started):
    v.handler(_event(), None)
    for kw in started:
        stem = kw["client_request_token"].rsplit("-", 1)[0]
        assert "-" not in stem


def test_the_tokens_are_long_enough_for_athena(started):
    """Athena requires 32-128 characters."""
    v.handler(_event(), None)
    for kw in started:
        assert 32 <= len(kw["client_request_token"]) <= 128


# ── Result routing (FR-003) ──────────────────────────────────────────────────


def test_each_query_gets_its_own_output_location(started):
    """Per query, because a workgroup has exactly ONE static result location — so
    per-space routing is impossible any other way."""
    v.handler(_event(), None)
    locations = [kw["output_location"] for kw in started]
    assert len(set(locations)) == 3
    assert all(loc.startswith(f"s3://{BUCKET}/alice/athenaresults/") for loc in locations)


def test_a_personal_check_writes_results_under_the_users_own_prefix(started):
    out = v.handler(_event(), None)
    assert out["resultsPrefix"].startswith(f"s3://{BUCKET}/alice/athenaresults/")


def test_a_shared_check_writes_results_under_the_spaces_prefix(started):
    """A NEW prefix convention, introduced deliberately: until now athenaresults/ existed
    only as {username}/athenaresults/ in the user-space bucket."""
    out = v.handler(
        _event(space={"kind": "shared", "bucket": "dq-shared-bkt", "prefix": "team_data/"}), None
    )
    assert out["resultsPrefix"].startswith("s3://dq-shared-bkt/team_data/athenaresults/")


def test_result_locations_are_recorded_for_the_report(started):
    """SPEC-112 reads these files; it has to be told where they are."""
    out = v.handler(_event(), None)
    assert out["profile"]["resultLocation"].endswith("/profile/")
    assert out["ragged"]["resultLocation"].endswith("/ragged/")
    assert out["duplicates"]["resultLocation"].endswith("/duplicates/")


def test_the_queries_run_in_the_dedicated_workgroup(started):
    """Not the shared portal workgroup, whose 10 GiB scan cutoff would fail every real
    check."""
    v.handler(_event(), None)
    assert all(kw["workgroup"] for kw in started)
    assert len({kw["workgroup"] for kw in started}) == 1


# ── Shape validation ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing", ["requestId", "manifestKey", "database", "tempTable", "format"])
def test_a_missing_required_field_is_a_typed_terminal(started, missing):
    event = _event()
    del event[missing]
    with pytest.raises(TerminalError) as exc:
        v.handler(event, None)
    assert exc.value.reason == messages.INVALID_REQUEST


def test_the_request_object_is_threaded_not_replaced(started):
    out = v.handler(_event(), None)
    assert out["requestId"] == REQUEST_ID
    assert out["actor"] == "alice"
    assert out["tempTable"] == f"dq_tmp_{HEX32}"
