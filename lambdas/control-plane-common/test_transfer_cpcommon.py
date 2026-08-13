"""Unit tests for the shared transfer engine (SPEC-160).

The manifest writer's file format, the batch copier's failure isolation, and the result
reader's two attribution paths — including the one a FAILED-only collector silently passes.
AWS is stubbed with a recording fake. Runnable under pytest or directly:
python3 test_transfer_cpcommon.py.
"""

import json
import math
import os
import pathlib
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import clients, messages
from cpcommon.errors import TerminalError, TransientError
from cpcommon.transfer import config as transfer_config
from cpcommon.transfer import copy as copy_mod
from cpcommon.transfer import manifest as manifest_mod
from cpcommon.transfer import results as results_mod

GIB = 1024**3

#: Reason codes the tests pass in as a caller would. Registered so TerminalError accepts them
#: without importing a domain layer — cpcommon owns the algorithm, not the wording.
_FAILED = "copy_failed"
_UNREADABLE = "transfer_results_unreadable"

messages.register(
    {_FAILED: "copying the data failed.", _UNREADABLE: "the transfer results were unreadable."},
    prefix="Test: ",
)


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, objects=None, copy_error=None, get_error=None, source_headers=None):
        self.objects = objects or {}
        self.puts = []
        self.copies = []
        self.multipart = []
        self.aborted = []
        self.heads = []
        self.copy_error = copy_error
        self.get_error = get_error
        # What HeadObject reports for a source object. Empty by default: the multipart path
        # re-states only what the source actually carries, so the default case must produce a
        # CreateMultipartUpload identical to the one that shipped before SPEC-171.
        self.source_headers = source_headers or {}
        self._uploads = 0

    def head_object(self, **kwargs):
        self.heads.append(kwargs)
        return {"ContentLength": 0, **self.source_headers}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)

    def get_object(self, **kwargs):
        if self.get_error:
            raise self.get_error
        try:
            body = self.objects[kwargs["Key"]]
        except KeyError as err:
            raise _S3Error("NoSuchKey") from err
        return {"Body": _Body(body)}

    def copy_object(self, **kwargs):
        error = self.copy_error(kwargs) if callable(self.copy_error) else self.copy_error
        if error:
            raise error
        self.copies.append(kwargs)

    def create_multipart_upload(self, **kwargs):
        self._uploads += 1
        return {"UploadId": f"u{self._uploads}"}

    def upload_part_copy(self, **kwargs):
        self.multipart.append(kwargs)
        return {"CopyPartResult": {"ETag": f"etag-{kwargs['PartNumber']}"}}

    def complete_multipart_upload(self, **kwargs):
        self.multipart.append({"complete": kwargs})

    def abort_multipart_upload(self, **kwargs):
        self.aborted.append(kwargs)


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode()


