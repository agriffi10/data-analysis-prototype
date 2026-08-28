"""Unit tests for the data-quality create-temp-tables Lambda (SPEC-111 FR-001/FR-002).

AWS stubbed: the S3 client (the manifest read) and ``athena.run_ddl`` are replaced on the
verb module, so no bucket and no catalog is touched. The assertions are mostly about the
DDL that WOULD have been run, because that is the whole output of this verb.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data-quality-common"))

import dq_create_temp_tables as v
import pytest
from cpcommon.errors import TerminalError
from dqcommon import config, messages

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
    }
    event.update(overrides)
    return event


_DEFAULT_FILES = [
    {
        "key": "alice/sales/jan.csv",
        "size": 10,
        "columns": [{"name": "order_id", "type": "string"}, {"name": "amount", "type": "string"}],
    }
]


def _manifest(files=None, partition_keys=None, fmt="csv"):
    # `is not None`, NOT `or`: an EMPTY file list is a case under test (the guard against
    # building a table over the space root), and `or` would silently swap it for the
    # default — making that test assert nothing.
    resolved = _DEFAULT_FILES if files is None else files
    return {
        "requestId": REQUEST_ID,
        "format": fmt,
        "fileCount": len(resolved),
        "partitionKeys": partition_keys or [],
        "files": resolved,
    }


@pytest.fixture
def ran(monkeypatch):
    """Capture every DDL statement the verb would run, with a default manifest stubbed."""
    statements = []
    monkeypatch.setattr(v.athena, "run_ddl", lambda **kw: statements.append(kw) or "qid-1")
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: _manifest())
    return statements


def _install_manifest(monkeypatch, manifest):
    monkeypatch.setattr(v.manifest_store, "load", lambda bucket, key: manifest)


# ── The typed table ──────────────────────────────────────────────────────────


def test_csv_creates_both_the_typed_and_the_raw_table(ran):
    out = v.handler(_event(), None)

    assert out["tempTable"] == f"dq_tmp_{HEX32}"
    assert out["tempRawTable"] == f"dq_tmp_raw_{HEX32}"
    assert len(ran) == 2
    assert "OpenCSVSerde" in ran[0]["query"]
    assert "LazySimpleSerDe" in ran[1]["query"]


# ── The width cap ────────────────────────────────────────────────────────────


def test_a_source_wider_than_the_cap_is_a_terminal_too_many_columns(monkeypatch, ran):
    wide = [{"name": f"c{i}", "type": "string"} for i in range(config.DQ_MAX_COLUMNS + 1)]
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/w.csv", "size": 1, "columns": wide}]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.TOO_MANY_COLUMNS
    # And nothing was created — the cap fires BEFORE any DDL runs, so a too-wide source
    # cannot leak a table.
    assert ran == []


# ── Column names ─────────────────────────────────────────────────────────────
#
# The reported bug: a data-quality check said nothing about column names, so a folder whose
# headers Athena cannot use passed the check and then produced an unbuildable — or worse, a
# built-but-unreadable — table. The check cannot report on data it cannot read, so the answer
# is a refusal naming the columns rather than a report that never gets built.


def test_a_header_athena_cannot_use_is_a_terminal_that_names_the_columns(monkeypatch, ran):
    _install_manifest(monkeypatch, _manifest(
        files=[{"key": "alice/sales/jan.csv", "size": 1, "columns": [
            {"name": "order_id", "type": "string"},
            {"name": "Order ID", "type": "string"},
        ]}]
    ))

    with pytest.raises(TerminalError) as exc:
        v.handler(_event(), None)

    assert exc.value.reason == messages.INVALID_COLUMN_NAMES
    assert exc.value.tokens["columns"] == '"Order ID"'
    # Nothing was created: the check fires BEFORE any DDL runs, so a refused source cannot
    # leak a temp table into the user's own database.
    assert ran == []


# ── Shape validation ─────────────────────────────────────────────────────────


def _raise(exc):
    def _fn(**_kw):
        raise exc

    return _fn


