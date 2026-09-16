"""Unit tests for the data-quality start-profile-query Lambda (SPEC-111 FR-003).

AWS stubbed: ``athena.start_query`` and the manifest loader are replaced on the verb
module. The properties under test are the ones that make a retry safe and the results
land in the right space.
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_start_profile_query as v
import pytest
from dqcommon import sql

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


def test_a_column_naming_a_partition_key_is_named_by_no_query_whatever_its_case(monkeypatch, started):
    """The temp table leaves out a data column naming a partition key in any case — here `Year`
    against the key `year`, and `month` against the folder-derived `Month`. A query naming one
    anyway does not fail: Athena lowercases the identifier and binds it to the partition column,
    so the profile would report the folder's value under the user's column name. So the profile
    projects exactly the columns the table's own DDL declares, numbered over that list, and the
    duplicates grouping names each of them once, then the partition keys.

    JSON, because a name-matched format drops such a column wherever it sits: `Year` is second,
    so an alias numbered before the drop leaves a gap that a trailing drop could never show.
    """
    manifest = {
        "partitionKeys": [{"name": "year", "values": ["2025"]}, {"name": "Month", "values": ["01"]}],
        "files": [{"key": "alice/sales/year=2025/Month=01/jan.json", "size": 1, "columns": [
            {"name": "id", "type": "string"},
            {"name": "Year", "type": "string"},
            {"name": "amount", "type": "string"},
            {"name": "month", "type": "string"},
        ]}],
    }
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: manifest)
    ddl = sql.build_temp_table_ddl(
        "alice", f"dq_tmp_{HEX32}", sql.union_columns(manifest["files"]),
        manifest["partitionKeys"], "json", f"s3://{BUCKET}/alice/sales/",
    )
    declared = re.findall(r"`([^`]+)` string", re.search(r"\(([^()]*)\) PARTITIONED BY", ddl).group(1))

    v.handler(_event(format="json", tempRawTable=None), None)

    queries = {kw["client_request_token"]: kw["query"] for kw in started}
    projected = re.findall(r'"([^"]+)"(?:\), \'\'\))? AS c(\d+)\b', queries[f"{HEX32}-profile"])
    assert declared == ["id", "amount"], "the table this manifest builds"
    assert projected == [(name, str(index)) for index, name in enumerate(declared)]
    assert 'GROUP BY "id", "amount", "year", "Month" HAVING' in queries[f"{HEX32}-dupes"]


# ── Idempotent submission (FR-003) ───────────────────────────────────────────


def test_every_submission_carries_a_client_request_token(started):
    """Without one, an SFN Retry after a post-submission transient error starts a SECOND
    query — the pipeline then polls one execution while another runs unwatched."""
    v.handler(_event(), None)
    assert all(kw.get("client_request_token") for kw in started)


# ── A single-file target narrows every query ─────────────────────────────────

#: The predicate literal all three queries must carry, written out rather than derived from the
#: event so the expectation and the input do not agree by construction. It is the full ``s3://``
#: form Athena's path pseudo-column returns — a bare key would match nothing and the report would
#: come back empty.
_SELECTED = "'s3://dq-user-bkt/alice/sales/jan.csv'"


def test_every_query_is_narrowed_to_the_selected_file(started):
    """A single-file check reports on the file only because this verb attaches the predicate.

    create-temp-tables promotes a single-file target's LOCATION to the parent folder, because an
    external table's location is a prefix and pointing it at an object key gives a table over
    nothing — and a location is read recursively, so that table also covers every sibling. This
    is the call site that has to pass the filter on: ``dqcommon.sql`` renders the clause, but a
    verb that stopped passing it would run all three queries over the folder and describe it as
    the file, with nothing red. The manifest is the folder case's, unchanged — only the requested
    location differs, which is exactly what ``sql.single_file_path`` keys on.
    """
    event = _event(location="alice/sales/jan.csv")

    v.handler(event, None)

    narrowed = {kw["client_request_token"]: kw["query"] for kw in started}
    assert sorted(narrowed) == sorted(
        [f"{HEX32}-profile", f"{HEX32}-ragged", f"{HEX32}-dupes"]
    ), "the three queries this assertion ranges over"
    for token, query in narrowed.items():
        assert f'WHERE "$path" = {_SELECTED}' in query, token


def test_a_folder_target_attaches_no_predicate(started):
    """The other direction, and the one nothing else would catch: a folder narrowed to one file.

    A folder check that gained a predicate would report on whichever file it picked and call the
    answer the folder's. It is the worse half because create-temp-tables promotes a target it
    believes is a single file a level FURTHER up, so a ``single_file_path`` that answered "one
    file" for every target would build the table over the user's whole space and profile that. The
    folder branch also has to render byte-identically to the pre-filter form, which is what lets
    ``_where`` return nothing at all rather than a clause that is always true.

    The needle is the comparison, not the column: the ragged query names ``"$path"`` in its
    per-file CASE whatever the target is, so an absence assertion over the column alone could
    never hold.
    """
    event = _event()

    v.handler(event, None)

    rendered = {kw["client_request_token"]: kw["query"] for kw in started}
    assert sorted(rendered) == sorted(
        [f"{HEX32}-profile", f"{HEX32}-ragged", f"{HEX32}-dupes"]
    ), "the three queries this assertion ranges over"
    for token, query in rendered.items():
        assert '"$path" = ' not in query, token
