"""Unit tests for the table-share create-table Lambda (SPEC-092).

Pure logic, AWS stubbed: Athena run_ddl is faked at the module seam. Asserts the
rendered DDL (recipient DB + repointed LOCATION + carried projection props), the
recipient-DB execution context + results routing, the pass-through output, and the
terminal/transient routing. Runnable under pytest or directly:
python3 test_table_share_create_table.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_create_table as m
from cpcommon.errors import TerminalError


class _FakeRunDdl:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return "qid-1"


_DEFINITION = {
    "columns": [{"name": "id", "type": "bigint"}, {"name": "amount", "type": "double"}],
    "partitionKeys": [{"name": "dt", "type": "string"}],
    "serde": {
        "serializationLibrary": "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe",
        "parameters": {"serialization.format": "1"},
    },
    "inputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
    "outputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
    "tableType": "EXTERNAL_TABLE",
    "tableProperties": {"projection.enabled": "true", "projection.dt.type": "enum", "projection.dt.values": "a,b"},
}


_DEFINITION_KEY = "table-share/h/definition.json"


def _event(definition=_DEFINITION):
    """One Map item, with the definition staged behind its pointer (SPEC-161 FR-002).

    The stub stands in for ``copy_plan.load_definition``, which is the seam the verb now
    fetches through. It round-trips through JSON deliberately: returning the caller's own dict
    would make the equivalence test below compare ``render(x)`` with ``render(x)`` and pass
    however badly the real writer and reader mangled the definition in between.

    No local restore: conftest's SPEC-153 FR-004 snapshot covers shared-layer module
    namespaces, tscommon included.
    """
    m.copy_plan.load_definition = lambda key: json.loads(json.dumps(definition))
    return {
        "recipient": {
            "kind": "user",
            "name": "bob",
            "valid": True,
            "database": "bob",
            "destBucket": "user-bkt",
            "destPrefix": "bob/shared_tables/orders_copy/",
        },
        "request": {
            "actor": "alice",
            "source": {"database": "alice", "table": "orders"},
            "tableName": "orders_copy",
            "definitionKey": _DEFINITION_KEY,
            "location": {"bucket": "user-bkt", "prefix": "alice/sales/"},
        },
    }


@pytest.fixture(autouse=True)
def _restore_the_runner():
    """Puts the real ``run_ddl`` back on the verb's runner after every test.

    A local restore is REQUIRED, and the note that said otherwise was true only while
    ``athena_mod`` was the module ``tscommon.athena``: conftest's SPEC-153 FR-004 snapshot
    matches shared-layer modules by name and restores a module NAMESPACE. Since SPEC-156
    FR-005 this is a ``BoundRunner`` instance held by a verb module, so it is neither matched
    nor reachable — restoring the namespace rebinds the same instance, attribute intact. The
    leak was invisible only because the file that would have caught it sorts first.
    """
    original = m.athena_mod.run_ddl
    yield
    m.athena_mod.run_ddl = original


def _setup(error=None):
    """Stubs the verb's bound DDL runner. Restored by the autouse fixture above."""
    fake = _FakeRunDdl(error=error)
    m.athena_mod.run_ddl = fake
    return fake


def test_renders_and_runs_the_clone_ddl_against_the_recipient_db():
    fake = _setup()
    out = m.handler(_event(), None)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["database"] == "bob"
    assert call["workgroup"] == "test-workgroup"
    assert call["output_location"] == "s3://user-bkt/bob/athenaresults/alice/"

    query = call["query"]
    assert query.startswith("CREATE EXTERNAL TABLE IF NOT EXISTS `bob`.`orders_copy` (")
    assert "`id` bigint, `amount` double" in query
    assert "PARTITIONED BY (`dt` string)" in query
    assert "LOCATION 's3://user-bkt/bob/shared_tables/orders_copy/'" in query
    assert "'projection.enabled'='true'" in query
    assert "'projection.dt.values'='a,b'" in query
    assert "ROW FORMAT SERDE 'org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe'" in query
    assert "STORED AS INPUTFORMAT 'org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat'" in query
    assert "OUTPUTFORMAT 'org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat'" in query

    # The item state threads through unchanged for RecipientSucceeded.
    assert out["recipient"]["name"] == "bob"
    assert out["request"]["tableName"] == "orders_copy"