def _setup(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _item(recipient="bob", rel="part-0.parquet", size=10):
    return {
        "recipient": recipient,
        "kind": "user",
        "srcBucket": "user-bkt",
        "srcKey": f"alice/sales/{rel}",
        "destBucket": "user-bkt",
        "destKey": f"{recipient}/shared_tables/orders/{rel}",
        "size": size,
    }


# ── manifest ────────────────────────────────────────────────────────────────


def test_the_manifest_is_one_json_object_per_line():
    fake = _setup()
    items = [_item(rel="a.parquet"), _item(rel="b.parquet")]

    count = manifest_mod.write_manifest("admin-bkt", "table-share/h/exec/transfer-manifest.jsonl", items)

    assert count == 2
    body = fake.puts[0]["Body"].decode()
    assert [json.loads(line) for line in body.split("\n")] == items
    assert fake.puts[0]["Key"] == "table-share/h/exec/transfer-manifest.jsonl"


def test_the_manifest_has_no_trailing_newline():
    """A blank final line is a line, and the reader would hand it back as an empty item."""
    fake = _setup()
    manifest_mod.write_manifest("admin-bkt", "k.jsonl", [_item()])
    assert not fake.puts[0]["Body"].endswith(b"\n")


def test_an_empty_manifest_writes_nothing_but_a_zero_count():
    fake = _setup()
    assert manifest_mod.write_manifest("admin-bkt", "k.jsonl", []) == 0
    assert fake.puts[0]["Body"] == b""


def test_a_throttled_manifest_write_is_transient():
    fake = _setup()
    fake.put_object = lambda **kwargs: (_ for _ in ()).throw(_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        manifest_mod.write_manifest("admin-bkt", "k.jsonl", [_item()])


def test_a_deterministic_manifest_write_propagates():
    fake = _setup()
    fake.put_object = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    with pytest.raises(_S3Error):
        manifest_mod.write_manifest("admin-bkt", "k.jsonl", [_item()])


def test_a_worst_case_batch_stays_under_the_input_limit():
    """The batch size is sized against S3's limits, not against a typical key (FR-002 AC3).

    A child execution's input is capped at 256 KB. The worst an item can be is two 1024-byte
    keys and two 63-byte bucket names, so the bound is computed here rather than asserted as a
    number — raising MAX_ITEMS_PER_BATCH without re-checking it fails this test.
    """
    worst = {
        "recipient": "r" * 63,
        "kind": "space",
        "srcBucket": "b" * 63,
        "srcKey": "s" * 1024,
        "destBucket": "d" * 63,
        "destKey": "k" * 1024,
        "size": 5 * GIB,
    }
    batch = json.dumps({"Items": [worst] * transfer_config.MAX_ITEMS_PER_BATCH})
    assert len(batch.encode()) < 256 * 1024 // 2, "a worst-case batch is not far below the limit"


def test_a_worst_case_batch_copies_inside_the_verb_timeout():
    """SPEC-161: the batch's OTHER bound, computed as a MAKESPAN rather than a bandwidth.

    The payload bound above is why the batch was 50; this is why it is ``COPY_CONCURRENCY``.
    ``ItemBatcher`` batches by **count**, never by bytes, so the unit that must finish inside
    one ``copy-objects`` invocation is ``MAX_ITEMS_PER_BATCH`` objects at the per-object cap.
    While table-share's TOTAL cap was 20 GiB that was implicit — a batch could not exceed the
    whole table — and raising it to 1 TiB removed the bound.

    **The model matters as much as the number, and an earlier version of this test got it
    wrong in a way that read as safe.** It divided the batch's bytes by
    ``COPY_CONCURRENCY x rate``, as though the objects shared one pipe. They do not:
    ``copy_batch`` submits one WHOLE object per worker and ``copy_one`` part-copies serially,
    so an object holds a worker for ``size / rate`` however idle the others are. A batch costs
    ``ceil(items / COPY_CONCURRENCY)`` ROUNDS of its slowest object. At 10 items the aggregate
    reading said 537 s and the makespan was 859 — 41 seconds from a hard Lambda timeout, and
    green the whole time.

    The throughput is deliberately pessimistic: a measured rate would make the bound depend on
    the day S3 was measured, and being wrong costs a timed-out batch and a failed recipient.
    """
    sys.path.insert(0, os.path.join(_HERE, "..", "table-share-common"))
    from tscommon import config as ts_config

    per_object = ts_config.SHARE_MAX_OBJECT_BYTES / transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND
    rounds = math.ceil(transfer_config.MAX_ITEMS_PER_BATCH / copy_mod.COPY_CONCURRENCY)
    makespan = rounds * per_object
    budget = transfer_config.COPY_TIMEOUT_SECONDS * 2 / 3

    assert makespan < budget, (
        f"a worst-case batch is {rounds} round(s) of a "
        f"{ts_config.SHARE_MAX_OBJECT_BYTES / GIB:,.0f} GiB object = {makespan:,.0f}s at "
        f"{transfer_config.CONSERVATIVE_STREAM_BYTES_PER_SECOND / 1e6:.0f} MB/s per stream, "
        f"against copy-objects' {transfer_config.COPY_TIMEOUT_SECONDS}s timeout — lower "
        f"MAX_ITEMS_PER_BATCH or SHARE_MAX_OBJECT_BYTES"
    )


def test_a_batch_is_exactly_one_round_of_the_worker_pool():
    """The invariant that makes the makespan above one object's time rather than several.

    Structural, not arithmetic: while ``MAX_ITEMS_PER_BATCH <= COPY_CONCURRENCY`` every item in
    a batch starts immediately, so the batch costs its slowest object and nothing more. Raise
    the batch above the pool and the cost doubles at the first item over — a step change, not a
    gradient, which is the kind of thing a bytes-based bound cannot express at all.
    """
    assert transfer_config.MAX_ITEMS_PER_BATCH <= copy_mod.COPY_CONCURRENCY, (
        f"a batch of {transfer_config.MAX_ITEMS_PER_BATCH} on "
        f"{copy_mod.COPY_CONCURRENCY} workers takes "
        f"{math.ceil(transfer_config.MAX_ITEMS_PER_BATCH / copy_mod.COPY_CONCURRENCY)} rounds, "
        "so its worst case is a multiple of the slowest object rather than the object itself"
    )


def test_the_copy_timeout_constant_matches_the_deployed_verb():
    """Guards the guard above: the budget it divides by lives in locals.tf, not in Python.

    A `copy-objects` timeout lowered in Terraform while this constant stayed at 900 would
    leave the batch bound computing against a budget the verb no longer has.
    """
    locals_tf = os.path.join(
        _HERE, "..", "..", "infra", "modules", "table-share", "locals.tf"
    )
    with open(locals_tf) as handle:
        text = handle.read()

    assert re.search(
        rf'"copy-objects"\s*=\s*\{{[^}}]*timeout\s*=\s*{transfer_config.COPY_TIMEOUT_SECONDS}\b',
        text,
    ), f"locals.tf's copy-objects timeout is not {transfer_config.COPY_TIMEOUT_SECONDS}s"


# ── copy_batch ──────────────────────────────────────────────────────────────


def test_every_item_is_copied_to_its_own_destination():
    fake = _setup()
    out = copy_mod.copy_batch([_item("bob", "a.parquet"), _item("carol", "year=2025/b.parquet")], _FAILED)

    assert out == {"copied": 2, "failures": []}
    assert sorted((c["CopySource"]["Key"], c["Key"]) for c in fake.copies) == [
        ("alice/sales/a.parquet", "bob/shared_tables/orders/a.parquet"),
        ("alice/sales/year=2025/b.parquet", "carol/shared_tables/orders/year=2025/b.parquet"),
    ]
    assert fake.multipart == []


def test_a_large_object_still_multipart_copies():
    fake = _setup()
    size = 5 * GIB + 512
    copy_mod.copy_batch([_item(rel="big.parquet", size=size)], _FAILED)

    parts = [c for c in fake.multipart if "PartNumber" in c and "complete" not in c]
    complete = [c for c in fake.multipart if "complete" in c]
    assert fake.copies == []
    assert len(parts) == 6
    assert parts[0]["CopySourceRange"] == f"bytes=0-{GIB - 1}"
    assert parts[-1]["CopySourceRange"] == f"bytes={5 * GIB}-{size - 1}"
    assert [p["PartNumber"] for p in complete[0]["complete"]["MultipartUpload"]["Parts"]] == [1, 2, 3, 4, 5, 6]


# ── the per-item storage class (SPEC-169) ───────────────────────────────────


def test_an_item_with_no_storage_class_names_no_storage_class_at_all():
    """THE PROPERTY THE TWO EXISTING CALLERS DEPEND ON, and it is about the ABSENCE of a key
    rather than about a default value. Passing `StorageClass="STANDARD"` would also be
    "correct" and would change every table-share and file-send request; asserting the exact
    argument set is what keeps that honest.

    SPEC-171 ADDED `MetadataDirective` TO THAT SET, deliberately, and this test is the place
    that records it. It is S3's own default on this path, so no request's BEHAVIOUR changed —
    but it is stated rather than assumed because the multipart path beside it proves the
    default is not universal, and an argument set nobody pins is an argument set that drifts.
    """
    fake = _setup()

    copy_mod.copy_batch([_item()], _FAILED)

    assert set(fake.copies[0]) == {"Bucket", "Key", "CopySource", "MetadataDirective"}
    assert fake.copies[0]["MetadataDirective"] == "COPY"


def test_an_item_carrying_a_storage_class_passes_it_to_the_copy():
    fake = _setup()

    copy_mod.copy_batch([{**_item(), "storageClass": "GLACIER"}], _FAILED)

    assert fake.copies[0]["StorageClass"] == "GLACIER"


def test_the_storage_class_is_set_on_the_MULTIPART_CREATE_not_the_part_copies():
    """THE HALF AN OBVIOUS IMPLEMENTATION MISSES, and the failure it produces is silent and
    expensive. The class belongs to `CreateMultipartUpload`; the part copies inherit it, and
    `UploadPartCopy` does not accept it at all.

    Set on the single-copy path only, an archive would write every object under 5 GiB to
    GLACIER and every object OVER it to STANDARD — at roughly 20x the storage cost, with no
    error anywhere, and with SPEC-171's restore mysteriously unnecessary for exactly the
    biggest objects.
    """
    fake = _setup()
    creates = []
    real_create = fake.create_multipart_upload
    fake.create_multipart_upload = lambda **kw: creates.append(kw) or real_create(**kw)

    copy_mod.copy_batch(
        [{**_item(rel="big.parquet", size=6 * GIB), "storageClass": "GLACIER"}], _FAILED
    )

    assert creates[0]["StorageClass"] == "GLACIER"
    part_copies = [m for m in fake.multipart if "complete" not in m]
    assert part_copies, "the multipart path did not run — this test is measuring nothing"
    assert not any("StorageClass" in m for m in part_copies)


def test_a_large_object_with_no_storage_class_creates_the_upload_it_always_did():
    """The absence half of the multipart path, for the same reason as the single-copy one."""
    fake = _setup()
    creates = []
    real_create = fake.create_multipart_upload
    fake.create_multipart_upload = lambda **kw: creates.append(kw) or real_create(**kw)

    copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert set(creates[0]) == {"Bucket", "Key"}


# ── the metadata round trip (SPEC-171 FR-003 AC5) ───────────────────────────


def test_a_single_copy_carries_the_sources_metadata_by_directive():
    """`MetadataDirective: COPY` is S3's default here, and it is stated because the multipart
    path proves the default is not universal. Passing REPLACE with no metadata beside it would
    strip every object's content type on a copy that otherwise looked identical."""
    fake = _setup()

    copy_mod.copy_batch([_item()], _FAILED)

    assert fake.copies[0]["MetadataDirective"] == "COPY"
    assert fake.heads == [], "a single copy needs no HeadObject — the directive does the work"


def test_a_multipart_copy_restates_the_sources_content_type_and_metadata():
    """**THE LATENT BUG SPEC-171 SURFACED, and it was silent on all three planes.**
    `UploadPartCopy` moves bytes and nothing else, and `CreateMultipartUpload` has no
    `MetadataDirective` — so the destination's content type and user metadata are whatever the
    create call was told, and it was told nothing. Every object over MULTIPART_COPY_THRESHOLD
    came out as `binary/octet-stream` with its user metadata gone.

    It surfaced here because an archive round trip is the first operation in this repo that
    copies an object twice and hands it back to the user expecting it unchanged — a table share
    reads its objects through Athena, which does not care.
    """
    fake = _setup(
        source_headers={
            "ContentType": "text/csv; charset=utf-8",
            "Metadata": {"origin": "quarterly-export"},
            "ContentEncoding": "gzip",
        }
    )
    creates = []
    real_create = fake.create_multipart_upload
    fake.create_multipart_upload = lambda **kw: creates.append(kw) or real_create(**kw)

    copy_mod.copy_batch([_item(rel="big.csv", size=6 * GIB)], _FAILED)

    assert fake.heads, "the multipart path did not read the source — this test measures nothing"
    assert creates[0]["ContentType"] == "text/csv; charset=utf-8"
    assert creates[0]["Metadata"] == {"origin": "quarterly-export"}
    assert creates[0]["ContentEncoding"] == "gzip"


def test_a_content_type_survives_an_archive_then_a_restore_at_both_sizes():
    """FR-003 AC5's own scenario, run in both directions and at BOTH copy strategies — a test
    that fixtured only a small object would pass while the multipart path silently dropped
    everything, which is exactly the shape of the bug it is here to catch.

    The archive copy and the copy-back are the same function, so what this asserts is that two
    hops of it leave the content type where it started.
    """
    for size in (10, 6 * GIB):
        fake, creates = _round_trip(size)

        if size <= copy_mod.MULTIPART_COPY_THRESHOLD:
            assert [c["MetadataDirective"] for c in fake.copies] == ["COPY", "COPY"]
        else:
            assert [c["ContentType"] for c in creates] == [
                "application/x-parquet",
                "application/x-parquet",
            ]


def _round_trip(size):
    """Archives one object at GLACIER and restores it at STANDARD, recording both copies."""
    fake = _setup(source_headers={"ContentType": "application/x-parquet"})
    creates = []
    real_create = fake.create_multipart_upload

    def _observed(**kwargs):
        creates.append(kwargs)
        return real_create(**kwargs)

    fake.create_multipart_upload = _observed

    archived = {**_item(rel="q1.parquet", size=size), "storageClass": "GLACIER"}
    copy_mod.copy_batch([archived], _FAILED)
    copy_mod.copy_batch(
        [
            {
                **archived,
                "srcBucket": archived["destBucket"],
                "srcKey": archived["destKey"],
                "destBucket": "user-bkt",
                "destKey": "alice/sales/q1.parquet",
                "storageClass": "STANDARD",
            }
        ],
        _FAILED,
    )
    return fake, creates


def test_the_multipart_paths_new_HEAD_is_a_real_failure_point_and_is_handled():
    """**SPEC-171 added a pre-copy S3 call to a path two SHIPPED planes already use**, so its
    failure modes are theirs now too. A throttle must stay transient — the Map retries the whole
    idempotent batch — and a deterministic fault must fail THAT ITEM rather than producing an
    object stripped of the metadata this call exists to carry."""
    fake = _setup()
    fake.head_object = lambda **kw: (_ for _ in ()).throw(_S3Error("SlowDown"))

    with pytest.raises(TransientError):
        copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    fake = _setup()
    fake.head_object = lambda **kw: (_ for _ in ()).throw(_S3Error("NoSuchKey"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert out["copied"] == 0
    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]
    assert fake.multipart == [], "an unreadable source started a multipart upload anyway"


def test_a_source_header_the_object_does_not_carry_is_not_stamped_over_the_default():
    """An empty `ContentType` passed to `CreateMultipartUpload` would stamp the default over
    nothing, which is harmless — but an empty `Metadata` dict or `ContentDisposition` reads as
    an explicit instruction, and the argument set that shipped before SPEC-171 is the one the
    two existing callers' requests are pinned to."""
    fake = _setup()
    creates = []
    real_create = fake.create_multipart_upload
    fake.create_multipart_upload = lambda **kw: creates.append(kw) or real_create(**kw)

    copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert set(creates[0]) == {"Bucket", "Key"}


def test_the_storage_class_travels_per_ITEM_and_not_per_batch():
    """One manifest could in principle mix classes. Nothing does today, and the parameter is
    still per item rather than per call — a batch-level argument would be an invitation for a
    future caller to assume the wrong scope, and the engine has three callers now."""
    fake = _setup()

    copy_mod.copy_batch(
        [{**_item(rel="a.parquet"), "storageClass": "GLACIER"}, _item(rel="b.parquet")], _FAILED
    )

    assert [c.get("StorageClass") for c in fake.copies] == ["GLACIER", None]


def test_the_two_existing_planes_write_no_storage_class_into_their_manifests():
    """The other end of the same guarantee, asserted against the SOURCE of the two callers
    rather than against a fixture: absent in the manifest is what makes absent in the request."""
    lambdas = pathlib.Path(__file__).resolve().parent.parent
    for verb in ("table-share-build-transfer-manifest", "file-send-build-transfer-manifest"):
        body = "".join(p.read_text() for p in (lambdas / verb).glob("*.py") if not p.name.startswith("test_"))
        assert "storageClass" not in body, f"{verb} now sets a storage class"


def test_one_bad_item_never_costs_its_siblings_their_copy():
    """FR-003 AC3 — the batch SUCCEEDS and reports the failure per item."""
    fake = _setup(copy_error=lambda kwargs: _S3Error("AccessDenied") if "bad" in kwargs["Key"] else None)

    out = copy_mod.copy_batch(
        [_item("bob", "good-1.parquet"), _item("carol", "bad.parquet"), _item("bob", "good-2.parquet")],
        _FAILED,
    )

    assert out["copied"] == 2
    assert out["failures"] == [{"recipient": "carol", "kind": "user", "reason": _FAILED}]
    assert len(fake.copies) == 2


def test_a_failure_names_the_recipient_and_never_the_key():
    _setup(copy_error=_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item("bob", "secret-name.parquet")], _FAILED)
    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]


def test_a_throttled_item_raises_so_the_batch_retries():
    _setup(copy_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        copy_mod.copy_batch([_item()], _FAILED)


def test_a_malformed_line_fails_its_own_item_only():
    fake = _setup()
    out = copy_mod.copy_batch([{"recipient": "bob"}, _item("carol")], _FAILED)

    assert out["copied"] == 1
    assert out["failures"] == [{"recipient": "bob", "kind": None, "reason": _FAILED}]
    assert len(fake.copies) == 1


def test_a_failed_multipart_upload_is_aborted():
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]
    assert len(fake.aborted) == 1


def test_a_failed_abort_never_hides_the_copy_failure():
    """The abort is best-effort — an expired upload lifecycles away — but the item still fails."""
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    fake.abort_multipart_upload = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]


