"""What a person is told about how many files an archive or a restore moved.

The portal's New folder writes a zero-byte key ending in ``/``, and the plane carries it so an
archived empty folder comes back. On 2026-09-21 that made one 38-byte file read as "Archived 2
files", in the notification, the receipt and the restore-started message alike. The fix is a
count that rides beside the object count rather than replacing it, so the tests that matter are
the ones that cross verbs: the count is written by a manifest builder, carried on the state,
threaded by the ASL and read by another verb, and a field name that disagreed at any one of those
seams would render the object count again with every per-verb suite green.

So the chains below drive each real handler in turn over one in-memory S3, resolve every notify
payload from the rendered state machine rather than building it by hand, and assert the sentence
the user reads.
"""

import json
import os
import pathlib
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _verb in (
    "control-plane-common",
    "archive-build-transfer-manifest",
    "archive-build-restore-manifest",
    "archive-copy-objects",
    "archive-collect-transfer-results",
    "archive-rollback",
    "archive-write-receipt",
    "archive-notify",
):
    sys.path.insert(0, os.path.join(_HERE, "..", _verb))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_build_restore_manifest
import archive_build_transfer_manifest
import archive_collect_transfer_results
import archive_copy_objects
import archive_notify
import archive_rollback
import archive_write_receipt
import pytest
from arcommon import counts, notify
from cpcommon import clients
from cpcommon.errors import TerminalError

_ASL = os.path.join(_HERE, "..", "..", "infra", "planes", "archive", "state-machine.asl.json.tftpl")
_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
_ARCHIVE_ID = "57d14bb9-be06-4790-81ab-d5a95d484926"
_RESTORE_ID = "6a1e2c3d-4b5f-4c6d-8e7f-9a0b1c2d3e4f"
_SPACE_ROOT = "livecheck_186/"
_ARCHIVE_ROOT = f"shared/livecheck_186/archive/{_ARCHIVE_ID}/"
_PLACEHOLDER = "live0921_archive/"
_FILE = "live0921_archive/archive_0921.csv"


def _states() -> dict:
    """Renders the archive machine with Terraform's interpolations stubbed, as its own suite does."""
    raw = pathlib.Path(_ASL).read_text()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{([^}]+)\}", r"\1", raw))["States"]


STATES = _states()


def _payload(state_name: str, state: dict) -> dict:
    """Resolves a Task's Payload against a state the way Step Functions would.

    An absent path raises ``KeyError`` here, which is the uncatchable ``States.Runtime`` it would
    be in production — so a payload that reads a field the chain never wrote fails the test.
    """

    def resolve(template):
        out = {}
        for key, value in template.items():
            if key.endswith(".$"):
                node = state
                for part in value.removeprefix("$.").split("."):
                    node = node[part]
                out[key[:-2]] = node
            elif isinstance(value, dict):
                out[key] = resolve(value)
            else:
                out[key] = value
        return out

    return resolve(STATES[state_name]["Parameters"]["Payload"])


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 403}}
        super().__init__(code)


class _FakeS3:
    """One in-memory S3 across every bucket, so each verb reads what the one before it wrote."""

    def __init__(self, objects, refuse_copy=()):
        self.objects = dict(objects)
        self._refuse_copy = set(refuse_copy)

    def get_object(self, Bucket, Key, **_):
        if (Bucket, Key) not in self.objects:
            raise _S3Error("NoSuchKey")
        body = self.objects[(Bucket, Key)]

        class _Body:
            def read(self):
                return body

        return {"Body": _Body()}

    def put_object(self, Bucket, Key, Body, **_):
        self.objects[(Bucket, Key)] = Body
        return {}

    def copy_object(self, Bucket, Key, CopySource, **_):
        if CopySource["Key"] in self._refuse_copy:
            raise _S3Error("AccessDenied")
        self.objects[(Bucket, Key)] = self.objects[(CopySource["Bucket"], CopySource["Key"])]
        return {}

    def get_paginator(self, name):
        objects = self.objects

        class _Pages:
            def paginate(self, Bucket, Prefix, **_):
                yield {
                    "Contents": [
                        {"Key": key, "Size": len(body)}
                        for (bucket, key), body in sorted(objects.items())
                        if bucket == Bucket and key.startswith(Prefix)
                    ]
                }

        return _Pages()

    def delete_objects(self, Bucket, Delete):
        for entry in Delete["Objects"]:
            self.objects.pop((Bucket, entry["Key"]), None)
        return {"Errors": []}


