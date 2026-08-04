"""``cpcommon.glue`` — the shape checks, and the registration that makes them sayable.

The move itself (SPEC-143 FR-004) is covered by table-share's suite passing unmodified:
its verbs still call ``glue_mod.clone_definition`` and still see the same four reason
codes. What table-share's suite CANNOT cover is the property that made the move risky, so
that is what this file is for.

Runnable under pytest or directly: python3 test_glue_cpcommon.py.
"""

import ast
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import config, glue
from cpcommon.errors import TerminalError

_HERE = os.path.dirname(os.path.abspath(__file__))

#: Read from config rather than hardcoded: the conftest stamps these with setdefault, so a
#: developer with USER_SPACE_BUCKET already exported would otherwise have every fixture
#: location rejected as source_location_unsupported.
USER_BUCKET = config.USER_SPACE_BUCKET


#: A minimal live Glue table in the shape ``get_table`` returns.
def _table(**overrides):
    table = {
        "Name": "sales",
        "TableType": "EXTERNAL_TABLE",
        "StorageDescriptor": {
            "Location": f"s3://{USER_BUCKET}/alice/sales/",
            "Columns": [{"Name": "order_id", "Type": "string"}],
            "SerdeInfo": {
                "SerializationLibrary": "org.apache.hadoop.hive.serde2.OpenCSVSerde",
                "Parameters": {"separatorChar": ","},
            },
            "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
        },
        "Parameters": {"skip.header.line.count": "1", "transient_lastDdlTime": "1", "EXTERNAL": "TRUE"},
        "PartitionKeys": [],
    }
    table.update(overrides)
    return table


def _reason(table):
    with pytest.raises(TerminalError) as excinfo:
        glue.clone_definition(table)
    return excinfo.value.reason


def test_a_flat_external_table_clones_with_its_bookkeeping_stripped():
    definition, location, partitioned = glue.clone_definition(_table())

    assert location == {"bucket": USER_BUCKET, "prefix": "alice/sales/"}
    assert partitioned is False
    assert definition["columns"] == [{"name": "order_id", "type": "string"}]
    assert definition["serde"]["parameters"] == {"separatorChar": ","}
    # transient_lastDdlTime and EXTERNAL are Hive bookkeeping, never carried.
    assert definition["tableProperties"] == {"skip.header.line.count": "1"}


def test_a_partition_projection_table_clones_as_partitioned():
    definition, _location, partitioned = glue.clone_definition(
        _table(
            PartitionKeys=[{"Name": "year", "Type": "int"}],
            Parameters={"projection.enabled": "true", "projection.year.type": "integer"},
        )
    )

    assert partitioned is True
    assert definition["partitionKeys"] == [{"name": "year", "type": "int"}]


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (_table(TableType="VIRTUAL_VIEW"), "source_is_view"),
        (_table(TableType="MANAGED_TABLE"), "source_not_external"),
        (_table(TableType=""), "source_not_external"),
        (
            _table(PartitionKeys=[{"Name": "year", "Type": "int"}], Parameters={}),
            "source_catalog_partitioned",
        ),
    ],
    ids=["view", "managed", "unset-type", "catalog-partitioned"],
)
def test_an_unreproducible_shape_is_refused_with_its_own_code(table, expected):
    assert _reason(table) == expected


@pytest.mark.parametrize(
    "location",
    [None, "alice/sales/", f"s3://{USER_BUCKET}", "s3://somebody-elses-bucket/alice/sales/"],
    ids=["absent", "not-s3", "no-prefix", "foreign-bucket"],
)
def test_an_unusable_location_is_one_reason_code_not_four(location):
    """SPEC-143 FR-004 AC3: there is no separate `table_has_no_location`.

    A missing LOCATION, an unparseable one and a bucket outside the two data buckets are
    all `source_location_unsupported`, because the refresh path maps this ONE code to
    `cannot_refresh_location_unsupported` and a second code would have nothing to map to.
    """
    storage = dict(_table()["StorageDescriptor"])
    if location is None:
        storage.pop("Location")
    else:
        storage["Location"] = location

    assert _reason(_table(StorageDescriptor=storage)) == "source_location_unsupported"


def test_an_object_level_location_normalizes_to_a_listable_prefix():
    storage = {**_table()["StorageDescriptor"], "Location": f"s3://{USER_BUCKET}/alice/sales"}

    _definition, location, _partitioned = glue.clone_definition(_table(StorageDescriptor=storage))

    assert location["prefix"] == "alice/sales/"


_PROBE = """
import os

from cpcommon import config, glue
from cpcommon.errors import TerminalError

reasons = []
for table_type in ("VIRTUAL_VIEW", "MANAGED_TABLE"):
    try:
        glue.clone_definition({"Name": "t", "TableType": table_type})
    except TerminalError as err:
        reasons.append(err.reason)
try:
    glue.clone_definition({"Name": "t", "TableType": "EXTERNAL_TABLE"})
except TerminalError as err:
    reasons.append(err.reason)
try:
    glue.clone_definition({
        "Name": "t",
        "TableType": "EXTERNAL_TABLE",
        "StorageDescriptor": {"Location": "s3://" + config.USER_SPACE_BUCKET + "/a/"},
        "PartitionKeys": [{"Name": "year", "Type": "int"}],
    })
except TerminalError as err:
    reasons.append(err.reason)
print(",".join(reasons))
"""

