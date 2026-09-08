"""The one-shot migration's guards, its record, and the two points where it must refuse.

The module is a script rather than a Lambda, so it is imported through the same ``sys.path`` shim
``scripts/generate_api_contract.py`` uses. Every scenario drives the real S3 and Glue fakes rather
than a mock of the module's own calls: the fakes model what S3 actually returns — a ``CopyObject``
that preserves nothing by default, a ``DeleteObjects`` that reports per-item failures inside an
HTTP 200 — and those two shapes are the ones this module exists to get right.

**Why most scenarios patch the singular builder.** ``switch_has_landed`` asks
``app_managed_prefix`` where a write goes, and in this checkout it still answers depth one, because
FR-001 has not merged. That is the guard working; one scenario asserts it. The rest patch the
builder to its post-switch answer, which is exactly the state the migration is dispatched in.
"""

from __future__ import annotations

import contextlib
import json
import logging
import pathlib
import sys
from typing import ClassVar

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(LAMBDAS.parent / "scripts"))
sys.path.insert(0, str(LAMBDAS / "shared-space-common"))

import migrate_system_settings as migrate
from fakes import FakeClientError, FakeGlue, FakeS3

USER_BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"
ADMIN_BUCKET = "dat-prod-athena-admin"

CONFIG = {
    "user_space_bucket": USER_BUCKET,
    "shared_space_bucket": SHARED_BUCKET,
    "admin_bucket": ADMIN_BUCKET,
    "archive_state_machine_arn": "arn:aws:states:us-east-1:1:stateMachine:dat-prod-archive",
    "table_share_state_machine_arn": "arn:aws:states:us-east-1:1:stateMachine:dat-prod-share",
    "workgroup": "dat-prod-portal-wg",
}


class FakeSfn:
    """A Step Functions client that reports whichever executions a scenario planted.

    Attributes:
      running: Execution ARNs per state machine ARN.
    """

    def __init__(self, running=None):
        """Records what is in flight.

        Args:
          running: Execution ARNs keyed by state machine ARN.

        Returns:
          None.

        Raises:
          None.
        """
        self.running = running or {}

    def list_executions(self, stateMachineArn, statusFilter, nextToken=None):
        """Lists the planted executions for one machine.

        Args:
          stateMachineArn: The machine.
          statusFilter: The status asked for.
          nextToken: Unused; one page is enough here.

        Returns:
          The executions.

        Raises:
          None.
        """
        return {
            "executions": [
                {"executionArn": arn} for arn in self.running.get(stateMachineArn, [])
            ]
        }


class FakeAthena:
    """An Athena client whose executions carry whatever states a scenario planted.

    Attributes:
      states: Execution id to state.
    """

    def __init__(self, states=None):
        """Records the planted executions.

        Args:
          states: Execution id to state.

        Returns:
          None.

        Raises:
          None.
        """
        self.states = states or {}

    def list_query_executions(self, WorkGroup, NextToken=None):
        """Lists the planted execution ids.

        Args:
          WorkGroup: The workgroup.
          NextToken: Unused.

        Returns:
          The ids.

        Raises:
          None.
        """
        return {"QueryExecutionIds": list(self.states)}

    def batch_get_query_execution(self, QueryExecutionIds):
        """Describes the planted executions.

        Args:
          QueryExecutionIds: The ids to describe.

        Returns:
          Each id with its state.

        Raises:
          None.
        """
        return {
            "QueryExecutions": [
                {"QueryExecutionId": qid, "Status": {"State": self.states[qid]}}
                for qid in QueryExecutionIds
            ]
        }


@pytest.fixture
def switched(monkeypatch):
    """Puts the checkout in its post-FR-001 state, where the singular builder has moved.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setattr(
        migrate,
        "app_managed_prefix",
        lambda root, folder: f"{root}system_settings/{folder}/",
    )


def clients(s3=None, glue=None, sfn=None, athena=None):
    """Assembles the client bundle the modes take.

    Args:
      s3: An S3 fake, or a fresh one.
      glue: A Glue fake, or a fresh one.
      sfn: A Step Functions fake, or an idle one.
      athena: An Athena fake, or an idle one.

    Returns:
      The bundle.

    Raises:
      None.
    """
    return {
        "s3": s3 or FakeS3(),
        "glue": glue or FakeGlue(),
        "sfn": sfn or FakeSfn(),
        "athena": athena or FakeAthena(),
    }


def seed_space(s3, bucket="dat-prod-user-space", space="alice/", folder="athenaresults", keys=("q1/r.csv",)):
    """Puts objects under a space's OLD app-managed prefix.

    Args:
      s3: The S3 fake.
      bucket: The bucket.
      space: The space root, trailing slash.
      folder: Which moving folder.
      keys: Key tails under that folder.

    Returns:
      The full keys written.

    Raises:
      None.
    """
    written = []
    for tail in keys:
        key = f"{space}{folder}/{tail}"
        s3.store[(bucket, key)] = b"bytes"
        written.append(key)
    return written


def rid(key, bucket=USER_BUCKET):
    """The record's identifier for one object, so scenarios stay written in S3 keys.

    Args:
      key: The object key.
      bucket: The bucket it lives in.

    Returns:
      The identifier the record uses.

    Raises:
      None.
    """
    return migrate.recorded_id(bucket, key)


def test_a_key_outside_the_three_folders_is_refused_by_name():
    """A key under a folder the migration does not move is refused, and the code says which rule.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.folder_of("alice/user_settings/theme.json", "alice/")
    assert caught.value.code == "outside_migration_scope"


def test_a_location_outside_the_old_shared_tables_prefix_is_refused_by_name():
    """A table whose data never lived under the old prefix is refused, not silently re-pointed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.migrated_location("s3://dat-prod-user-space/alice/projects/t/", "alice/")
    assert caught.value.code == "location_not_migrated"


def test_a_location_already_at_the_new_home_is_refused_rather_than_moved_twice():
    """A re-run must not build ``system_settings/system_settings/``.

    The refusal is also the filter ``tables_to_repoint`` uses, so a table already re-pointed is
    simply not returned — which is what makes a second ``copy`` re-point zero tables.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.migrated_location(
            "s3://dat-prod-user-space/alice/system_settings/shared_tables/t/", "alice/"
        )
    assert caught.value.code == "location_not_migrated"