@pytest.fixture
def told(monkeypatch):
    """Every notification any verb in the chain sent, as ``(recipient, text)``."""
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _archive_run(objects: list, refuse_copy=()) -> tuple:
    """Stands up the live check's archive: its plan in the admin bucket and its source objects.

    Returns the fake and the state as ``BuildTransferManifest`` receives it.
    """
    plan_key = f"archive/{_ARCHIVE_ID}/copy-plan.json"
    total = sum(entry["bytes"] for entry in objects)
    fake = _FakeS3(
        {
            ("admin-bkt", plan_key): json.dumps({
                "requestId": _ARCHIVE_ID,
                "actor": "agriffith",
                "source": {"bucket": "shared-bkt", "root": _SPACE_ROOT},
                "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
                "objectCount": len(objects),
                "totalBytes": total,
                "objects": objects,
            }).encode(),
            **{
                ("shared-bkt", f"{_SPACE_ROOT}{entry['relKey']}"): b"x" * entry["bytes"]
                for entry in objects
            },
        },
        refuse_copy={f"{_SPACE_ROOT}{key}" for key in refuse_copy},
    )
    clients._s3 = fake
    state = {
        "traceparent": _TRACEPARENT,
        "requestId": _ARCHIVE_ID,
        "mode": "archive",
        "actor": {"username": "agriffith"},
        "source": {"bucket": "shared-bkt", "root": _SPACE_ROOT, "kind": "shared", "name": "livecheck_186"},
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "receiptBucket": "shared-bkt",
            "receiptKey": f"{_SPACE_ROOT}system_settings/archive/{_ARCHIVE_ID}/receipt.txt",
        },
        "execution": {"name": "arch-exec-1", "startedAt": "2026-09-21T20:14:03.000Z"},
        "copyPlanKey": plan_key,
        "objectCount": len(objects),
        "totalBytes": total,
    }
    return fake, state


_ONE_FILE_IN_A_NEW_FOLDER = [{"relKey": _PLACEHOLDER, "bytes": 0}, {"relKey": _FILE, "bytes": 38}]


@pytest.mark.parametrize(
    "objects,sentence,receipt_line",
    [
        (
            _ONE_FILE_IN_A_NEW_FOLDER,
            (
                f"Archived 1 file (38 B). It has been removed from your space. Archive id: "
                f"{_ARCHIVE_ID} - to restore it, open the livecheck_186 space in Files, choose "
                "Restore Archived Data and pick this archive from the list."
            ),
            "Files archived:    1",
        ),
        (
            [{"relKey": _PLACEHOLDER, "bytes": 0}],
            (
                f"Archived 1 empty folder (0 B). It has been removed from your space. Archive "
                f"id: {_ARCHIVE_ID} - to restore it, open the livecheck_186 space in Files, "
                "choose Restore Archived Data and pick this archive from the list."
            ),
            "Files archived:    0",
        ),
    ],
    ids=["the-live-check", "nothing-but-an-empty-folder"],
)
def test_an_archive_names_its_files_in_the_notification_and_on_the_receipt(
    told, objects, sentence, receipt_line
):
    """The live check's own shape: one 38-byte file inside a folder New folder made. Driven from
    the real manifest builder through the receipt writer and the notify verb, with the payload
    resolved from the machine — so the builder's field, the ASL's threading and the notify's read
    all have to agree for the sentence to say one file."""
    fake, state = _archive_run(objects)

    built = archive_build_transfer_manifest.handler(state, None)
    receipted = archive_write_receipt.handler(built, None)
    archive_notify.handler(_payload("NotifyArchived", receipted), None)

    receipt = fake.objects[("shared-bkt", receipted["archive"]["receiptKey"])].decode()
    assert receipt_line in receipt.splitlines()
    assert told == [("agriffith", sentence)]