def test_the_pool_is_bounded():
    """Observed, not inferred (SPEC-153 FR-007): a serial loop satisfies a ceiling alone."""
    import threading
    import time

    lock = threading.Lock()
    state = {"in_flight": 0, "peak": 0}
    fake = _setup()
    real_copy = fake.copy_object

    def _observed(**kwargs):
        with lock:
            state["in_flight"] += 1
            state["peak"] = max(state["peak"], state["in_flight"])
        time.sleep(0.02)
        try:
            return real_copy(**kwargs)
        finally:
            with lock:
                state["in_flight"] -= 1

    fake.copy_object = _observed
    out = copy_mod.copy_batch([_item(rel=f"p{i}.parquet") for i in range(20)], _FAILED, concurrency=2)

    assert out["copied"] == 20
    assert state["peak"] <= 2, f"the pool exceeded its bound: {state['peak']} in flight"
    assert state["peak"] >= 2, f"the pool never saturated ({state['peak']}) — bound unproven"


# ── results ─────────────────────────────────────────────────────────────────


def _run_manifest(**groups):
    return {
        "MapRunArn": "arn:aws:states:us-east-1:1:mapRun/m/r",
        "ResultFiles": {group: [{"Key": key} for key in keys] for group, keys in groups.items()},
    }


def _succeeded_record(items, failures):
    return {
        "ExecutionArn": "arn:aws:states:us-east-1:1:execution:m:child",
        "Status": "SUCCEEDED",
        "Input": json.dumps({"Items": items}),
        "InputDetails": {"Included": True},
        "Output": json.dumps({"copied": len(items) - len(failures), "failures": failures}),
        "OutputDetails": {"Included": True},
    }