def test_copy_refuses_while_the_switch_has_not_landed():
    """Before FR-001 merges, a copy would race the fleet's own writes — so it refuses.

    This is the guard that turns "merge PR 2 two merges early" from a data-loss window into a
    refusal. It runs WITHOUT the ``switched`` fixture on purpose: the builder in this checkout
    still answers depth one, which is precisely the condition being asserted.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_copy(clients(), CONFIG, "run-1")
    assert caught.value.code == "switch_not_landed"


def test_prove_empty_refuses_once_the_narrowing_has_shrunk_the_plural(monkeypatch):
    """After PR 4 the old home is unaddressable, so proving it empty would answer the wrong question.

    ``old_prefix`` reads the plural builder's first element; the narrowing deletes that element.
    Without this refusal the mode would enumerate the NEW home and report "empty" about a prefix
    nobody asked about — a guard that cannot see its own shrink.

    Args:
      monkeypatch: pytest's patcher, used to simulate the narrowed builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    monkeypatch.setattr(
        migrate, "app_managed_prefixes", lambda root, folder: (f"{root}{folder}/",)
    )
    s3 = FakeS3()
    s3.store[(USER_BUCKET, "alice/x")] = b""
    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_prove_empty(clients(s3=s3), CONFIG)
    assert caught.value.code == "narrowing_already_merged"


def test_copy_refuses_to_start_and_names_every_execution_that_must_finish_first(switched):
    """A restore, a share or a query in flight computes a destination the copy would then miss.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing, carries another code, or does not name the work.
    """
    sfn = FakeSfn(
        {
            CONFIG["archive_state_machine_arn"]: ["arn:exec:restore-7"],
            CONFIG["table_share_state_machine_arn"]: ["arn:exec:share-9"],
        }
    )
    athena = FakeAthena({"q-42": "RUNNING", "q-43": "SUCCEEDED"})
    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_copy(clients(sfn=sfn, athena=athena), CONFIG, "run-1")
    assert caught.value.code == "precondition_in_flight"
    named = str(caught.value)
    assert "restore-7" in named
    assert "share-9" in named
    assert "q-42" in named
    assert "q-43" not in named


def test_copy_preserves_the_storage_class_and_leaves_both_directives_at_copy(switched):
    """S3 preserves none of this by default, so the parameters are the behaviour.

    A ``CopyObject`` that omits ``StorageClass`` lands the copy in ``STANDARD`` whatever the source
    was, and naming ``ContentType`` would force ``MetadataDirective=REPLACE`` and drop the user
    metadata. Both are asserted on the call rather than on the result, because the result of a
    correct copy and of a lossy one look alike until someone reads the object back.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When a directive or the storage class is wrong.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    s3.storage_class[(USER_BUCKET, key)] = "GLACIER_IR"
    s3.metadata[(USER_BUCKET, key)] = {"owner": "alice"}
    s3.tags[(USER_BUCKET, key)] = [{"Key": "class", "Value": "restricted"}]

    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    assert s3.copy_parameters["StorageClass"] == "GLACIER_IR"
    assert s3.copy_parameters["MetadataDirective"] == "COPY"
    assert s3.copy_parameters["TaggingDirective"] == "COPY"
    moved = "alice/system_settings/athenaresults/q1/r.csv"
    assert s3.head_object(Bucket=USER_BUCKET, Key=moved)["Metadata"] == {"owner": "alice"}
    assert s3.get_object_tagging(Bucket=USER_BUCKET, Key=moved)["TagSet"] == [
        {"Key": "class", "Value": "restricted"}
    ]


def test_an_object_over_five_gibibytes_is_copied_in_parts(switched):
    """``CopyObject`` is refused above 5 GiB, so an oversize source rides ``UploadPartCopy``.

    It is recorded under ``oversize`` rather than refused, because a large result set is ordinary.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the object was not copied in parts or not recorded.
    """
    s3 = FakeS3()
    key = seed_space(s3, keys=("big.csv",))[0]
    s3.sizes[(USER_BUCKET, key)] = 6 * 1024 * 1024 * 1024

    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert rid(key) in record["oversize"]
    assert rid(key) in record["oversize_done"]
    assert any(operation[0] == "complete" for operation in s3.operations)


def test_a_second_copy_with_the_same_run_id_copies_nothing(switched):
    """Idempotence is what lets an interrupted run be resumed rather than restarted.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the second run copied anything.
    """
    s3 = FakeS3()
    seed_space(s3)
    bundle = clients(s3=s3)
    migrate.mode_copy(bundle, CONFIG, "run-1")
    copies = [operation for operation in s3.operations if operation[0] == "copy"]

    migrate.mode_copy(bundle, CONFIG, "run-1")

    assert [operation for operation in s3.operations if operation[0] == "copy"] == copies


def test_a_destination_with_no_record_is_a_conflict_and_is_not_overwritten(switched):
    """Something else wrote there. The migration reports it and leaves both sides alone.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the key was overwritten or not reported.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    destination = "alice/system_settings/athenaresults/q1/r.csv"
    s3.store[(USER_BUCKET, destination)] = b"someone else"

    exit_code = migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    assert exit_code == 1
    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["conflicts"] == [rid(key)]
    assert s3.store[(USER_BUCKET, destination)] == b"someone else"


def test_report_writes_nothing(switched):
    """The mode an operator runs first must be safe to run at any time.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the store changed.
    """
    s3 = FakeS3()
    seed_space(s3)
    before = dict(s3.store)

    migrate.mode_report(clients(s3=s3), CONFIG, None)

    assert s3.store == before
    assert s3.operations == []