@pytest.mark.parametrize(
    "refused,counted",
    [((_PLACEHOLDER,), "1 of 2"), ((_FILE,), "0 of 1")],
    ids=["the-folder-placeholder-did-not-copy", "the-file-did-not-copy"],
)
def test_a_copy_that_fell_short_names_files_and_counts_a_placeholder_only_when_it_is_short(
    told, refused, counted
):
    """The seam the flag crosses: the builder writes it on the line, the copy verb echoes it onto
    the failure, the collector counts it apart and the rollback names the result. A placeholder
    left behind is counted, so the sentence cannot read "1 of 1"; a placeholder that copied is
    not, so it cannot read "0 of 2" over one file."""
    fake, state = _archive_run(_ONE_FILE_IN_A_NEW_FOLDER, refuse_copy=refused)
    built = archive_build_transfer_manifest.handler(state, None)
    transfer = built["transfer"]
    lines = [
        json.loads(line)
        for line in fake.objects[("admin-bkt", transfer["manifestKey"])].decode().splitlines()
    ]
    copied = archive_copy_objects.handler(
        {"Items": lines, "BatchInput": {"traceparent": _TRACEPARENT, "requestId": _ARCHIVE_ID}},
        None,
    )
    results = f"{transfer['resultsPrefix']}/run-1"
    fake.objects[("admin-bkt", f"{results}/SUCCEEDED_0.json")] = json.dumps(
        [{"Output": json.dumps(copied)}]
    ).encode()
    fake.objects[("admin-bkt", f"{results}/manifest.json")] = json.dumps(
        {"ResultFiles": {"SUCCEEDED": [{"Key": f"{results}/SUCCEEDED_0.json", "Size": 1}]}}
    ).encode()
    mapped = {
        **built,
        "mapRun": {"ResultWriterDetails": {"Bucket": "admin-bkt", "Key": f"{results}/manifest.json"}},
    }

    collected = archive_collect_transfer_results.handler(mapped, None)
    with pytest.raises(TerminalError) as err:
        archive_rollback.handler(collected, None)

    assert err.value.reason == "archive_incomplete"
    assert told == [
        (
            "agriffith",
            (
                f"Couldn't archive that: only {counted} file(s) could be copied, so nothing was "
                "deleted and your files are exactly where they were. Please try again."
            ),
        )
    ]


def test_a_restore_names_its_files_when_it_starts_and_when_it_finishes(told):
    """The restore arm reads the count off the restore manifest's block, at two notifies hours
    apart. Both payloads are resolved from the machine, and the second threads the cleanup block
    the vault sweep writes."""
    plan_key = f"archive/{_RESTORE_ID}/restore-plan.json"
    archive = {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT, "archiveId": _ARCHIVE_ID}
    clients._s3 = _FakeS3(
        {
            ("admin-bkt", plan_key): json.dumps({
                "requestId": _RESTORE_ID,
                "actor": "agriffith",
                "archive": archive,
                "space": {"bucket": "shared-bkt", "root": _SPACE_ROOT},
                "objectCount": 2,
                "totalBytes": 38,
                "objects": [
                    {
                        "archiveKey": f"{_ARCHIVE_ROOT}{key}",
                        "destKey": f"{_SPACE_ROOT}{key}",
                        "bytes": size,
                    }
                    for key, size in ((_PLACEHOLDER, 0), (_FILE, 38))
                ],
            }).encode()
        }
    )
    state = {
        "traceparent": _TRACEPARENT,
        "requestId": _RESTORE_ID,
        "mode": "restore",
        "actor": {"username": "agriffith"},
        "source": {"bucket": "shared-bkt", "root": _SPACE_ROOT, "kind": "shared", "name": "livecheck_186"},
        "archive": archive,
        "planKey": plan_key,
        "objectCount": 2,
        "totalBytes": 38,
        "execution": {"name": "restore-exec-1", "startedAt": "2026-09-21T21:02:40.000Z"},
    }

    built = archive_build_restore_manifest.handler(state, None)
    archive_notify.handler(_payload("NotifyRestoreStarted", built), None)
    swept = {**built, "cleanup": {"deleted": 2, "residue": 0, "cleanupIncomplete": False}}
    archive_notify.handler(_payload("NotifyRestored", swept), None)

    assert [text for _, text in told] == [
        (
            "Restoring 1 file from long-term storage. This takes several hours - you'll get "
            "another notification when it finishes. Nothing has changed in your space yet."
        ),
        (
            "Restored 1 file (38 B) to your space, back where it came from. The archive has "
            "been cleaned up."
        ),
    ]


