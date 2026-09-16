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
from cpcommon.errors import TerminalError
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
        "pathFilter": None,
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
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key, location: _MANIFEST)
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


@pytest.mark.parametrize(
    ("fmt", "expected", "grouped"),
    [
        pytest.param(
            "json", ["id", "amount"], '"id", "amount", "year", "Month"', id="json-leaves-them-out"
        ),
        pytest.param(
            "csv",
            ["id", "year_in_file", "amount", "month_in_file"],
            '"id", "year_in_file", "amount", "month_in_file", "year", "Month"',
            id="csv-keeps-them-under-new-names",
        ),
    ],
)
def test_every_query_names_the_columns_the_temp_table_declares_for_a_partitions_namesake(
    monkeypatch, started, fmt, expected, grouped
):
    """A data column naming a partition key in any case — here `Year` against the key `year`, and
    `month` against the folder-derived `Month` — is left out of a JSON temp table and renamed in a
    CSV one. A query naming the file's own spelling anyway does not fail: Athena lowercases the
    identifier and binds it to the partition column, so the profile would report the folder's
    value under the user's column name. So the profile projects exactly the columns the table's
    own DDL declares, numbered over that list, and the duplicates grouping names each of them
    once, then the partition keys — for the format the event carries.

    `Year` is second, so an alias numbered before the mapping leaves a gap or a stale name that a
    trailing column could never show.

    Args:
      monkeypatch: Used to install the manifest.
      started: The queries the fake Athena started.
      fmt: The source format.
      expected: The names the body should declare.
      grouped: The duplicates grouping the statement should carry.

    Returns:
      None.

    Raises:
      None.
    """
    manifest = {
        "partitionKeys": [{"name": "year", "values": ["2025"]}, {"name": "Month", "values": ["01"]}],
        "files": [{"key": f"alice/sales/year=2025/Month=01/jan.{fmt}", "size": 1, "columns": [
            {"name": "id", "type": "string"},
            {"name": "Year", "type": "string"},
            {"name": "amount", "type": "string"},
            {"name": "month", "type": "string"},
        ]}],
    }
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key, location: manifest)
    ddl = sql.build_temp_table_ddl(
        "alice", f"dq_tmp_{HEX32}", sql.union_columns(manifest["files"]),
        manifest["partitionKeys"], fmt, f"s3://{BUCKET}/alice/sales/",
    )
    declared = re.findall(r"`([^`]+)` string", re.search(r"\(([^()]*)\) PARTITIONED BY", ddl).group(1))

    v.handler(_event(format=fmt, tempRawTable=None), None)

    queries = {kw["client_request_token"]: kw["query"] for kw in started}
    projected = re.findall(r'"([^"]+)"(?:\), \'\'\))? AS c(\d+)\b', queries[f"{HEX32}-profile"])
    assert declared == expected, "the table this manifest builds"
    assert projected == [(name, str(index)) for index, name in enumerate(declared)]
    assert f"GROUP BY {grouped} HAVING" in queries[f"{HEX32}-dupes"]


def test_the_ragged_query_judges_each_file_by_its_full_path_against_its_own_header(monkeypatch, started):
    """Each file's CASE branch is keyed the way Athena names the file and holds that file's count.

    The branch key has to be the full ``s3://`` form because that is what the path pseudo-column
    returns. A bare key matches no line at all, so every line falls through to ``ELSE false`` and
    the report says the folder has no ragged rows — a clean bill of health nobody earned, which is
    worse than an error. The WHERE-clause tests pin the same form at the other rendering site; this
    is the one inside the CASE, and nothing else would notice the two disagreeing.

    The two files disagree on their headers, and their union has four columns where the files have
    two and three, so a count taken from the union instead of each file's own header fails on both
    branches rather than passing on the one file that happens to hold every column. One key carries
    a capital because the pseudo-column keeps the key's case: a lowercased mapping misses that file
    exactly as a bare key misses every file.

    The whole CASE is written out rather than parsed, and rather than built from the event, so the
    expectation cannot agree with the input by construction. That also pins what each branch
    compares, a branch shadowing another, and the ``ELSE false`` — none of which any other test
    asserts.
    """
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key, location: {
        "partitionKeys": [],
        "files": [
            {"key": "alice/sales/jan.csv", "size": 1, "columns": [
                {"name": "order_id", "type": "string"},
                {"name": "amount", "type": "string"},
            ]},
            {"key": "alice/sales/Feb.csv", "size": 1, "columns": [
                {"name": "order_id", "type": "string"},
                {"name": "region", "type": "string"},
                {"name": "channel", "type": "string"},
            ]},
        ],
    })

    v.handler(_event(), None)

    ragged = {kw["client_request_token"]: kw["query"] for kw in started}[f"{HEX32}-ragged"]
    assert (
        'CASE "$path" '
        "WHEN 's3://dq-user-bkt/alice/sales/Feb.csv' THEN cardinality(split(\"line\", ',')) <> 3 "
        "WHEN 's3://dq-user-bkt/alice/sales/jan.csv' THEN cardinality(split(\"line\", ',')) <> 2 "
        "ELSE false END"
    ) in ragged, "each file's branch, keyed by its full s3:// path and holding its own header's column count"


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