def test_finish_refuses_while_a_conflict_is_unresolved(switched):
    """An unresolved conflict means somebody must look, so nothing may be deleted yet.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    s3.store[(USER_BUCKET, "alice/system_settings/athenaresults/q1/r.csv")] = b"other"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    assert caught.value.code == "conflicts_outstanding"
    assert (USER_BUCKET, key) in s3.store


def test_finish_refuses_without_a_record(switched):
    """Deleting against no record would be deleting against nothing.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_finish(clients(), CONFIG, "never-ran")
    assert caught.value.code == "no_record"


def test_finish_deletes_a_verified_source_and_leaves_a_rewritten_one(switched):
    """The head re-verify is the guard, and this is the case it exists for.

    A source rewritten between ``copy`` and ``finish`` holds bytes nobody copied. Deleting it
    would lose them silently — the destination looks complete either way — so it lands under
    ``refused`` and the run exits non-zero.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the rewritten source was deleted or the verified one survived.
    """
    s3 = FakeS3()
    safe, rewritten = seed_space(s3, keys=("safe.csv", "rewritten.csv"))
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    s3.store[(USER_BUCKET, rewritten)] = b"changed after the copy"
    s3.etags[(USER_BUCKET, rewritten)] = '"etag-rewritten"'

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    assert exit_code == 1
    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["refused"] == [rid(rewritten)]
    assert (USER_BUCKET, rewritten) in s3.store
    assert (USER_BUCKET, safe) not in s3.store


def test_finish_run_twice_reports_the_deleted_sources_as_absent(switched):
    """Re-running after a partial run must be safe, so a gone source is ordinary, not an error.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the second run deleted anything or refused.
    """
    s3 = FakeS3()
    keys = seed_space(s3, keys=("a.csv", "b.csv"))
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")
    deletes = len([o for o in s3.operations if o[0] == "delete"])

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert exit_code == 0
    assert record is not None
    assert sorted(record["absent"]) == sorted(rid(k) for k in keys)
    assert record["refused"] == []
    assert len([o for o in s3.operations if o[0] == "delete"]) == deletes


def test_finish_reads_the_per_item_errors_array_rather_than_the_http_status(switched):
    """``DeleteObjects`` reports a failure inside an HTTP 200, so the array is the only signal.

    A caller reading the call's success would report a finished migration over sources that are
    still there — which is the failure the fake models on purpose.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the undeletable key was not reported.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    s3.undeletable.add(key)

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert exit_code == 1
    assert record is not None
    assert record["refused"] == [rid(key)]


def test_finish_sends_the_recorded_source_etag_when_the_runtime_carries_the_field(switched):
    """The identifier ETag is belt, and it is only sent when botocore can serialize it.

    A model without the member raises ``ParamValidationError`` for the WHOLE request rather than
    a per-item error, so the probe decides. Both branches are asserted, because the one that
    silently omits the ETag is the one that would go unnoticed.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the ETag is sent by a runtime that cannot serialize it, or omitted by
        one that can.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    recorded = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert recorded is not None
    expected = recorded["keys"][rid(key)]["source_etag"]

    assert migrate.supports_conditional_delete(s3) is False
    migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")
    assert all("ETag" not in i for i in s3.delete_identifiers)

    other = FakeS3()
    seed_space(other)
    other.meta = _ModelWithEtag()
    migrate.mode_copy(clients(s3=other), CONFIG, "run-2")
    assert migrate.supports_conditional_delete(other) is True
    migrate.mode_finish(clients(s3=other), CONFIG, "run-2")
    assert [i.get("ETag") for i in other.delete_identifiers] == [expected]


class _ModelWithEtag:
    """A botocore stand-in whose ``ObjectIdentifier`` carries the ``ETag`` member.

    Mirrors the shape ``supports_conditional_delete`` introspects, so the branch that DOES send
    the identifier ETag is reachable in a test rather than only in production.

    Attributes:
      service_model: The object exposing ``shape_for``.
    """

    class _Shape:
        """The shape whose members the probe reads.

        Attributes:
          members: The member names.
        """

        members: ClassVar[dict[str, object]] = {
            "Key": object(),
            "VersionId": object(),
            "ETag": object(),
        }

    class _Service:
        """The service model exposing ``shape_for``."""

        def shape_for(self, name):
            """Returns the shape for a name.

            Args:
              name: The shape's name.

            Returns:
              The shape.

            Raises:
              KeyError: When another shape is asked for, as botocore would.
            """
            if name != "ObjectIdentifier":
                raise KeyError(name)
            return _ModelWithEtag._Shape

    service_model = _Service()


def seed_table(glue, database="alice", name="sales", location=None):
    """Puts one table in the catalog with a StorageDescriptor pointing somewhere.

    Args:
      glue: The Glue fake.
      database: The database, which is the space's own name.
      name: The table name.
      location: The table's location, defaulting to the OLD shared-tables prefix.

    Returns:
      The location seeded.

    Raises:
      None.
    """
    where = location or f"s3://{USER_BUCKET}/{database}/shared_tables/{name}/"
    glue.databases.add(database)
    glue.tables.setdefault(database, []).append(name)
    glue.definitions[(database, name)] = {
        "Name": name,
        "StorageDescriptor": {"Location": where, "Columns": [{"Name": "id"}]},
    }
    return where


def test_a_moved_table_is_repointed_and_the_previous_version_is_retained(switched):
    """``SkipArchive=False`` is the rollback: the retained version is where the old location lives.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the location did not move or no version was retained.
    """
    s3 = FakeS3()
    glue = FakeGlue()
    seed_space(s3, folder="shared_tables", keys=("sales/part.parquet",))
    previous = seed_table(glue)

    migrate.mode_copy(clients(s3=s3, glue=glue), CONFIG, "run-1")

    assert glue.update_calls[0]["SkipArchive"] is False
    moved = glue.get_table(DatabaseName="alice", Name="sales")["Table"]
    assert moved["StorageDescriptor"]["Location"] == (
        f"s3://{USER_BUCKET}/alice/system_settings/shared_tables/sales/"
    )
    assert glue.archived["alice.sales"][0]["StorageDescriptor"]["Location"] == previous
    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["tables"]["alice.sales"] == previous