def _failed_record(items):
    return {
        "ExecutionArn": "arn:aws:states:us-east-1:1:execution:m:child",
        "Status": "FAILED",
        "Input": json.dumps({"Items": items}),
        "InputDetails": {"Included": True},
        "Output": None,
        "OutputDetails": {"Included": False},
    }


def _read(objects):
    """The failures alone — the item count is asserted where it is the point (below)."""
    return _read_outcome(objects)["failures"]


def _read_outcome(objects):
    _setup(objects=objects)
    return results_mod.read_failed_items(
        "admin-bkt",
        "table-share/h/exec/results/manifest.json",
        batch_failure_reason=_FAILED,
        unreadable_reason=_UNREADABLE,
    )


#: A REAL ``manifest.json``, transcribed byte-for-byte from the first live SPEC-160 share
#: (2026-08-10) and not reconstructed from the docs.
#:
#: It is here because this file's fixtures were written from AWS's documentation, which describes
#: the record fields and the ``SUCCEEDED_n``/``FAILED_n``/``PENDING_n`` grouping but **never shows
#: the ``ResultFiles`` object itself** — so the reader's top-level parse was corroborated rather
#: than demonstrated, and the delivery doc said so. This discharges it. Three things it settles
#: that a hand-written fixture could not:
#:
#: * ``ResultFiles`` really is a mapping of group name to a list of ``{Key, Size}``, and the
#:   empty groups are present as empty arrays rather than absent.
#: * ``Key`` is a **full key from the bucket root**, not relative to the prefix — which is what
#:   the reader assumes when it passes it straight back to ``get_object``.
#: * Step Functions appends ``{mapRunUuid}/`` UNDER the configured prefix. Nothing here depends
#:   on that (the manifest's own key comes from ``ResultWriterDetails``), and that independence
#:   is the point: the layout is AWS's to change.
_LIVE_MANIFEST = {
    "DestinationBucket": "dat-prod-athena-admin",
    "MapRunArn": "arn:aws:states:us-east-1:696000197480:mapRun:dat-prod-table-share-orchestrator/239693d7-7a1a-3ccf-8705-7d2523b25e6f:abd95259-b545-4817-977d-16541875576d",
    "ResultFiles": {
        "FAILED": [],
        "PENDING": [],
        "SUCCEEDED": [{
            "Key": "table-share/0312374ae1cca589ab95b27ea3e19031cfe859815334916fd5b4005d024931eb/a3ced512-87b1-5237-9f7a-b7e684027e95/results/abd95259-b545-4817-977d-16541875576d/SUCCEEDED_0.json",
            "Size": 1011,
        }],
    },
}


