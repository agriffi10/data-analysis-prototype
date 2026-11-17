"""Moves the three app-managed folders into ``system_settings/``, once, under the deploy role.

This is the step between two merges. The first merge switches where new writes go; this
module copies what is already there and, after every live check has passed, deletes the sources; the
second merge then removes the old home's fences.

**It moves OBJECTS and nothing else.** ``shared_tables/`` does not move — the tables in it were sent
to this space and are the user's to edit, which is the opposite of what the app-managed folder
means — so no Glue ``LOCATION`` points anywhere this migration changes, and there is no catalog
work, no Lake Formation probe and no ``UpdateTable``. That is the whole reason this module talks to
S3 alone. It is a runner script rather than a fleet function
because the deploy role already holds ``s3:*`` on both space buckets, is a Lake Formation data-lake
admin, and is named in the user-space bucket-policy allowlist — a new function would need a role the
allowlist does not name, and its first ``CopyObject`` would be ``AccessDenied`` behind a green apply.

**It refuses to run before the switch has landed.** Merging this module puts a destructive one-shot
on ``main`` two merges before it may safely run, and the workflow's main-only step does not bound
*when*. So every mode that writes asks the builder where a write goes today: while
``app_managed_prefix`` still resolves to depth one, ``copy`` would copy objects the fleet is actively
still writing and ``finish`` would then delete live sources, which is the loss the two-merge shape
exists to prevent. That check reads the runner's checkout, not the deployed image, so it does not
prove the fleet has the new code — ``Deploy Lambdas`` green on the switch sha is what covers that.

**The refusals here are correctness guards on this script, not authorization boundaries.** IAM does
not bound the module — the deploy role can reach every key in both buckets — so ``outside_migration_scope``
and ``location_not_migrated`` exist to stop this script touching what it has no business touching.
They deny nobody who reaches the role another way, and reading them as a fence would leave the next
author believing a bound exists where none does.

**Why a destination is never compared to its source by ETag.** A multipart source carries an
``…-N`` ETag that a single ``CopyObject`` never reproduces, so "already copied" means exactly
*destination ETag equals the ``copied_etag`` this run recorded*. A destination that exists with no
record, or with a different ETag, is a conflict for an operator to resolve.

Attributes:
  ROOT: The repository root, used for the layer import and nothing else.
  MODES: The six modes, in the order an operator runs them.
  RECORD_PREFIX: Where the copy record lives in the admin bucket. No lifecycle rule expires it.
  RECORD_EVERY: How many recorded keys between persists, so a run the runner cuts off leaves a
    record a re-run extends rather than starting over.
  MULTIPART_THRESHOLD: The size above which ``CopyObject`` is refused by S3 and ``UploadPartCopy``
    is used instead — 5 GiB, the service limit.
  PART_SIZE: The part size for an oversize copy.
  DELETE_BATCH: The most keys one ``DeleteObjects`` may carry, per the S3 API.
  VERIFY_SAMPLE: How many recorded keys per bucket ``verify`` reads back by default.
  SKIPPED_ROOTS: The user-space bucket's non-space prefixes. Neither holds a space.
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import pathlib
import sys
import urllib.parse
from typing import Any, Literal, TypedDict, cast

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas" / "control-plane-common"))

from cpcommon.app_managed import (
    MOVING_FOLDERS,
    app_managed_prefix,
    app_managed_prefixes,
)
from cpcommon.errors import error_code

logger = logging.getLogger("migrate_system_settings")

Mode = Literal["report", "copy", "resolve", "verify", "finish", "prove-empty"]

MODES: tuple[str, ...] = ("report", "copy", "resolve", "verify", "finish", "prove-empty")

RECORD_PREFIX = "migration/system-settings/"
RECORD_EVERY = 500
MULTIPART_THRESHOLD = 5 * 1024 * 1024 * 1024
PART_SIZE = 1024 * 1024 * 1024
DELETE_BATCH = 1000
VERIFY_SAMPLE = 20
SKIPPED_ROOTS = ("_config/", "_directory/")


class Recorded(TypedDict):
    """One source key's record, written by ``copy`` and read by every later mode.

    Attributes:
      source_etag: The source's ETag when it was copied.
      source_last_modified: The source's ``LastModified``, ISO-8601.
      copied_etag: The ``CopyObjectResult.ETag`` the copy returned, or the destination's own
        ``HeadObject`` ETag for a key the copy skipped because the destination already existed.
        This is what ``finish`` re-verifies the destination against.
      resolution: Empty, or which side an operator kept when the key was a conflict.
    """

    source_etag: str
    source_last_modified: str
    copied_etag: str
    resolution: Literal["", "keep-source", "keep-destination"]


class Record(TypedDict):
    """The persisted state of one migration run.

    Attributes:
      run_id: The workflow run's ``GITHUB_RUN_ID``, echoed to the step summary so an operator can
        pass it to every later mode.
      started: When ``copy`` first wrote this record, ISO-8601.
      keys: Per source key, what was copied.
      conflicts: Source keys whose destination exists and does not match the record.
      oversize: Keys copied in parts rather than in one call.
      oversize_done: Which of those finished, informational.
      absent: Filled by ``finish`` — sources already gone before deletion.
      refused: Filled by ``finish`` — a HEAD or a delete that no longer matched the record.
    """

    run_id: str
    started: str
    keys: dict[str, Recorded]
    conflicts: list[str]
    oversize: list[str]
    oversize_done: list[str]
    absent: list[str]
    refused: list[str]


class Refusal(Exception):
    """A refusal this module raises rather than doing something outside its remit.

    Carries a named code so a caller and a test can tell which refusal fired; the neighbouring
    path usually returns the same kind of error, which is what makes a code-less refusal untestable.

    Attributes:
      code: The refusal's name.
    """

    def __init__(self, code: str, detail: str) -> None:
        """Records the code and a human-readable detail.

        Args:
          code: The refusal's name, asserted by tests.
          detail: What was refused, for the operator reading the log.

        Returns:
          None.

        Raises:
          None.
        """
        super().__init__(f"{code}: {detail}")
        self.code = code


def switch_has_landed() -> bool:
    """Reports whether the write switch is in the checkout this script is running from.

    Asks the builder where a write goes today rather than reading a version or a flag, because the
    builder is the thing the switch actually changes.

    Asked as "has the write path moved AWAY from the old home", which needs no literal: the
    plural builder's first element is the old home by definition, and the sweep refuses a
    constructed prefix outside the owner module — correctly, since a spelled ``system_settings/``
    here would be a second place the name lives.

    Args:
      None.

    Returns:
      True once the singular builder no longer answers the old home.

    Raises:
      Refusal: ``narrowing_already_merged``, from ``old_prefix``, once the plural has been shrunk.
        Every mode is done by then, and a predicate that quietly said "not landed" at that point
        would refuse the whole module for the opposite of the real reason.
    """
    root, folder = "probe/", MOVING_FOLDERS[0]
    return app_managed_prefix(root, folder) != old_prefix(root, folder)


def require_switch(mode: str) -> None:
    """Refuses a writing mode while the checkout still writes to the old home.

    Args:
      mode: The mode about to run.

    Returns:
      None.

    Raises:
      Refusal: ``switch_not_landed`` when the builder still resolves to depth one.
    """
    if not switch_has_landed():
        raise Refusal(
            "switch_not_landed",
            f"{mode} needs the write switch merged first — app_managed_prefix still resolves to "
            "depth one, so the fleet is still writing to the old home",
        )


def old_prefix(space_root: str, folder: str) -> str:
    """Builds a moving folder's OLD location under a space root.

    Reads the plural builder's first element rather than spelling the path, because the sweep
    refuses a construction outside the owner and because the old home is what the plural knows.

    Args:
      space_root: The space root, trailing slash.
      folder: One of the moving folders.

    Returns:
      The depth-one prefix.

    Raises:
      Refusal: ``narrowing_already_merged`` when the plural has been shrunk to one element, which
        means the old home is no longer addressable and every answer about it would be about the
        new one.
    """
    homes = app_managed_prefixes(space_root, folder)
    if len(homes) < 2:
        raise Refusal(
            "narrowing_already_merged",
            f"app_managed_prefixes({folder!r}) returned {len(homes)} element(s); the old home is "
            "no longer addressable, so this run would answer about the new home instead",
        )
    return homes[0]


def new_prefix(space_root: str, folder: str) -> str:
    """Builds a moving folder's NEW location under a space root.

    Args:
      space_root: The space root, trailing slash.
      folder: One of the moving folders.

    Returns:
      The depth-two prefix.

    Raises:
      None.
    """
    return app_managed_prefix(space_root, folder)


def folder_of(key: str, space_root: str) -> str:
    """Names which moving folder a source key sits under, refusing anything else.

    Args:
      key: The object key.
      space_root: The space root the key was listed under.

    Returns:
      The moving folder's name.

    Raises:
      Refusal: ``outside_migration_scope`` when the key is under none of the three old prefixes.
    """
    for folder in MOVING_FOLDERS:
        if key.startswith(old_prefix(space_root, folder)):
            return folder
    raise Refusal("outside_migration_scope", key)


def destination_of(key: str, space_root: str) -> str:
    """Maps a source key to its key at the new home.

    Args:
      key: The source key, already in scope.
      space_root: The space root.

    Returns:
      The destination key.

    Raises:
      Refusal: ``outside_migration_scope`` when the key is not under a migrated prefix.
    """
    folder = folder_of(key, space_root)
    return new_prefix(space_root, folder) + key[len(old_prefix(space_root, folder)) :]


def supports_conditional_delete(s3: Any) -> bool:
    """Reports whether this runtime can send a per-object ETag on ``DeleteObjects``.

    Read off the live service model rather than a version string, for the reason
    ``focommon.delete`` records: a botocore whose ``ObjectIdentifier`` shape lacks the member
    raises ``ParamValidationError`` for the WHOLE request rather than a per-item error, and the
    runner's botocore is not the Lambda runtime's. Sending it is belt — the head re-verify is the
    guard ``finish`` actually relies on.

    Args:
      s3: The S3 client.

    Returns:
      True when ``ObjectIdentifier`` carries an ``ETag`` member.

    Raises:
      None. A client that cannot be introspected reports False, taking the path that works
      everywhere.
    """
    try:
        shape = s3.meta.service_model.shape_for("ObjectIdentifier")
    except Exception:  # noqa: BLE001 - an unintrospectable client takes the path that always works
        return False
    return bool("ETag" in shape.members)


def spaces(s3: Any, bucket: str, skip: tuple[str, ...] = ()) -> list[str]:
    """Lists a bucket's space roots.

    Args:
      s3: The S3 client.
      bucket: The bucket to enumerate.
      skip: Root prefixes that hold no space.

    Returns:
      The space roots, each with its trailing slash, sorted.

    Raises:
      None.
    """
    roots: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": "", "Delimiter": "/"}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = cast("dict[str, Any]", s3.list_objects_v2(**kwargs))
        for entry in page.get("CommonPrefixes", []):
            prefix = cast("str", entry["Prefix"])
            if prefix not in skip:
                roots.append(prefix)
        if not page.get("IsTruncated"):
            break
        token = cast("str", page["NextContinuationToken"])
    return sorted(roots)


def objects_under(s3: Any, bucket: str, prefix: str) -> list[dict[str, Any]]:
    """Lists every object under a prefix, following continuation tokens.

    Args:
      s3: The S3 client.
      bucket: The bucket.
      prefix: The prefix to list.

    Returns:
      The objects, each as S3 returned it.

    Raises:
      None.
    """
    found: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token is not None:
            kwargs["ContinuationToken"] = token
        page = cast("dict[str, Any]", s3.list_objects_v2(**kwargs))
        found.extend(cast("list[dict[str, Any]]", page.get("Contents", [])))
        if not page.get("IsTruncated"):
            break
        token = cast("str", page["NextContinuationToken"])
    return found


def empty_record(run_id: str) -> Record:
    """Builds a fresh record for a run.

    Args:
      run_id: The workflow run id.

    Returns:
      An empty record stamped with the current time.

    Raises:
      None.
    """
    return Record(
        run_id=run_id,
        started=datetime.datetime.now(tz=datetime.UTC).isoformat(),
        keys={},
        conflicts=[],
        oversize=[],
        oversize_done=[],
        absent=[],
        refused=[],
    )


def recorded_id(bucket: str, key: str) -> str:
    """Names one object in the record, unambiguously across both space buckets.

    A space name is unique WITHIN a bucket and not across the two — sign-up does not consult the
    shared-space registry, so a user ``alice`` and a shared space ``alice`` can both exist, and
    each may hold ``alice/athenaresults/q1.csv``. Keyed by the S3 key alone the two collapse into
    one entry: the ETag re-verify then refuses one of them, so nothing is lost, but a source IS
    deleted while the run reports it was not. On the one mode that cannot be undone, an audit trail
    that disagrees with what happened is its own defect. The archive plane reached the same
    conclusion where the two namespaces first met, and added a leading segment for it.

    Args:
      bucket: The bucket the object is in.
      key: The object key.

    Returns:
      The record's identifier for that object.

    Raises:
      None.
    """
    return f"{bucket}|{key}"


def recorded_key(identifier: str) -> str:
    """Recovers the S3 key from a record identifier.

    Args:
      identifier: An identifier from ``recorded_id``.

    Returns:
      The object key.

    Raises:
      None.
    """
    return identifier.partition("|")[2]


def record_key(run_id: str) -> str:
    """Names the record's object key.

    Args:
      run_id: The workflow run id.

    Returns:
      The key under the admin bucket.

    Raises:
      None.
    """
    return f"{RECORD_PREFIX}{run_id}.json"


def load_record(s3: Any, admin_bucket: str, run_id: str) -> Record | None:
    """Reads a run's record, or None when it has none yet.

    Args:
      s3: The S3 client.
      admin_bucket: The admin bucket.
      run_id: The workflow run id.

    Returns:
      The record, or None when the run has none yet.

    Raises:
      Refusal: ``record_unreadable`` when the stored document is not JSON, and
        ``record_incomplete`` when it is JSON but lacks a field every later mode reads. A run cut
        off mid-write, or a record hand-edited to settle something, otherwise surfaces as a
        ``JSONDecodeError`` or a ``KeyError`` from deep inside whichever mode touched the missing
        field first — fail-closed either way, but saying nothing about which mode to re-run.
    """
    try:
        response = cast("dict[str, Any]", s3.get_object(Bucket=admin_bucket, Key=record_key(run_id)))
    except s3.exceptions.NoSuchKey:
        return None
    try:
        loaded = json.loads(response["Body"].read())
    except ValueError as error:
        raise Refusal("record_unreadable", f"{run_id}: {error}") from error
    if not isinstance(loaded, dict):
        raise Refusal("record_unreadable", f"{run_id}: the stored record is not an object")
    missing = [field for field in Record.__annotations__ if field not in loaded]
    if missing:
        raise Refusal("record_incomplete", f"{run_id} is missing {', '.join(missing)}")
    return cast("Record", loaded)


def save_record(s3: Any, admin_bucket: str, record: Record) -> None:
    """Persists a run's record.

    Called every ``RECORD_EVERY`` keys as well as at the end, so a run the runner cuts off leaves
    a record a re-run extends rather than one that has to start over.

    Args:
      s3: The S3 client.
      admin_bucket: The admin bucket.
      record: The record to write.

    Returns:
      None.

    Raises:
      None.
    """
    s3.put_object(
        Bucket=admin_bucket,
        Key=record_key(record["run_id"]),
        Body=json.dumps(record, indent=2).encode("utf-8"),
    )


def running_executions(sfn: Any, machine_arn: str) -> list[str]:
    """Names any execution of one state machine that has not finished.

    Args:
      sfn: The Step Functions client.
      machine_arn: The state machine to ask about.

    Returns:
      The ARNs of executions still ``RUNNING``.

    Raises:
      None.
    """
    running: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"stateMachineArn": machine_arn, "statusFilter": "RUNNING"}
        if token is not None:
            kwargs["nextToken"] = token
        page = cast("dict[str, Any]", sfn.list_executions(**kwargs))
        running.extend(
            cast("str", item["executionArn"]) for item in page.get("executions", [])
        )
        token = cast("str | None", page.get("nextToken"))
        if token is None:
            break
    return running


def unfinished_queries(athena: Any, workgroup: str) -> list[str]:
    """Names any query in the workgroup that has not reached a terminal state.

    ``ListQueryExecutions`` returns the last 45 days newest first, so the first page holds anything
    that could still be running; the walk stops as soon as a page is entirely terminal.

    Args:
      athena: The Athena client.
      workgroup: The one workgroup every space's queries run in.

    Returns:
      The ids of executions still ``QUEUED`` or ``RUNNING``.

    Raises:
      None.
    """
    unfinished: list[str] = []
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"WorkGroup": workgroup}
        if token is not None:
            kwargs["NextToken"] = token
        page = cast("dict[str, Any]", athena.list_query_executions(**kwargs))
        ids = cast("list[str]", page.get("QueryExecutionIds", []))
        if not ids:
            break
        detail = cast(
            "dict[str, Any]", athena.batch_get_query_execution(QueryExecutionIds=ids)
        )
        states = [
            (
                cast("str", item["QueryExecutionId"]),
                cast("str", item["Status"]["State"]),
            )
            for item in detail.get("QueryExecutions", [])
        ]
        unfinished.extend(qid for qid, state in states if state in ("QUEUED", "RUNNING"))
        if all(state not in ("QUEUED", "RUNNING") for _, state in states):
            break
        token = cast("str | None", page.get("NextToken"))
        if token is None:
            break
    return unfinished


def check_preconditions(clients: dict[str, Any], config: dict[str, str]) -> None:
    """Refuses to start a copy while work that would race it is still in flight.

    Each of the three is a write that computes its destination at validate time and lands it
    later: a restore computes its receipt key and rewrites it hours afterwards, a share computes
    its ``destPrefix`` and writes both data and a ``LOCATION`` later, and a query started before
    the switch lands its CSV at the old location minutes later. The remedy is to wait — a restore
    is 3 to 5 hours — and re-dispatch.

    Args:
      clients: The ``sfn`` and ``athena`` clients.
      config: The two state-machine ARNs and the workgroup name.

    Returns:
      None.

    Raises:
      Refusal: ``precondition_in_flight``, naming every execution that must finish first.
    """
    blocking: list[str] = []
    for label, arn in (
        ("archive", config["archive_state_machine_arn"]),
        ("table-share", config["table_share_state_machine_arn"]),
    ):
        blocking.extend(
            f"{label} execution {execution}"
            for execution in running_executions(clients["sfn"], arn)
        )
    blocking.extend(
        f"athena execution {qid}"
        for qid in unfinished_queries(clients["athena"], config["workgroup"])
    )
    if blocking:
        raise Refusal("precondition_in_flight", "; ".join(blocking))


def copy_one(
    s3: Any, bucket: str, source_key: str, destination_key: str, listed: dict[str, Any]
) -> str:
    """Copies one object to its new home, preserving what S3 will not preserve by default.

    ``StorageClass`` is passed explicitly because a ``CopyObject`` that omits it lands the copy in
    ``STANDARD`` whatever the source was. ``MetadataDirective`` and ``TaggingDirective`` are passed
    at ``COPY`` rather than left to default, so a test can assert them: naming ``ContentType`` would
    force ``REPLACE`` and drop the user metadata this is trying to keep.

    Args:
      s3: The S3 client.
      bucket: The bucket both keys live in.
      source_key: The key to copy from.
      destination_key: The key to copy to.
      listed: The object as ``list_objects_v2`` returned it, for its size and storage class.

    Returns:
      The ``CopyObjectResult.ETag`` the copy reported.

    Raises:
      None.
    """
    storage_class = cast("str", listed.get("StorageClass", "STANDARD"))
    size = cast("int", listed.get("Size", 0))
    if size > MULTIPART_THRESHOLD:
        return copy_in_parts(s3, bucket, source_key, destination_key, size, storage_class)
    response = cast(
        "dict[str, Any]",
        s3.copy_object(
            Bucket=bucket,
            Key=destination_key,
            CopySource={"Bucket": bucket, "Key": source_key},
            StorageClass=storage_class,
            MetadataDirective="COPY",
            TaggingDirective="COPY",
        ),
    )
    return cast("str", response["CopyObjectResult"]["ETag"])


def source_attributes(s3: Any, bucket: str, key: str) -> dict[str, Any]:
    """Reads the attributes a multipart copy has to carry across by hand.

    ``UploadPartCopy`` moves BYTES and nothing else, and there is no ``MetadataDirective`` for a
    multipart copy: whatever ``CreateMultipartUpload`` is given is what the destination ends up
    with. So the content type, the user metadata and the tag set are read from the source here and
    passed there explicitly. A single ``CopyObject`` gets all three free at ``COPY``, which is what
    makes this path so easy to get wrong — and the loss is unrecoverable, since both space buckets
    have versioning disabled and ``finish`` deletes the source afterwards.

    Args:
      s3: The S3 client.
      bucket: The bucket the source is in.
      key: The source key.

    Returns:
      ``ContentType``, ``Metadata`` and a URL-encoded ``Tagging`` string, ready to be splatted into
      ``create_multipart_upload``. An absent source yields empty values rather than raising; the
      copy that follows fails on the missing source and says so.

    Raises:
      None.
    """
    head = head_or_none(s3, bucket, key) or {}
    try:
        tag_set = cast(
            "list[dict[str, str]]",
            cast("dict[str, Any]", s3.get_object_tagging(Bucket=bucket, Key=key))["TagSet"],
        )
    except Exception as error:
        if error_code(error) not in ("404", "NoSuchKey", "NotFound"):
            raise
        tag_set = []
    return {
        "ContentType": head.get("ContentType", "binary/octet-stream"),
        "Metadata": dict(cast("dict[str, str]", head.get("Metadata", {}))),
        "Tagging": urllib.parse.urlencode({t["Key"]: t["Value"] for t in tag_set}),
    }


def copy_in_parts(
    s3: Any, bucket: str, source_key: str, destination_key: str, size: int, storage_class: str
) -> str:
    """Copies an object too large for a single ``CopyObject``.

    S3 refuses ``CopyObject`` above 5 GiB, so the object is copied in ranged parts. It is listed
    under ``oversize`` for the record rather than refused, because a large result set is ordinary.

    **The attributes a single copy preserves for free are carried by hand here.** ``UploadPartCopy``
    moves bytes only, so the content type, user metadata and tags come from the
    ``CreateMultipartUpload`` request or not at all — see ``source_attributes``.

    Args:
      s3: The S3 client.
      bucket: The bucket both keys live in.
      source_key: The key to copy from.
      destination_key: The key to copy to.
      size: The source's size in bytes.
      storage_class: The source's storage class.

    Returns:
      The completed object's ETag.

    Raises:
      None.
    """
    created = cast(
        "dict[str, Any]",
        s3.create_multipart_upload(
            Bucket=bucket,
            Key=destination_key,
            StorageClass=storage_class,
            **source_attributes(s3, bucket, source_key),
        ),
    )
    upload_id = cast("str", created["UploadId"])
    parts: list[dict[str, Any]] = []
    start = 0
    number = 1
    while start < size:
        end = min(start + PART_SIZE, size) - 1
        part = cast(
            "dict[str, Any]",
            s3.upload_part_copy(
                Bucket=bucket,
                Key=destination_key,
                UploadId=upload_id,
                PartNumber=number,
                CopySource={"Bucket": bucket, "Key": source_key},
                CopySourceRange=f"bytes={start}-{end}",
            ),
        )
        parts.append({"ETag": part["CopyPartResult"]["ETag"], "PartNumber": number})
        start = end + 1
        number += 1
    completed = cast(
        "dict[str, Any]",
        s3.complete_multipart_upload(
            Bucket=bucket,
            Key=destination_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        ),
    )
    return cast("str", completed["ETag"])


def buckets_and_spaces(s3: Any, config: dict[str, str]) -> list[tuple[str, str]]:
    """Enumerates every ``(bucket, space root)`` the migration covers.

    Args:
      s3: The S3 client.
      config: The bucket names.

    Returns:
      The pairs, user-space first.

    Raises:
      None.
    """
    pairs: list[tuple[str, str]] = []
    for bucket, skip in (
        (config["user_space_bucket"], SKIPPED_ROOTS),
        (config["shared_space_bucket"], ()),
    ):
        pairs.extend((bucket, root) for root in spaces(s3, bucket, skip))
    return pairs


def mode_report(clients: dict[str, Any], config: dict[str, str], run_id: str | None) -> int:
    """Prints what is there, and what a record says about it. Writes nothing.

    Args:
      clients: The AWS clients.
      config: The bucket, machine and workgroup names.
      run_id: A run to read the record of, or None.

    Returns:
      0.

    Raises:
      None.
    """
    s3 = clients["s3"]
    for bucket, root in buckets_and_spaces(s3, config):
        for folder in MOVING_FOLDERS:
            listed = objects_under(s3, bucket, old_prefix(root, folder))
            total = sum(cast("int", item.get("Size", 0)) for item in listed)
            logger.info(
                "%s %s%s: %d keys, %d bytes", bucket, root, folder, len(listed), total
            )
    if run_id is not None:
        record = load_record(s3, config["admin_bucket"], run_id)
        if record is None:
            logger.info("run %s has no record", run_id)
        else:
            for field in ("conflicts", "oversize", "absent", "refused"):
                logger.info("%s: %s", field, record[field] or "none")
    return 0


def mode_copy(clients: dict[str, Any], config: dict[str, str], run_id: str) -> int:
    """Copies every source to its new home and re-points every moved table.

    Idempotent against its own record: a second run with the same id copies zero keys and
    copies nothing, because every destination already matches its recorded ``copied_etag``.

    Args:
      clients: The AWS clients.
      config: The bucket, machine and workgroup names.
      run_id: The run id, which an existing record is extended under.

    Returns:
      0, or 1 when the run ended with conflicts an operator must resolve.

    Raises:
      Refusal: ``switch_not_landed`` before the write switch is merged; ``precondition_in_flight``
        while a
        racing execution is running.
    """
    require_switch("copy")
    check_preconditions(clients, config)
    s3 = clients["s3"]
    admin = config["admin_bucket"]
    record = load_record(s3, admin, run_id) or empty_record(run_id)
    since_save = 0
    for bucket, root in buckets_and_spaces(s3, config):
        for folder in MOVING_FOLDERS:
            for listed in objects_under(s3, bucket, old_prefix(root, folder)):
                key = cast("str", listed["Key"])
                identifier = recorded_id(bucket, key)
                destination = destination_of(key, root)
                existing = head_or_none(s3, bucket, destination)
                previous = record["keys"].get(identifier)
                if existing is not None:
                    if previous is not None and existing["ETag"] == previous["copied_etag"]:
                        continue
                    if previous is None:
                        if identifier not in record["conflicts"]:
                            record["conflicts"].append(identifier)
                        record["keys"][identifier] = Recorded(
                            source_etag=cast("str", listed["ETag"]),
                            source_last_modified=_stamp(listed.get("LastModified")),
                            copied_etag=cast("str", existing["ETag"]),
                            resolution="",
                        )
                        continue
                    if identifier not in record["conflicts"]:
                        record["conflicts"].append(identifier)
                    continue
                if cast("int", listed.get("Size", 0)) > MULTIPART_THRESHOLD and (
                    identifier not in record["oversize"]
                ):
                    record["oversize"].append(identifier)
                copied = copy_one(s3, bucket, key, destination, listed)
                if identifier in record["oversize"]:
                    record["oversize_done"].append(identifier)
                record["keys"][identifier] = Recorded(
                    source_etag=cast("str", listed["ETag"]),
                    source_last_modified=_stamp(listed.get("LastModified")),
                    copied_etag=copied,
                    resolution="",
                )
                since_save += 1
                if since_save >= RECORD_EVERY:
                    save_record(s3, admin, record)
                    since_save = 0
        save_record(s3, admin, record)
        since_save = 0
    save_record(s3, admin, record)
    logger.info(
        "run %s: %d keys recorded, %d conflicts",
        run_id,
        len(record["keys"]),
        len(record["conflicts"]),
    )
    return 1 if record["conflicts"] else 0


def _stamp(value: Any) -> str:
    """Renders a ``LastModified`` as a string whatever shape the client returned it in.

    Args:
      value: A datetime, a string, or None.

    Returns:
      The ISO-8601 form, or an empty string.

    Raises:
      None.
    """
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    return str(value)


def head_or_none(s3: Any, bucket: str, key: str) -> dict[str, Any] | None:
    """Reads an object's metadata, or None when it is not there.

    **A HEAD of an absent object is a ``ClientError`` with code ``404``, not a ``NoSuchKey``**, and
    the code is read off ``response["Error"]["Code"]`` — botocore's exception carries no ``code``
    attribute at all. Both spellings of that mistake fail the same way: every absent object
    re-raises, so the first destination on a first run aborts the copy. ``cpcommon.errors`` owns
    the extractor, and it is defensive about the response's shape so a classifier never throws
    while classifying.

    An error that is not an absence propagates. A denied HEAD answers the same shape as a missing
    object, and reading a denial as absence is how a copy would decide a destination was free.

    Args:
      s3: The S3 client.
      bucket: The bucket.
      key: The key.

    Returns:
      The ``HeadObject`` response, or None when the object is genuinely absent.

    Raises:
      Exception: Whatever the client raised, when it is not an absence.
    """
    try:
        return cast("dict[str, Any]", s3.head_object(Bucket=bucket, Key=key))
    except Exception as error:
        if error_code(error) in ("404", "NoSuchKey", "NotFound") or isinstance(
            error, s3.exceptions.NoSuchKey
        ):
            return None
        raise


def mode_resolve(
    clients: dict[str, Any], config: dict[str, str], run_id: str, key: str, keep: str
) -> int:
    """Settles one conflict, either way, and records which way.

    ``keep=source`` re-copies the source over the destination and records the new ``copied_etag``.
    ``keep=destination`` marks the key so ``finish`` deletes its source without a match — which is
    the right choice for a table re-shared after the switch, whose destination is the newer data.

    Args:
      clients: The AWS clients.
      config: The bucket names.
      run_id: The run whose record holds the conflict.
      key: The source key to settle, or the record identifier ``"{bucket}|{key}"``. The identifier
        form is the only way to name the shared-space side of a collision: a bare key resolves to
        whichever bucket matches first, and that is always the user-space one.
      keep: ``source`` or ``destination``.

    Returns:
      0.

    Raises:
      Refusal: ``switch_not_landed``; ``no_record`` when the run has none; ``not_a_conflict`` when
        the key is not listed as one.
    """
    require_switch("resolve")
    s3 = clients["s3"]
    admin = config["admin_bucket"]
    record = load_record(s3, admin, run_id)
    if record is None:
        raise Refusal("no_record", run_id)
    if "|" in key and key.partition("|")[0] in (
        config["user_space_bucket"],
        config["shared_space_bucket"],
    ):
        bucket = key.partition("|")[0]
        key = recorded_key(key)
        root = next(
            (r for b, r in buckets_and_spaces(s3, config) if b == bucket and key.startswith(r)),
            "",
        )
        if not root:
            raise Refusal("outside_migration_scope", key)
    else:
        bucket, root = bucket_and_root_for(s3, config, key)
    identifier = recorded_id(bucket, key)
    if identifier not in record["conflicts"]:
        raise Refusal("not_a_conflict", key)
    if keep == "source":
        head = head_or_none(s3, bucket, key)
        if head is None:
            raise Refusal("source_absent", key)
        listed = {
            "Key": key,
            "ETag": head["ETag"],
            "Size": head.get("ContentLength", 0),
            "StorageClass": head.get("StorageClass", "STANDARD"),
            "LastModified": head.get("LastModified"),
        }
        copied = copy_one(s3, bucket, key, destination_of(key, root), listed)
        record["keys"][identifier] = Recorded(
            source_etag=cast("str", head["ETag"]),
            source_last_modified=_stamp(head.get("LastModified")),
            copied_etag=copied,
            resolution="keep-source",
        )
    else:
        entry = record["keys"][identifier]
        entry["resolution"] = "keep-destination"
        record["keys"][identifier] = entry
    record["conflicts"] = [k for k in record["conflicts"] if k != identifier]
    save_record(s3, admin, record)
    logger.info("resolved %s as keep-%s; %d conflicts left", key, keep, len(record["conflicts"]))
    return 0


def bucket_and_root_for(
    s3: Any, config: dict[str, str], key: str
) -> tuple[str, str]:
    """Finds which bucket and space root a source key belongs to.

    Args:
      s3: The S3 client.
      config: The bucket names.
      key: The source key.

    Returns:
      The bucket and the space root.

    Raises:
      Refusal: ``outside_migration_scope`` when no space claims the key.
    """
    for bucket, root in buckets_and_spaces(s3, config):
        if key.startswith(root):
            folder_of(key, root)
            return bucket, root
    raise Refusal("outside_migration_scope", key)


def mode_verify(clients: dict[str, Any], config: dict[str, str], run_id: str) -> int:
    """Reads a sample of copied keys back and prints source against destination, side by side.

    The sample takes ``VERIFY_SAMPLE`` keys per bucket, every storage class present at least once,
    and **every oversize key**, because attribute preservation is exactly what the fakes cannot
    prove. A sample holding only ``STANDARD`` objects would say nothing about the others; a sample
    holding no oversize key would say nothing about the multipart path, which is the ONE place
    these attributes can be silently lost — a single ``CopyObject`` carries them at ``COPY``, and a
    multipart copy carries only what its create was given.

    **Each sampled key is carried with the space root it was found under.** The sample is scoped to
    a bucket and a bucket holds many spaces, so a key paired with the wrong root maps to a
    destination in another space — which ``folder_of`` then refuses, taking the whole mode down on
    the second space of any real bucket.

    Args:
      clients: The AWS clients.
      config: The bucket names.
      run_id: The run whose record names the keys.

    Returns:
      0.

    Raises:
      Refusal: ``no_record`` when the run has none.
    """
    s3 = clients["s3"]
    record = load_record(s3, config["admin_bucket"], run_id)
    if record is None:
        raise Refusal("no_record", run_id)
    chosen: dict[str, list[tuple[str, str]]] = {}
    seen_classes: dict[str, set[str]] = {}
    for bucket, root in buckets_and_spaces(s3, config):
        sampled = chosen.setdefault(bucket, [])
        classes = seen_classes.setdefault(bucket, set())
        prefix = recorded_id(bucket, root)
        oversize = {recorded_key(i) for i in record["oversize"] if i.startswith(prefix)}
        for identifier in sorted(record["keys"]):
            if not identifier.startswith(prefix):
                continue
            if len(sampled) >= VERIFY_SAMPLE and not oversize and len(classes) > 1:
                break
            key = recorded_key(identifier)
            head = head_or_none(s3, bucket, key)
            if head is None:
                continue
            storage = cast("str", head.get("StorageClass", "STANDARD"))
            wanted = key in oversize or storage not in classes or len(sampled) < VERIFY_SAMPLE
            if wanted:
                sampled.append((root, key))
                classes.add(storage)
                oversize.discard(key)
    for bucket, pairs in chosen.items():
        for root, key in pairs:
            destination = destination_of(key, root)
            source_head = head_or_none(s3, bucket, key)
            destination_head = head_or_none(s3, bucket, destination)
            logger.info(
                "%s\n  source      class=%s type=%s meta=%s tags=%s\n  destination class=%s "
                "type=%s meta=%s tags=%s",
                key,
                _attr(source_head, "StorageClass"),
                _attr(source_head, "ContentType"),
                _attr(source_head, "Metadata"),
                _tags(s3, bucket, key),
                _attr(destination_head, "StorageClass"),
                _attr(destination_head, "ContentType"),
                _attr(destination_head, "Metadata"),
                _tags(s3, bucket, destination),
            )
    return 0


def _attr(head: dict[str, Any] | None, name: str) -> Any:
    """Reads one attribute off a HEAD response that may be absent.

    Args:
      head: The response, or None.
      name: The attribute.

    Returns:
      The value, or the string ``absent``.

    Raises:
      None.
    """
    if head is None:
        return "absent"
    return head.get(name, "")


def _tags(s3: Any, bucket: str, key: str) -> Any:
    """Reads an object's tag set, tolerating an object that is not there.

    Args:
      s3: The S3 client.
      bucket: The bucket.
      key: The key.

    Returns:
      The tag set, or the string ``absent``.

    Raises:
      None.
    """
    try:
        response = cast("dict[str, Any]", s3.get_object_tagging(Bucket=bucket, Key=key))
    except Exception:  # noqa: BLE001 - a missing object is reported as absent, not as a failure
        return "absent"
    return response.get("TagSet", [])


def mode_finish(clients: dict[str, Any], config: dict[str, str], run_id: str) -> int:
    """Deletes every source whose copy re-verifies. **This is the point of no return.**

    Both sides are re-HEADed first: a source whose ETag no longer matches the record has been
    rewritten since the copy, and a destination that no longer matches ``copied_etag`` has been
    overwritten. Either lands the key under ``refused`` and it is not deleted. A source already
    gone lands under ``absent``, which is ordinary for a re-run and for an object a user deleted
    between the copy and the finish.

    **A key an operator resolved as ``keep-destination`` skips the destination comparison**, which
    is the whole content of that resolution: they looked, and said the destination is the newer
    truth. Its ``copied_etag`` is by definition stale — that is what made it a conflict — so
    comparing against it would refuse the one key the operator has already settled, which is the
    spec's own remedy for a table re-shared after the switch. The SOURCE is still re-verified, so
    the resolution buys a deletion that was decided by a human, never one decided by a mismatch.

    The recorded source ETag rides on each identifier as a belt, but only when this runtime's
    botocore carries the field — a model without it raises ``ParamValidationError`` for the whole
    request rather than a per-item error. The head re-verify is the guard this actually relies on.

    Args:
      clients: The AWS clients.
      config: The bucket names.
      run_id: The run whose record says what may be deleted.

    Returns:
      0, or 1 when anything was refused.

    Raises:
      Refusal: ``switch_not_landed``; ``no_record``; ``conflicts_outstanding`` while any conflict
        is unresolved.
    """
    require_switch("finish")
    s3 = clients["s3"]
    admin = config["admin_bucket"]
    record = load_record(s3, admin, run_id)
    if record is None:
        raise Refusal("no_record", run_id)
    if record["conflicts"]:
        raise Refusal("conflicts_outstanding", ", ".join(record["conflicts"]))
    conditional = supports_conditional_delete(s3)
    record["absent"] = []
    record["refused"] = []
    for bucket, root in buckets_and_spaces(s3, config):
        pending: list[dict[str, Any]] = []
        prefix = recorded_id(bucket, root)
        for identifier, entry in sorted(record["keys"].items()):
            if not identifier.startswith(prefix):
                continue
            key = recorded_key(identifier)
            source = head_or_none(s3, bucket, key)
            if source is None:
                record["absent"].append(identifier)
                continue
            if cast("str", source["ETag"]) != entry["source_etag"]:
                record["refused"].append(identifier)
                continue
            destination = head_or_none(s3, bucket, destination_of(key, root))
            if destination is None:
                record["refused"].append(identifier)
                continue
            if (
                entry["resolution"] != "keep-destination"
                and cast("str", destination["ETag"]) != entry["copied_etag"]
            ):
                record["refused"].append(identifier)
                continue
            delete_identifier: dict[str, Any] = {"Key": key}
            if conditional:
                delete_identifier["ETag"] = entry["source_etag"]
            pending.append(delete_identifier)
        for start in range(0, len(pending), DELETE_BATCH):
            batch = pending[start : start + DELETE_BATCH]
            response = cast(
                "dict[str, Any]",
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch}),
            )
            for failure in response.get("Errors", []):
                record["refused"].append(recorded_id(bucket, cast("str", failure["Key"])))
    save_record(s3, admin, record)
    logger.info(
        "run %s: %d deleted, %d absent, %d refused",
        run_id,
        len(record["keys"]) - len(record["absent"]) - len(record["refused"]),
        len(record["absent"]),
        len(record["refused"]),
    )
    return 1 if record["refused"] else 0


def mode_prove_empty(clients: dict[str, Any], config: dict[str, str]) -> int:
    """Proves every old prefix holds nothing, positively and fail-closed.

    Only meaningful between ``finish`` and the narrowing merge: ``old_prefix`` reads the plural
    builder's first element, which the narrowing deletes, so a run afterwards would enumerate the
    NEW home and answer "empty" to a question nobody asked. ``old_prefix`` refuses that outright.

    An error is never read as an empty prefix — a failed call and an empty one are the same shape
    from the outside, and treating them alike is how a half-finished migration looks finished.

    Args:
      clients: The AWS clients.
      config: The bucket names.

    Returns:
      0 when every prefix is empty, 1 otherwise.

    Raises:
      Refusal: ``narrowing_already_merged`` when the old home is no longer addressable.
    """
    s3 = clients["s3"]
    occupied: list[str] = []
    for bucket, root in buckets_and_spaces(s3, config):
        for folder in MOVING_FOLDERS:
            prefix = old_prefix(root, folder)
            try:
                page = cast(
                    "dict[str, Any]",
                    s3.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1),
                )
            except Exception as error:  # noqa: BLE001 - a failed call is not an empty prefix
                occupied.append(f"{bucket}/{prefix} (unreadable: {error})")
                continue
            if page.get("Contents"):
                occupied.append(f"{bucket}/{prefix}")
    for entry in occupied:
        logger.error("still occupied: %s", entry)
    if occupied:
        return 1
    logger.info("every old prefix is empty across every space")
    return 0


def make_clients() -> dict[str, Any]:
    """Builds the four AWS clients this module uses.

    Imported inside the function so importing this module for its pure helpers — which is what the
    tests do — needs no credentials and no boto3.

    Args:
      None.

    Returns:
      The ``s3``, ``sfn`` and ``athena`` clients.

    Raises:
      None.
    """
    import boto3

    return {
        "s3": boto3.client("s3"),
        "sfn": boto3.client("stepfunctions"),
        "athena": boto3.client("athena"),
    }


def read_config(environ: dict[str, str]) -> dict[str, str]:
    """Reads the resource names the workflow derives from repository variables.

    Args:
      environ: The process environment.

    Returns:
      The bucket names, the two state-machine ARNs and the workgroup.

    Raises:
      Refusal: ``config_missing``, naming every variable that is absent OR empty — an unset
        repository variable renders as the empty string, which satisfies a presence check and
        means nothing.
    """
    wanted = (
        "USER_SPACE_BUCKET",
        "SHARED_SPACE_BUCKET",
        "ADMIN_BUCKET",
        "ARCHIVE_STATE_MACHINE_ARN",
        "TABLE_SHARE_STATE_MACHINE_ARN",
        "ATHENA_WORKGROUP",
    )
    missing = [name for name in wanted if not environ.get(name, "").strip()]
    if missing:
        raise Refusal("config_missing", ", ".join(missing))
    return {
        "user_space_bucket": environ["USER_SPACE_BUCKET"],
        "shared_space_bucket": environ["SHARED_SPACE_BUCKET"],
        "admin_bucket": environ["ADMIN_BUCKET"],
        "archive_state_machine_arn": environ["ARCHIVE_STATE_MACHINE_ARN"],
        "table_share_state_machine_arn": environ["TABLE_SHARE_STATE_MACHINE_ARN"],
        "workgroup": environ["ATHENA_WORKGROUP"],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parses the command line the workflow builds.

    Args:
      argv: The arguments after the program name.

    Returns:
      The parsed namespace.

    Raises:
      SystemExit: On an unparseable command line, as argparse does.
    """
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--keep", choices=("source", "destination"), default="source")
    return parser.parse_args(argv)