def test_a_second_copy_repoints_no_table(switched):
    """A table already at the new home is filtered by ``location_not_migrated``, not re-pointed.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the second run touched the catalog.
    """
    s3 = FakeS3()
    glue = FakeGlue()
    seed_space(s3, folder="shared_tables", keys=("sales/part.parquet",))
    seed_table(glue)
    bundle = clients(s3=s3, glue=glue)
    migrate.mode_copy(bundle, CONFIG, "run-1")
    calls = len(glue.update_calls)

    migrate.mode_copy(bundle, CONFIG, "run-1")

    assert len(glue.update_calls) == calls


def test_a_readback_that_disagrees_stops_the_run_before_the_rest_are_repointed(switched, monkeypatch):
    """The first re-point is read back because an IAM simulate cannot see Lake Formation.

    The deploy role is an LF data-lake admin, so this call IS the probe: a silent LF refusal would
    otherwise leave every table pointing at data the migration then deleted.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the run continued past a disagreeing read-back.
    """
    s3 = FakeS3()
    glue = FakeGlue()
    seed_space(s3, folder="shared_tables", keys=("a/p.parquet", "b/p.parquet"))
    seed_table(glue, name="a")
    seed_table(glue, name="b")
    monkeypatch.setattr(migrate, "read_back_location", lambda *a: "s3://elsewhere/wrong/")

    with pytest.raises(migrate.Refusal) as caught:
        migrate.mode_copy(clients(s3=s3, glue=glue), CONFIG, "run-1")

    assert caught.value.code == "location_readback_failed"
    assert len(glue.update_calls) == 1, (
        "the probe must stop the run after the FIRST re-point; re-pointing every table and then "
        "reading one back would leave the rest pointing at data finish is about to delete"
    )


def test_resolve_keeping_the_source_recopies_and_records_the_new_etag(switched):
    """The operator chose the source, so the destination is overwritten and the record follows.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the conflict survived or the record was not updated.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    destination = "alice/system_settings/athenaresults/q1/r.csv"
    s3.store[(USER_BUCKET, destination)] = b"someone else"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    migrate.mode_resolve(clients(s3=s3), CONFIG, "run-1", key, "source")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["conflicts"] == []
    assert record["keys"][rid(key)]["resolution"] == "keep-source"
    assert record["keys"][rid(key)]["copied_etag"] == s3.etags[(USER_BUCKET, destination)]
    assert s3.store[(USER_BUCKET, destination)] == b"bytes"


def test_resolve_keeping_the_destination_lets_finish_delete_the_source(switched):
    """A table re-shared after the switch: the destination is the newer data, so the source goes.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the conflict survived or the source was not deleted.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    destination = "alice/system_settings/athenaresults/q1/r.csv"
    s3.store[(USER_BUCKET, destination)] = b"newer"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    migrate.mode_resolve(clients(s3=s3), CONFIG, "run-1", key, "destination")
    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["conflicts"] == []
    assert record["keys"][rid(key)]["resolution"] == "keep-destination"
    assert exit_code == 0
    assert (USER_BUCKET, key) not in s3.store
    assert s3.store[(USER_BUCKET, destination)] == b"newer"


def test_prove_empty_passes_only_once_every_old_prefix_is_gone(switched):
    """The positive proof that the migration finished, from the account rather than from a plan.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When an occupied prefix passed or an empty one failed.
    """
    s3 = FakeS3()
    seed_space(s3)
    s3.store[(USER_BUCKET, "alice/notes/keep.txt")] = b"ordinary user file"

    assert migrate.mode_prove_empty(clients(s3=s3), CONFIG) == 1

    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    assert migrate.mode_prove_empty(clients(s3=s3), CONFIG) == 0
    assert (USER_BUCKET, "alice/notes/keep.txt") in s3.store


def test_prove_empty_reads_a_failed_listing_as_occupied_not_as_empty(switched):
    """A failed call and an empty prefix answer the same shape, and only one of them is proof.

    Reading an error as emptiness is how a half-finished migration looks finished — which is the
    reason this loop fails closed rather than tolerating the exception.

    Args:
      switched: The post-FR-001 builder.

    Returns:
      None.

    Raises:
      AssertionError: When the unreadable prefix passed.
    """
    s3 = FakeS3()

    def refuse(**kwargs):
        """Fails every listing the way a denied call would.

        Args:
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          RuntimeError: Always.
        """
        if kwargs.get("Delimiter"):
            return {"CommonPrefixes": [{"Prefix": "alice/"}], "Contents": [], "IsTruncated": False}
        raise RuntimeError("AccessDenied")

    s3.list_objects_v2 = refuse

    assert migrate.mode_prove_empty(clients(s3=s3), CONFIG) == 1


@contextlib.contextmanager
def captured_log():
    """Collects the module's own log lines for the duration of the block.

    The level is set explicitly: the module's logger inherits the root's default, which filters
    ``info`` before any handler sees it — so a handler alone captures nothing and every assertion
    over the output passes vacuously against an empty string.

    Args:
      None.

    Yields:
      The list the lines land in, filled as the block runs.

    Raises:
      None.
    """
    lines: list[str] = []

    class _Capture(logging.Handler):
        """Appends each formatted record to the list."""

        def emit(self, record):
            """Records one line.

            Args:
              record: The log record.

            Returns:
              None.

            Raises:
              None.
            """
            lines.append(record.getMessage())

    handler = _Capture()
    previous = migrate.logger.level
    migrate.logger.setLevel(logging.INFO)
    migrate.logger.addHandler(handler)
    try:
        yield lines
    finally:
        migrate.logger.removeHandler(handler)
        migrate.logger.setLevel(previous)