def test_the_reader_parses_a_real_map_run_manifest():
    """The premise this module was built on, DEMONSTRATED rather than read from the docs."""
    key = _LIVE_MANIFEST["ResultFiles"]["SUCCEEDED"][0]["Key"]
    _setup(objects={
        "results/manifest.json": _LIVE_MANIFEST,
        key: [_succeeded_record([_item("bob"), _item("bob")], [])],
    })

    outcome = results_mod.read_failed_items(
        "dat-prod-athena-admin",
        "results/manifest.json",
        batch_failure_reason=_FAILED,
        unreadable_reason=_UNREADABLE,
    )

    assert outcome == {"failures": [], "items": 2}


def test_the_live_manifests_key_is_read_as_an_absolute_key():
    """The one way this could have been wrong without anything else noticing.

    Had ``Key`` been relative to the ResultWriter prefix, the reader would have asked for the
    wrong object, got NoSuchKey, and — correctly, but for the wrong reason — failed every share
    with ``transfer_results_unreadable``. The live artifact shows it is absolute.
    """
    key = _LIVE_MANIFEST["ResultFiles"]["SUCCEEDED"][0]["Key"]

    assert key.startswith("table-share/")
    assert "/results/" in key and key.endswith("/SUCCEEDED_0.json")


def test_a_clean_run_reports_no_failures():
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
        "r/SUCCEEDED_0.json": [_succeeded_record([_item("bob")], [])],
    }) == []