def run(argv: list[str], environ: dict[str, str], clients: dict[str, Any]) -> int:
    """Dispatches one mode and reports its outcome.

    Args:
      argv: The command line after the program name.
      environ: The process environment.
      clients: The AWS clients.

    Returns:
      The process exit code.

    Raises:
      Refusal: Whatever the selected mode refuses. The caller turns it into an exit code so the
        code is printed rather than a traceback.
    """
    args = parse_args(argv)
    config = read_config(environ)
    run_id = args.run_id or environ.get("GITHUB_RUN_ID", "")
    announce_run_id(environ, run_id, args.mode)
    if args.mode == "report":
        return mode_report(clients, config, run_id or None)
    if args.mode == "prove-empty":
        return mode_prove_empty(clients, config)
    if not run_id:
        raise Refusal("run_id_required", args.mode)
    if args.mode == "copy":
        return mode_copy(clients, config, run_id)
    if args.mode == "resolve":
        if not args.key:
            raise Refusal("key_required", "resolve")
        return mode_resolve(clients, config, run_id, args.key, args.keep)
    if args.mode == "verify":
        return mode_verify(clients, config, run_id)
    return mode_finish(clients, config, run_id)


def announce_run_id(environ: dict[str, str], run_id: str, mode: str) -> None:
    """Writes the run id this invocation is using to the step summary.

    It is the EFFECTIVE id — the one passed in, falling back to the workflow run's own — because
    every mode after the first copy is given an existing id, and printing the ambient one instead
    would tell an operator to carry a value that opens a SECOND record on the next copy, splitting
    one migration across two.

    Args:
      environ: The process environment.
      run_id: The id this invocation resolved.
      mode: The mode being run, so the line says what the id belongs to.

    Returns:
      None.

    Raises:
      None.
    """
    summary = environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary or not run_id:
        return
    with pathlib.Path(summary).open("a", encoding="utf-8") as handle:
        handle.write(f"\nRun id for `{mode}`: `{run_id}` — carry this into every later mode.\n")


def main() -> int:
    """Entry point: configures logging, runs one mode, and prints a refusal by its code.

    Args:
      None.

    Returns:
      The process exit code.

    Raises:
      None.
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        return run(sys.argv[1:], dict(os.environ), make_clients())
    except Refusal as refusal:
        logger.error("%s", refusal)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
