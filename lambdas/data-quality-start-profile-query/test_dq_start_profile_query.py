"""Unit tests for the data-quality start-profile-query Lambda (SPEC-111 FR-003).

AWS stubbed: ``athena.start_query`` and the manifest loader are replaced on the verb
module. The properties under test are the ones that make a retry safe and the results
land in the right space.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_start_profile_query as v
import pytest

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


def test_the_duplicates_grouping_names_a_partition_key_once_whatever_its_case(monkeypatch, started):
    """The temp table leaves out a data column naming a partition key in any case — here `Year`
    against the key `year`, and `month` against the folder-derived `Month` — so the grouping
    names each of the table's columns once rather than repeating one under two spellings."""
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: {
        "partitionKeys": [{"name": "year", "values": ["2025"]}, {"name": "Month", "values": ["01"]}],
        "files": [{"key": "alice/sales/year=2025/Month=01/jan.csv", "size": 1, "columns": [
            {"name": "id", "type": "string"},
            {"name": "month", "type": "string"},
            {"name": "Year", "type": "string"},
        ]}],
    })

    v.handler(_event(), None)

    assert 'GROUP BY "id", "year", "Month" HAVING' in started[-1]["query"]


# ── Idempotent submission (FR-003) ───────────────────────────────────────────


def test_every_submission_carries_a_client_request_token(started):
    """Without one, an SFN Retry after a post-submission transient error starts a SECOND
    query — the pipeline then polls one execution while another runs unwatched."""
    v.handler(_event(), None)
    assert all(kw.get("client_request_token") for kw in started)


# ── SPEC-151 FR-001: a single-file target narrows every query ────────────────
#
# create-temp-tables promotes the table LOCATION to the parent FOLDER for a single-file
# target, because Athena needs a prefix. A LOCATION is read RECURSIVELY, so that table
# covers every sibling — and the "$path" predicate this verb attaches is the only thing
# that puts the report back on the file the user actually selected.

_ONE_FILE_MANIFEST = {
    "partitionKeys": [],
    "files": [
        {
            "key": "alice/sales/jan.csv",
            "size": 1,
            "columns": [
                {"name": "order_id", "type": "string"},
                {"name": "amount", "type": "string"},
            ],
        }
    ],
}

_SELECTED = "'s3://dq-user-bkt/alice/sales/jan.csv'"


@pytest.fixture
def started_single_file(monkeypatch):
    calls = []

    def _start(**kw):
        calls.append(kw)
        return f"qid-{len(calls)}"

    monkeypatch.setattr(v.athena, "start_query", _start)
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: _ONE_FILE_MANIFEST)
    return calls