def test_an_oversize_copy_carries_the_metadata_a_single_copy_would_get_free(switched):
    """``UploadPartCopy`` moves bytes only, so the attributes come from the create or not at all.

    The regression this pins: the oversize path once opened its upload with the storage class alone,
    so a copied object arrived with no content type, no user metadata and no tags — and ``finish``
    then deleted the source, on buckets with versioning disabled. The single-copy path gets all
    three free at ``MetadataDirective=COPY``, which is what makes the multipart path easy to get
    wrong and impossible to notice from the ETag.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When any attribute failed to cross.
    """
    s3 = FakeS3()
    key = seed_space(s3, keys=("big.csv",))[0]
    s3.sizes[(USER_BUCKET, key)] = 6 * 1024 * 1024 * 1024
    s3.storage_class[(USER_BUCKET, key)] = "GLACIER_IR"
    s3.content_type[(USER_BUCKET, key)] = "text/csv"
    s3.metadata[(USER_BUCKET, key)] = {"owner": "alice"}
    s3.tags[(USER_BUCKET, key)] = [{"Key": "class", "Value": "restricted"}]

    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    moved = "alice/system_settings/athenaresults/big.csv"
    head = s3.head_object(Bucket=USER_BUCKET, Key=moved)
    assert head["StorageClass"] == "GLACIER_IR"
    assert head["ContentType"] == "text/csv"
    assert head["Metadata"] == {"owner": "alice"}
    assert s3.get_object_tagging(Bucket=USER_BUCKET, Key=moved)["TagSet"] == [
        {"Key": "class", "Value": "restricted"}
    ]


def test_finish_refuses_a_key_whose_destination_no_longer_matches_the_record(switched):
    """The destination re-verify is the guard against deleting the only copy of an object.

    Without it, a destination overwritten or truncated after the copy is deleted-from anyway: the
    source goes, the run exits 0, and the object exists nowhere. The source re-verify does not
    cover this — the source is untouched in this scenario, which is exactly why the two checks are
    separate and why this one needs its own scenario rather than riding on the other's.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the source was deleted despite a changed destination.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    destination = "alice/system_settings/athenaresults/q1/r.csv"
    s3.etags[(USER_BUCKET, destination)] = '"etag-overwritten-since-the-copy"'

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert exit_code == 1
    assert record is not None
    assert record["refused"] == [rid(key)]
    assert (USER_BUCKET, key) in s3.store


def test_finish_refuses_a_key_whose_destination_has_gone(switched):
    """A destination deleted after the copy leaves the source as the only copy, so it stays.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the source was deleted with no destination present.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    del s3.store[(USER_BUCKET, "alice/system_settings/athenaresults/q1/r.csv")]

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert exit_code == 1
    assert record is not None
    assert record["refused"] == [rid(key)]
    assert (USER_BUCKET, key) in s3.store