def test_a_succeeded_batch_carrying_failures_is_still_attributed():
    """THE CASE A FAILED-ONLY COLLECTOR SILENTLY PASSES (FR-004 AC2).

    The batch verb succeeds while reporting per-item failures, so Step Functions files the
    child under SUCCEEDED. Reading only FAILED_n.json would report universal success while
    carol received an incomplete dataset and a table pointed at it.
    """
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
        "r/SUCCEEDED_0.json": [
            _succeeded_record(
                [_item("bob"), _item("carol")], [{"recipient": "carol", "kind": "user", "reason": _FAILED}]
            )
        ],
    }) == [{"recipient": "carol", "kind": "user", "reason": _FAILED}]


def test_a_whole_batch_failure_is_attributed_from_its_input():
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(FAILED=["r/FAILED_0.json"]),
        "r/FAILED_0.json": [_failed_record([_item("bob"), _item("carol")])],
    }) == [
        {"recipient": "bob", "kind": "user", "reason": _FAILED},
        {"recipient": "carol", "kind": "user", "reason": _FAILED},
    ]


def test_a_pending_batch_is_attributed_too():
    """A run stopped mid-flight leaves items that never ran; they did not copy either."""
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(PENDING=["r/PENDING_0.json"]),
        "r/PENDING_0.json": [_failed_record([_item("bob")])],
    }) == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]