@pytest.mark.parametrize(
    "files,files_short,folders_short,unknown_short,expected",
    [
        (1, 0, 0, 0, (1, 1)),
        (1, 1, 0, 0, (0, 1)),
        (1, 0, 1, 0, (1, 2)),
        (1, 0, 0, 3, (0, 3)),
        (1, 3, 0, 0, (0, 3)),
        (2, 1, 1, 1, (0, 3)),
        (0, 0, 1, 0, (0, 1)),
    ],
    ids=[
        "nothing-short",
        "the-file-short",
        "a-placeholder-short",
        "unattributed-beyond-the-files",
        "more-files-short-than-files",
        "every-kind-short",
        "only-folders-and-one-short",
    ],
)
def test_the_pair_a_sentence_names_holds_its_invariant_on_every_shortfall(
    files, files_short, folders_short, unknown_short, expected
):
    """``done`` never goes below zero and ``total - done`` is always the whole shortfall — so
    "only N of N" cannot be rendered over a run that fell short, whatever mix of kinds it was,
    including items an export never accounted for."""
    done, total = counts.shown(files, files_short, folders_short, unknown_short)

    assert (done, total) == expected
    assert done >= 0
    assert total - done == files_short + folders_short + unknown_short


@pytest.mark.parametrize(
    "state,expected",
    [
        ({"objectCount": 2, "transfer": {"fileCount": 1}}, 1),
        ({"objectCount": 2}, 2),
        ({"objectCount": 2, "transfer": {"itemCount": 2}}, 2),
        ({"objectCount": 2, "transfer": {"fileCount": True}}, 2),
        ({"objectCount": 2, "transfer": {"fileCount": 3}}, 2),
        ({"objectCount": 2, "transfer": {"fileCount": -1}}, 2),
    ],
    ids=[
        "the-builders-count",
        "a-payload-from-the-older-definition",
        "a-block-from-the-older-builder",
        "a-flag-is-not-a-count",
        "more-files-than-objects",
        "a-negative-count",
    ],
)
def test_the_file_count_falls_back_to_the_object_count_it_replaced(state, expected):
    """A restore waits hours on the definition it started with, and the definition and the code
    deploy in no fixed order, so a notify can meet a payload an older half wrote. The fallback is
    the wording from before the count existed, never a guess."""
    assert counts.file_count(state) == expected


def test_the_shown_counts_fall_back_to_the_verdicts_object_counts():
    """A verb reading the verdict can run on newer code than the collector that wrote it seconds
    earlier; without the block it reads the object counts it read before."""
    shown = {"copied": 1, "expected": 3, "occupied": 0, "shown": {"copied": 0, "total": 1, "occupied": 0}}
    older = {"copied": 1, "expected": 3, "occupied": 1}

    assert counts.shown_outcome(shown) == (0, 1, 0)
    assert counts.shown_outcome(older) == (1, 3, 1)