_THREE_TOKENS = sorted([f"{HEX32}-profile", f"{HEX32}-ragged", f"{HEX32}-dupes"])


def _manifest_listing(monkeypatch, keys):
    """Installs a manifest naming these keys, recording the location each load was contained to."""
    loaded = []

    def _load(bucket, key, location):
        loaded.append(location)
        return {
            "partitionKeys": [],
            "files": [
                {"key": k, "size": 1, "columns": [{"name": "order_id", "type": "string"}]} for k in keys
            ],
        }

    monkeypatch.setattr(v.manifest_store, "load", _load)
    return loaded


def test_every_query_is_narrowed_to_the_carried_file_whatever_the_manifest_now_lists(
    monkeypatch, started
):
    """A single-file check reports on the file only because this verb attaches the predicate.

    create-temp-tables promotes a single-file target's LOCATION to the parent folder, because an
    external table's location is a prefix and pointing it at an object key gives a table over
    nothing — and a location is read recursively, so that table also covers every sibling. This
    is the call site that has to pass the filter on, and it passes the one create promoted on.

    The manifest this verb loads lists TWO files: the overwrite a caller could once land between
    create and this verb. Re-deriving the decision from it would find no single file, attach no
    predicate, and profile the promoted folder — for a file at the space root, the whole space.
    """
    loaded = _manifest_listing(monkeypatch, ["alice/sales/jan.csv", "alice/sales/feb.csv"])

    v.handler(
        _event(location="alice/sales/jan.csv", pathFilter="s3://dq-user-bkt/alice/sales/jan.csv"),
        None,
    )

    narrowed = {kw["client_request_token"]: kw["query"] for kw in started}
    assert sorted(narrowed) == _THREE_TOKENS, "the three queries this assertion ranges over"
    for token, query in narrowed.items():
        assert f'WHERE "$path" = {_SELECTED}' in query, token
    assert loaded == ["alice/sales/jan.csv"], "the manifest must be contained to the checked location"


def test_a_folder_target_attaches_no_predicate_whatever_the_manifest_now_lists(monkeypatch, started):
    """The other direction, and the one nothing else would catch: a folder narrowed to one file.

    A folder check that gained a predicate would report on whichever file it picked and call the
    answer the folder's. The manifest here names exactly the location — the one shape a
    re-derivation reads as a single file — so a verb that consulted it instead of the state would
    narrow. The folder branch also has to render byte-identically to the pre-filter form, which is
    what lets ``_where`` return nothing at all rather than a clause that is always true.

    The needle is the comparison, not the column: the ragged query names ``"$path"`` in its
    per-file CASE whatever the target is, so an absence assertion over the column alone could
    never hold.
    """
    _manifest_listing(monkeypatch, ["alice/sales"])

    v.handler(_event(location="alice/sales", pathFilter=None), None)

    rendered = {kw["client_request_token"]: kw["query"] for kw in started}
    assert sorted(rendered) == _THREE_TOKENS, "the three queries this assertion ranges over"
    for token, query in rendered.items():
        assert '"$path" = ' not in query, token


def test_a_state_without_the_carried_decision_starts_no_query(started):
    """Absent is refused rather than read as a folder, which would leave a promoted table unnarrowed."""
    event = _event()
    del event["pathFilter"]

    with pytest.raises(TerminalError) as exc:
        v.handler(event, None)

    assert exc.value.reason == "invalid_request"
    assert "pathFilter" in exc.value.detail
    assert started == []