def test_every_result_file_in_a_group_is_read():
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(
            SUCCEEDED=["r/SUCCEEDED_0.json", "r/SUCCEEDED_1.json"]
        ),
        "r/SUCCEEDED_0.json": [_succeeded_record([_item("bob")], [{"recipient": "bob", "reason": _FAILED}])],
        "r/SUCCEEDED_1.json": [_succeeded_record([_item("carol")], [{"recipient": "carol", "reason": _FAILED}])],
    }) == [
        {"recipient": "bob", "reason": _FAILED},
        {"recipient": "carol", "reason": _FAILED},
    ]


def test_an_omitted_output_is_unattributable_not_success():
    """FR-004 AC3 — a payload Step Functions declined to export is never 'no failures found'."""
    record = _succeeded_record([_item("bob")], [])
    record["OutputDetails"] = {"Included": False}
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
            "r/SUCCEEDED_0.json": [record],
        })
    assert caught.value.reason == _UNREADABLE


def test_an_omitted_input_on_a_failed_batch_is_unattributable():
    record = _failed_record([_item("bob")])
    record["InputDetails"] = {"Included": False}
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(FAILED=["r/FAILED_0.json"]),
            "r/FAILED_0.json": [record],
        })
    assert caught.value.reason == _UNREADABLE


def test_an_absent_results_manifest_fails_the_request():
    """FR-004 AC7 — never a silent 'everything succeeded'."""
    with pytest.raises(TerminalError) as caught:
        _read({})
    assert caught.value.reason == _UNREADABLE


def test_a_corrupt_results_manifest_fails_the_request():
    with pytest.raises(TerminalError) as caught:
        _read({"table-share/h/exec/results/manifest.json": b"{not json"})
    assert caught.value.reason == _UNREADABLE


def test_a_manifest_listing_no_files_fails_the_request():
    with pytest.raises(TerminalError) as caught:
        _read({"table-share/h/exec/results/manifest.json": {"MapRunArn": "arn"}})
    assert caught.value.reason == _UNREADABLE


@pytest.mark.parametrize(
    "record",
    [
        {"Status": "SUCCEEDED", "Output": "", "OutputDetails": {"Included": True}},
        {"Status": "SUCCEEDED", "Output": "{not json", "OutputDetails": {"Included": True}},
        {"Status": "SUCCEEDED", "Output": "[1,2]", "OutputDetails": {"Included": True}},
    ],
    ids=["absent", "unparseable", "not-an-object"],
)
def test_an_unusable_output_payload_is_unattributable(record):
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
            "r/SUCCEEDED_0.json": [record],
        })
    assert caught.value.reason == _UNREADABLE


def test_a_failed_record_with_no_item_batch_is_unattributable():
    record = _failed_record([])
    record["Input"] = json.dumps({"NotItems": []})
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(FAILED=["r/FAILED_0.json"]),
            "r/FAILED_0.json": [record],
        })
    assert caught.value.reason == _UNREADABLE