def test_keep_destination_lets_finish_delete_a_source_whose_recorded_etag_is_stale(switched):
    """The resolution is what finish reads, not the ETag — which is stale by definition.

    This is the conflict class the remedy is written for: a table re-shared AFTER the switch, whose
    destination has changed since it was recorded. Comparing the destination against the recorded
    ``copied_etag`` would refuse the one key an operator has already settled, leaving no route
    forward but overwriting the newer share.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the settled key was refused rather than deleted.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    destination = "alice/system_settings/athenaresults/q1/r.csv"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    s3.store[(USER_BUCKET, destination)] = b"re-shared after the switch"
    s3.etags[(USER_BUCKET, destination)] = '"etag-newer-share"'
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["conflicts"] == [rid(key)]

    migrate.mode_resolve(clients(s3=s3), CONFIG, "run-1", key, "destination")
    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    settled = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert settled is not None
    assert exit_code == 0
    assert settled["refused"] == []
    assert (USER_BUCKET, key) not in s3.store
    assert s3.store[(USER_BUCKET, destination)] == b"re-shared after the switch"


def test_the_record_is_persisted_before_the_run_ends(switched, monkeypatch):
    """A run the runner kills must leave a record a re-run extends, not one that starts over.

    Every unsaved key becomes a conflict on the re-run, and each conflict costs its own dispatch to
    settle, so the size of the unsaved tail is the size of the manual cleanup.

    Args:
      switched: The post-switch builder.
      monkeypatch: Used to shrink the persist interval to something a fixture can reach.

    Returns:
      None.

    Raises:
      AssertionError: When nothing was written before the final save.
    """
    monkeypatch.setattr(migrate, "RECORD_EVERY", 2)
    s3 = FakeS3()
    seed_space(s3, keys=("a.csv", "b.csv", "c.csv", "d.csv", "e.csv"))
    saves: list[int] = []
    real_save = migrate.save_record

    def counting_save(client, bucket, record):
        """Counts each persist and how many keys it carried.

        Args:
          client: The S3 client.
          bucket: The admin bucket.
          record: The record being written.

        Returns:
          None.

        Raises:
          None.
        """
        saves.append(len(record["keys"]))
        real_save(client, bucket, record)

    monkeypatch.setattr(migrate, "save_record", counting_save)
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    assert len(saves) > 1, "the record was written only once, so a killed run would lose everything"
    assert saves[0] < 5, "the first persist must land before every key is copied"


def test_the_effective_run_id_reaches_the_step_summary(switched, tmp_path):
    """An operator carries this id forward, so it must be the one this invocation actually used.

    Printing the ambient ``GITHUB_RUN_ID`` on a mode that was GIVEN a run id tells the operator to
    carry a value that opens a second record on the next copy, splitting one migration across two.

    Args:
      switched: The post-switch builder.
      tmp_path: A private summary file, never a fixed path — the suite runs on a checkout several
        sessions share, and a shared path is read by the wrong run.

    Returns:
      None.

    Raises:
      AssertionError: When the summary carries the wrong id.
    """
    summary = tmp_path / "summary.md"
    summary.write_text("", encoding="utf-8")
    environ = {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_RUN_ID": "ambient-999"}

    migrate.announce_run_id(environ, "carried-7", "finish")

    written = summary.read_text(encoding="utf-8")
    assert "carried-7" in written
    assert "ambient-999" not in written


def test_report_lists_the_records_four_registers(switched):
    """``report run_id`` is how an operator sees what still needs settling before finish.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When a register is missing from the output.
    """
    s3 = FakeS3()
    key = seed_space(s3)[0]
    s3.store[(USER_BUCKET, "alice/system_settings/athenaresults/q1/r.csv")] = b"other"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    with captured_log() as lines:
        migrate.mode_report(clients(s3=s3), CONFIG, "run-1")

    joined = "\n".join(lines)
    for register in ("conflicts", "oversize", "absent", "refused"):
        assert register in joined
    assert key in joined


def test_the_two_non_space_roots_are_not_treated_as_spaces(switched):
    """``_config/`` and ``_directory/`` hold no space, and reading them as one would refuse nothing.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When a non-space root was enumerated.
    """
    s3 = FakeS3()
    seed_space(s3)
    s3.store[(USER_BUCKET, "_config/settings.json")] = b"{}"
    s3.store[(USER_BUCKET, "_directory/users.json")] = b"[]"

    roots = [root for _, root in migrate.buckets_and_spaces(s3, CONFIG)]

    assert "alice/" in roots
    assert "_config/" not in roots
    assert "_directory/" not in roots


def test_verify_covers_every_storage_class_present(switched):
    """The attribute row that gates ``finish`` is read off this sample, so its shape is the claim.

    A sample that happened to hold only ``STANDARD`` objects would say nothing about the others,
    which is why every storage class present appears at least once.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When a storage class present in the record went unsampled.
    """
    s3 = FakeS3()
    keys = seed_space(s3, keys=tuple(f"q{n}.csv" for n in range(25)))
    for key in keys[:24]:
        s3.storage_class[(USER_BUCKET, key)] = "STANDARD"
    s3.storage_class[(USER_BUCKET, keys[24])] = "GLACIER_IR"
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    with captured_log() as lines:
        assert migrate.mode_verify(clients(s3=s3), CONFIG, "run-1") == 0

    joined = "\n".join(lines)
    assert "GLACIER_IR" in joined, "the one non-standard class in the record went unsampled"
    assert "source" in joined
    assert "destination" in joined


def test_the_table_input_allowlist_matches_botocores_own_model():
    """The allowlist is pinned against the service model, not against a reviewer's memory.

    A denylist here is the tempting shape and the wrong one: ``GetTable`` returns 24 members and
    ``TableInput`` accepts 14, so a denylist has to name 10 and goes stale the next time AWS adds a
    field. A rejected field raises ``ParamValidationError`` for the whole update — after the objects
    are copied and before the record is saved, which is the worst moment in the run to raise.

    The unconditional half is a floor that holds with no AWS libraries present; the model check is
    the real assertion and is skipped loudly rather than silently when botocore is absent.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the allowlist drifts from what Glue accepts.
    """
    assert len(migrate.TABLE_INPUT_FIELDS) == 14
    assert "Status" not in migrate.TABLE_INPUT_FIELDS
    assert "DatabaseName" not in migrate.TABLE_INPUT_FIELDS

    boto3 = pytest.importorskip("boto3", reason="botocore absent; the model pin cannot run here")
    model = boto3.client("glue", region_name="us-east-1").meta.service_model
    assert set(migrate.TABLE_INPUT_FIELDS) == set(model.shape_for("TableInput").members)


def test_a_repointed_definition_carries_no_field_the_input_rejects(switched):
    """The end-to-end check: what ``repoint_table`` actually sends is what Glue accepts.

    The fake accepts any ``TableInput``, so a shape assertion against the fake alone would pass on
    a payload the real service refuses. This asserts the payload against the allowlist that is
    itself pinned to the service model.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When a read-only member survived into the update.
    """
    s3 = FakeS3()
    glue = FakeGlue()
    seed_space(s3, folder="shared_tables", keys=("sales/part.parquet",))
    seed_table(glue)
    glue.definitions[("alice", "sales")].update(
        {
            "DatabaseName": "alice",
            "CreateTime": "2026-01-01",
            "Status": {"State": "SUCCEEDED"},
            "IsMultiDialectView": False,
            "FederatedTable": {"Identifier": "x"},
            "VersionId": "3",
        }
    )

    migrate.mode_copy(clients(s3=s3, glue=glue), CONFIG, "run-1")

    sent = glue.definitions[("alice", "sales")]
    rejected = set(sent) - set(migrate.TABLE_INPUT_FIELDS)
    assert rejected == set(), f"TableInput would reject: {sorted(rejected)}"
    assert sent["StorageDescriptor"]["Location"] == (
        f"s3://{USER_BUCKET}/alice/system_settings/shared_tables/sales/"
    )


def test_two_spaces_of_the_same_name_in_different_buckets_do_not_collapse(switched):
    """A user ``alice`` and a shared space ``alice`` can both exist, and both hold the same key.

    Nothing checks a proposed shared-space name against the User Pool, so the two namespaces meet
    here. Keyed by the S3 key alone their records collapse into one entry: the ETag re-verify then
    refuses one of them, so no data is lost, but a source IS deleted while the run reports it was
    not — a wrong audit trail on the one mode that cannot be undone.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the two objects shared a record entry, or one survived unrecorded.
    """
    s3 = FakeS3()
    seed_space(s3, bucket=USER_BUCKET, space="team/")
    seed_space(s3, bucket=SHARED_BUCKET, space="team/")

    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert len(record["keys"]) == 2, "the two buckets' identically-named keys collapsed into one"
    assert set(record["keys"]) == {
        rid("team/athenaresults/q1/r.csv", USER_BUCKET),
        rid("team/athenaresults/q1/r.csv", SHARED_BUCKET),
    }

    exit_code = migrate.mode_finish(clients(s3=s3), CONFIG, "run-1")

    settled = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert settled is not None
    assert exit_code == 0
    assert settled["refused"] == []
    assert (USER_BUCKET, "team/athenaresults/q1/r.csv") not in s3.store
    assert (SHARED_BUCKET, "team/athenaresults/q1/r.csv") not in s3.store
    assert (USER_BUCKET, "team/system_settings/athenaresults/q1/r.csv") in s3.store
    assert (SHARED_BUCKET, "team/system_settings/athenaresults/q1/r.csv") in s3.store


def test_a_record_that_is_not_json_is_refused_by_name(switched):
    """A run cut off mid-write leaves bytes that are not a record, and that must say so.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    s3 = FakeS3()
    s3.store[(ADMIN_BUCKET, migrate.record_key("run-1"))] = b'{"run_id": "run-1", "keys": {'

    with pytest.raises(migrate.Refusal) as caught:
        migrate.load_record(s3, ADMIN_BUCKET, "run-1")

    assert caught.value.code == "record_unreadable"