def test_flat_definition_renders_without_partition_or_properties_clauses():
    fake = _setup()
    flat = {**_DEFINITION, "partitionKeys": [], "tableProperties": {}}
    m.handler(_event(definition=flat), None)
    query = fake.calls[0]["query"]
    assert "PARTITIONED BY" not in query
    assert "TBLPROPERTIES" not in query


def test_serde_properties_and_literal_escaping():
    fake = _setup()
    quirky = {
        **_DEFINITION,
        "partitionKeys": [],
        "serde": {
            "serializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
            "parameters": {"escapeChar": "\\", "quoteChar": "'"},
        },
        "tableProperties": {"skip.header.line.count": "1"},
    }
    m.handler(_event(definition=quirky), None)
    query = fake.calls[0]["query"]
    assert "WITH SERDEPROPERTIES ('escapeChar'='\\\\', 'quoteChar'='\\'')" in query
    assert "TBLPROPERTIES ('skip.header.line.count'='1')" in query


def test_column_comment_is_carried_and_escaped():
    fake = _setup()
    commented = {
        **_DEFINITION,
        "columns": [{"name": "id", "type": "bigint", "comment": "the 'primary' id"}],
        "partitionKeys": [],
    }
    m.handler(_event(definition=commented), None)
    assert "`id` bigint COMMENT 'the \\'primary\\' id'" in fake.calls[0]["query"]


def test_the_definition_is_fetched_from_the_key_on_the_request():
    """SPEC-161 FR-002 AC1 — the verb reads a pointer, never a value on the state."""
    fake = _setup()
    fetched = []
    event = _event()
    m.copy_plan.load_definition = lambda key: (fetched.append(key) or _DEFINITION)

    m.handler(event, None)

    assert fetched == [_DEFINITION_KEY]
    assert "tableDefinition" not in event["request"]
    assert "`id` bigint, `amount` double" in fake.calls[0]["query"]


def test_the_pointer_renders_the_same_ddl_the_inline_definition_did():
    """SPEC-161 FR-002 AC2 — byte-identical, asserted rather than assumed.

    The move is only safe if it is a pure change of transport. Rendering the SAME definition
    through the renderer directly and through the verb's fetch-then-render path must produce
    one string; anything the pointer did to the definition on the way (a re-serialisation that
    reorders properties, a lost comment) shows up here as a diff and nowhere else.

    The fetch stub round-trips through JSON, so this exercises the serialisation the real
    writer and reader perform. Run over a definition with comments, projection properties and
    SerDe parameters rather than the bare one, because those are the parts a round-trip could
    plausibly disturb.
    """
    fake = _setup()
    rich = {
        **_DEFINITION,
        "columns": [
            {"name": "id", "type": "bigint", "comment": "the 'primary' id"},
            {"name": "amount", "type": "double", "comment": "in \\ units"},
        ],
    }
    recipient = _event()["recipient"]
    inline = m.ddl.render_create_external(
        rich,
        recipient["database"],
        "orders_copy",
        f"s3://{recipient['destBucket']}/{recipient['destPrefix']}",
    )

    m.handler(_event(definition=rich), None)

    assert fake.calls[0]["query"] == inline


def test_an_unreadable_definition_fails_only_this_recipient():
    """SPEC-161 FR-002 AC5 — no table over a partial definition, and no sibling harmed.

    A TerminalError here ends the finish Map's ITEM, which is what leaves the other recipients
    running. The assertion that matters alongside the reason is that Athena was never called:
    a definition with no columns renders a syntactically valid CREATE over the recipient's
    freshly-copied data, and that table reads as a success and returns nothing.
    """
    fake = _setup()
    event = _event()
    m.copy_plan.load_definition = lambda key: (_ for _ in ()).throw(
        TerminalError("definition_unreadable", f"could not read table definition {key}: nope")
    )

    with pytest.raises(TerminalError) as excinfo:
        m.handler(event, None)

    assert excinfo.value.reason == "definition_unreadable"
    assert fake.calls == [], "no DDL may run when the definition could not be read"


def test_athena_terminal_failure_propagates_as_create_failed():
    _setup(error=TerminalError("create_failed", "SYNTAX_ERROR: line 1"))
    try:
        m.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == "create_failed"
        return
    raise AssertionError("expected TerminalError('create_failed')")


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    raise SystemExit(1 if failures else 0)