def test_an_already_parsed_output_is_accepted():
    """Tolerated because a caller's fixture (and a future export format) may hand back an
    object rather than the embedded JSON string Step Functions writes today."""
    record = _succeeded_record([_item("bob")], [])
    record["Output"] = {"copied": 0, "failures": [{"recipient": "bob", "reason": _FAILED}]}
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
        "r/SUCCEEDED_0.json": [record],
    }) == [{"recipient": "bob", "reason": _FAILED}]


def test_a_result_file_entry_with_no_key_is_unattributable():
    """An entry naming no object is a shape this reader does not understand.

    Skipping it is the tempting move and it is the wrong direction: the batches in that file are
    then simply never read, and a run with real failures reports clean.
    """
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": {
                "ResultFiles": {"SUCCEEDED": [{"Size": 0}]},
            },
        })
    assert caught.value.reason == _UNREADABLE


def test_a_result_file_that_is_not_a_list_of_records_is_unattributable():
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
            "r/SUCCEEDED_0.json": {"not": "a list"},
        })
    assert caught.value.reason == _UNREADABLE


def test_a_succeeded_record_with_no_item_count_is_unattributable():
    """The count is what lets the caller check the export against the manifest it wrote."""
    record = _succeeded_record([_item("bob")], [])
    record["Output"] = json.dumps({"failures": []})
    with pytest.raises(TerminalError) as caught:
        _read({
            "table-share/h/exec/results/manifest.json": _run_manifest(SUCCEEDED=["r/SUCCEEDED_0.json"]),
            "r/SUCCEEDED_0.json": [record],
        })
    assert caught.value.reason == _UNREADABLE


def test_the_reader_reports_how_many_items_the_export_accounted_for():
    """The number the collector reconciles against its manifest — a well-formed export covering
    only some batches is the one silent-success path a shape check cannot catch."""
    outcome = _read_outcome({
        "table-share/h/exec/results/manifest.json": _run_manifest(
            SUCCEEDED=["r/SUCCEEDED_0.json"], FAILED=["r/FAILED_0.json"]
        ),
        "r/SUCCEEDED_0.json": [
            _succeeded_record([_item("bob"), _item("bob")], [{"recipient": "bob", "reason": _FAILED}])
        ],
        "r/FAILED_0.json": [_failed_record([_item("carol")])],
    })

    assert outcome["items"] == 3
    assert len(outcome["failures"]) == 2


def test_a_throttled_results_read_is_transient():
    _setup(get_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        results_mod.read_failed_items(
            "admin-bkt",
            "k.json",
            batch_failure_reason=_FAILED,
            unreadable_reason=_UNREADABLE,
        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── results_location — the Map state's export pointer ────────────────────────
#
# Consolidates the reader all three collectors carried: archive as its own `_results_location`,
# file-send and table-share inline. Each plane keeps the test that its collector refuses when the
# pointer is absent; the reader itself is asserted once here.


def test_the_bucket_and_key_come_off_the_map_states_result_writer_details():
    event = {"mapRun": {"ResultWriterDetails": {"Bucket": "admin-bkt", "Key": "r/manifest.json"}}}

    assert results_mod.results_location(event, unreadable_reason=_UNREADABLE) == (
        "admin-bkt",
        "r/manifest.json",
    )


@pytest.mark.parametrize(
    "event",
    [
        {},
        {"mapRun": None},
        {"mapRun": {}},
        {"mapRun": {"ResultWriterDetails": None}},
        {"mapRun": {"ResultWriterDetails": {"Bucket": "admin-bkt"}}},
        {"mapRun": {"ResultWriterDetails": {"Key": "r/manifest.json"}}},
        {"mapRun": {"ResultWriterDetails": {"Bucket": "", "Key": "r/manifest.json"}}},
    ],
    ids=[
        "no-map-run",
        "null-map-run",
        "no-result-writer-details",
        "null-result-writer-details",
        "no-key",
        "no-bucket",
        "blank-bucket",
    ],
)
def test_an_absent_pointer_is_terminal_rather_than_transient(event):
    """The run has FINISHED by the time a collector is invoked, so an absent pointer is a fault
    rather than a race — and retrying against a finished run would never resolve."""
    with pytest.raises(TerminalError) as caught:
        results_mod.results_location(event, unreadable_reason=_UNREADABLE)

    assert caught.value.reason == _UNREADABLE


def test_the_reason_code_is_the_callers_and_never_this_layers():
    """The engine takes every domain reason code as a parameter, so a plane's own registered
    wording reaches the user rather than a shared string this layer invented."""
    messages.register({"a_second_planes_wording": "somebody else's sentence."}, prefix="Test: ")

    with pytest.raises(TerminalError) as caught:
        results_mod.results_location({}, unreadable_reason="a_second_planes_wording")

    assert caught.value.reason == "a_second_planes_wording"