#: What the child keeps: enough to find the interpreter, plus exactly the six variables
#: cpcommon.config _require()s. An explicit allowlist rather than a denylist, matching
#: test_layer_import_safety.py — the point of the subprocess is a controlled environment.
_CHILD_KEEP = ("PATH", "SYSTEMROOT", "LD_LIBRARY_PATH")
_CHILD_REQUIRED = (
    "COGNITO_USER_POOL_ID",
    "COGNITO_APP_CLIENT_ID",
    "ADMIN_BUCKET",
    "USER_SPACE_BUCKET",
    "SHARED_SPACE_BUCKET",
    "ATHENA_WORKGROUP",
)


def test_the_shape_refusals_are_raisable_without_the_table_share_layer():
    """THE REASON THE MOVE NEEDED A REGISTRATION, and the only test that can see it.

    ``TerminalError`` validates its reason against ``cpcommon.messages`` AT THE RAISE SITE,
    and these four codes were registered solely by ``tscommon.messages``' import side
    effect. A table-builder Lambda attaches cpcommon + tbcommon and never imports tscommon,
    so before ``cpcommon.glue`` registered them itself, every shape refusal on the refresh
    path would have raised ``ValueError`` from inside the ``TerminalError`` constructor and
    surfaced to the user as the generic ``unexpected_error`` — the refusals this module
    exists to state clearly would have been exactly the ones it could not state.

    IN A SUBPROCESS, and it has to be: ``pytest lambdas/`` puts every layer root on
    ``sys.path`` and the table-share suite imports ``tscommon.messages`` in the same
    process, so an in-process assertion would pass whether or not this module registers
    anything. The only honest test is an interpreter that cannot see the table-share layer
    at all — which is also the deployed table-builder function's situation.
    """
    env = {k: v for k, v in os.environ.items() if k in _CHILD_KEEP + _CHILD_REQUIRED}
    env["PYTHONPATH"] = _HERE  # cpcommon ONLY — no tscommon on the path

    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _PROBE],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, (
        "clone_definition could not raise its own reason codes without the table-share "
        f"layer on the path:\n{result.stderr}"
    )
    assert result.stdout.strip().split(",") == [
        "source_is_view",
        "source_not_external",
        "source_location_unsupported",
        "source_catalog_partitioned",
    ]


def test_the_creation_marker_is_never_carried_into_a_clone():
    """SPEC-143 FR-007 AC2. Inheriting it would have a copy claim it was created by the
    call that created its SOURCE — the marker records who built THIS table."""
    table = _table(Parameters={"portal.managed": "true", "skip.header.line.count": "1"})

    definition, _location, _partitioned = glue.clone_definition(table)

    assert definition["tableProperties"] == {"skip.header.line.count": "1"}


def test_no_verb_reads_the_creation_marker_to_decide_anything():
    """SPEC-143 FR-007 AC4, and the guard that keeps the marker honest.

    Refresh eligibility turns on SHAPE, never on this property, and the reasons are
    permanent: every table created before SPEC-143 lacks it, and TBLPROPERTIES are
    user-writable through ALTER TABLE SET TBLPROPERTIES — so it can be trusted neither as
    a permission nor as a fact. The moment a verb branches on it, a user can grant
    themselves whatever that branch guards.

    Scans the whole Lambda tree, so this holds for verbs not yet written, and scans the
    parsed CODE rather than the text. Two reasons, each of which broke a simpler version:

    * ``PORTAL_MANAGED`` is a public name in ``cpcommon.ddl``, so importing it is the most
      natural way a future verb would reach the marker — and it contains no matching
      string literal, so a literal-only grep waves it straight through.
    * A text scan reports every COMMENT that merely names the property, including the ones
      warning readers not to confuse it with the hyphenated Lake Formation tag. Discussing
      the marker is not reading it. (``PORTAL_MANAGED_TAG_KEY``, that unrelated tag's
      constant, is one character away and correctly ignored — it is a different name.)
    """
    allowed = {
        os.path.join("control-plane-common", "cpcommon", "ddl.py"),      # writes it
        os.path.join("control-plane-common", "cpcommon", "glue.py"),     # excludes it
        os.path.join("control-plane-common", "test_ddl_cpcommon.py"),
        os.path.join("control-plane-common", "test_glue_cpcommon.py"),
    }
    lambdas = os.path.dirname(_HERE)

    def _references(tree):
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value == "portal.managed":
                return True
            if isinstance(node, ast.Name) and node.id == "PORTAL_MANAGED":
                return True
            if isinstance(node, ast.Attribute) and node.attr == "PORTAL_MANAGED":
                return True
        return False

    offenders = []
    for root, _dirs, files in os.walk(lambdas):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            relative = os.path.relpath(path, lambdas)
            if relative in allowed:
                continue
            with open(path) as handle:
                if _references(ast.parse(handle.read())):
                    offenders.append(relative)

    assert not offenders, f"the marker is referenced outside its two homes: {offenders}"


def test_table_share_still_reaches_clone_definition_through_its_own_module():
    """The re-export is the contract table-share's verbs and tests are written against.

    Relies on ``lambdas/conftest.py`` for the table-share layer root, so this one is
    pytest-only — a direct run skips it rather than mutating ``sys.path`` permanently.
    """
    try:
        from tscommon import glue as ts_glue
    except ImportError:  # direct run: only this layer is on the path
        pytest.skip("table-share layer not on sys.path (run under pytest lambdas/)")

    assert ts_glue.clone_definition is glue.clone_definition


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