def test_a_record_missing_a_register_is_refused_by_name(switched):
    """A hand-edited record that dropped a field must not fail deep inside whichever mode reads it.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    s3 = FakeS3()
    s3.store[(ADMIN_BUCKET, migrate.record_key("run-1"))] = json.dumps(
        {"run_id": "run-1", "started": "now", "keys": {}}
    ).encode("utf-8")

    with pytest.raises(migrate.Refusal) as caught:
        migrate.load_record(s3, ADMIN_BUCKET, "run-1")

    assert caught.value.code == "record_incomplete"
    assert "conflicts" in str(caught.value)


@pytest.mark.parametrize(
    ("location", "space_root"),
    [
        ("s3://buck/bob/shared_tables/alice/shared_tables/t/", "alice/"),
        ("s3://buck/xyz/a/shared_tables/t/", "a/"),
        ("s3://buck//alice/shared_tables/t1/", "alice/"),
    ],
    ids=["marker appears deeper", "one-character space name", "double slash after the bucket"],
)
def test_a_location_whose_marker_is_not_at_the_start_is_refused(location, space_root):
    """The guard is a PREFIX test on the path, never a substring test on the URI.

    A substring test accepts each of these and the slice below it then produces a plausible-looking
    destination that is simply wrong — ``.../system_settings/shared_tables/ice/shared_tables/t/``
    for the first. That is the highest-severity class in this module: nothing refuses, the copy
    lands somewhere nobody looks, and ``finish`` deletes the source afterwards. The two tests
    disagree only on inputs like these, which is why they are the fixture.

    Args:
      location: A location whose old-prefix marker is present but not at the start of the path.
      space_root: The space the table belongs to.

    Returns:
      None.

    Raises:
      AssertionError: When the malformed location was accepted.
    """
    with pytest.raises(migrate.Refusal) as caught:
        migrate.migrated_location(location, space_root)
    assert caught.value.code == "location_not_migrated"


def test_verify_handles_a_bucket_holding_more_than_one_space(switched):
    """The user-space bucket holds one prefix per user, so a single-space fixture proves nothing.

    The sample is scoped to a BUCKET and a bucket holds many spaces. A sampled key carried without
    the root it was found under is paired with whichever root the loop is on, maps to a destination
    in another space, and is then refused by ``folder_of`` — taking the whole mode down on the
    second space of any real bucket, with a code that reads like a safety refusal rather than a bug.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When verify refused, or reported a key against the wrong space.
    """
    s3 = FakeS3()
    seed_space(s3, space="alice/", keys=("q1.csv",))
    seed_space(s3, space="bob/", keys=("q2.csv",))
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")

    with captured_log() as lines:
        assert migrate.mode_verify(clients(s3=s3), CONFIG, "run-1") == 0

    joined = "\n".join(lines)
    assert "alice/athenaresults/q1.csv" in joined
    assert "bob/athenaresults/q2.csv" in joined


def test_verify_always_samples_an_oversize_key(switched):
    """The multipart path is the one place these attributes can be silently lost.

    ``record["oversize"]`` names exactly the keys that went through it, and the human gate for that
    is this sample — so a sample that happened to miss every one of them would be read as evidence
    about a path it never looked at.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the oversize key went unsampled.
    """
    s3 = FakeS3()
    ordinary = seed_space(s3, keys=tuple(f"q{n}.csv" for n in range(30)))
    big = seed_space(s3, keys=("zzz-big.csv",))[0]
    s3.sizes[(USER_BUCKET, big)] = 6 * 1024 * 1024 * 1024
    migrate.mode_copy(clients(s3=s3), CONFIG, "run-1")
    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["oversize"] == [rid(big)]

    with captured_log() as lines:
        assert migrate.mode_verify(clients(s3=s3), CONFIG, "run-1") == 0

    joined = "\n".join(lines)
    assert big in joined, "the oversize key sorts last and would fall outside a plain head-20 sample"
    assert len(ordinary) == 30


def test_a_record_that_is_a_json_scalar_is_refused_by_name(switched):
    """``field not in None`` raises a TypeError, which is the class the named refusals replaced.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is missing or carries another code.
    """
    s3 = FakeS3()
    s3.store[(ADMIN_BUCKET, migrate.record_key("run-1"))] = b"null"

    with pytest.raises(migrate.Refusal) as caught:
        migrate.load_record(s3, ADMIN_BUCKET, "run-1")

    assert caught.value.code == "record_unreadable"


def test_a_denied_tag_read_is_not_silently_an_empty_tag_set(switched):
    """A denial and an absence answer the same shape, and only one of them means "no tags".

    Reading a denial as absence would open the multipart upload with no tags, strip a tagged object,
    and let ``finish`` delete the source — on buckets with versioning disabled.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When the denial was swallowed.
    """
    s3 = FakeS3()
    key = seed_space(s3, keys=("big.csv",))[0]
    s3.sizes[(USER_BUCKET, key)] = 6 * 1024 * 1024 * 1024

    def denied(**kwargs):
        """Refuses every tag read the way a denied call does.

        Args:
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          FakeClientError: Always, with AccessDenied.
        """
        raise FakeClientError("AccessDenied")

    s3.get_object_tagging = denied

    with pytest.raises(FakeClientError):
        migrate.source_attributes(s3, USER_BUCKET, key)


def realistic_account(s3, glue):
    """Seeds the topology production actually has, rather than the one a scenario needs.

    Three rounds of review each found a defect that a narrower fixture could not reach: a bucket
    holding one space where production holds hundreds, one storage class where several exist, one
    bucket where there are two, and no oversize object where the multipart path is the one that
    loses attributes. Each was closed with a scenario aimed at it — but the shape kept recurring,
    which makes the fixture the problem rather than any one test.

    So this seeds all of it at once: two buckets, several spaces per bucket, a name that exists in
    BOTH, mixed storage classes, user metadata and tags, an object past the multipart threshold, a
    shared table to re-point, and ordinary user files that must be left alone.

    Args:
      s3: The S3 fake.
      glue: The Glue fake.

    Returns:
      The keys that must survive the migration untouched.

    Raises:
      None.
    """
    for space in ("alice/", "alicia/", "bob/", "team/"):
        seed_space(s3, bucket=USER_BUCKET, space=space, keys=("q1.csv", "q2.csv"))
        s3.store[(USER_BUCKET, f"{space}notes/keep.txt")] = b"an ordinary user file"
        s3.store[(USER_BUCKET, f"{space}user_settings/theme.json")] = b"{}"
    seed_space(s3, bucket=USER_BUCKET, space="alice/", folder="archive", keys=("r1/receipt.txt",))
    big = seed_space(s3, bucket=USER_BUCKET, space="bob/", keys=("huge.csv",))[0]
    s3.sizes[(USER_BUCKET, big)] = 6 * 1024 * 1024 * 1024
    s3.storage_class[(USER_BUCKET, big)] = "GLACIER_IR"
    s3.content_type[(USER_BUCKET, big)] = "text/csv"
    s3.metadata[(USER_BUCKET, big)] = {"owner": "bob"}
    s3.tags[(USER_BUCKET, big)] = [{"Key": "class", "Value": "restricted"}]

    for space in ("team/", "finance/"):
        seed_space(s3, bucket=SHARED_BUCKET, space=space, folder="shared_tables", keys=("t/p.parquet",))
        s3.store[(SHARED_BUCKET, f"{space}notes/keep.txt")] = b"an ordinary shared file"
    seed_table(glue, database="finance", name="t", location=f"s3://{SHARED_BUCKET}/finance/shared_tables/t/")

    s3.store[(USER_BUCKET, "_config/settings.json")] = b"{}"
    s3.store[(USER_BUCKET, "_directory/users.json")] = b"[]"
    return [
        (USER_BUCKET, "alice/notes/keep.txt"),
        (USER_BUCKET, "alice/user_settings/theme.json"),
        (USER_BUCKET, "_config/settings.json"),
        (USER_BUCKET, "_directory/users.json"),
        (SHARED_BUCKET, "team/notes/keep.txt"),
    ]


def test_the_whole_sequence_against_the_topology_production_actually_has(switched):
    """report, copy, verify, finish and prove-empty, end to end, on a realistic account.

    This is the structural answer to a class of defect that recurred across three review rounds
    rather than to any one instance of it: every mode runs against two buckets, several spaces, a
    name that exists in both, mixed storage classes and an oversize object, so a mode that only
    works on the first space of the first bucket cannot pass.

    Args:
      switched: The post-switch builder.

    Returns:
      None.

    Raises:
      AssertionError: When any mode refused, an untouched file moved, or a prefix survived.
    """
    s3 = FakeS3()
    glue = FakeGlue()
    untouched = realistic_account(s3, glue)
    bundle = clients(s3=s3, glue=glue)

    assert migrate.mode_report(bundle, CONFIG, None) == 0
    assert migrate.mode_copy(bundle, CONFIG, "run-1") == 0
    assert migrate.mode_verify(bundle, CONFIG, "run-1") == 0
    assert migrate.mode_prove_empty(bundle, CONFIG) == 1
    assert migrate.mode_finish(bundle, CONFIG, "run-1") == 0
    assert migrate.mode_prove_empty(bundle, CONFIG) == 0

    record = migrate.load_record(s3, ADMIN_BUCKET, "run-1")
    assert record is not None
    assert record["refused"] == []
    assert record["conflicts"] == []

    for bucket, key in untouched:
        assert (bucket, key) in s3.store, f"{key} is not the migration's business"

    moved = "bob/system_settings/athenaresults/huge.csv"
    head = s3.head_object(Bucket=USER_BUCKET, Key=moved)
    assert head["StorageClass"] == "GLACIER_IR"
    assert head["Metadata"] == {"owner": "bob"}
    assert s3.get_object_tagging(Bucket=USER_BUCKET, Key=moved)["TagSet"] == [
        {"Key": "class", "Value": "restricted"}
    ]
    assert glue.get_table(DatabaseName="finance", Name="t")["Table"]["StorageDescriptor"][
        "Location"
    ] == f"s3://{SHARED_BUCKET}/finance/system_settings/shared_tables/t/"


def test_the_allowlist_agrees_with_the_fleets_own_copy():
    """Two copies of one fact drift, so the second copy is pinned to the first rather than trusted.

    The refresh verb carries the same list and nothing pinned the two together; this module's copy
    is pinned to botocore's service model, so tying them makes the fleet's copy detectable too.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two copies have drifted.
    """
    sys.path.insert(0, str(LAMBDAS / "table-builder-apply-refresh"))
    import apply_refresh

    assert migrate.TABLE_INPUT_FIELDS == apply_refresh._TABLE_INPUT_FIELDS
