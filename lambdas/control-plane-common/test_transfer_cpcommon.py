"""Unit tests for the shared transfer engine (SPEC-160).

The manifest writer's file format, the batch copier's failure isolation, and the result
reader's two attribution paths — including the one a FAILED-only collector silently passes.
AWS is stubbed with a recording fake.
"""

import hashlib
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
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import clients, config, messages
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

#: The attribution vocabulary these tests exercise. The engine no longer has one of its own
#: (SPEC-189), so the suite passes a caller's — table-share's, which is what it was written
#: against — and two dedicated tests below cover a DIFFERENT set and the empty set.
_ECHO = ("recipient", "kind")

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
    batch = json.dumps({
        # SPEC-225 put the run's traceparent and the request id in the child's input
        # alongside `Items`, so the payload this bound is computed against grew. Modelled
        # rather than assumed negligible: a cap is computed against what it actually bounds.
        "BatchInput": {
            "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01",
            "requestId": "0" * 36,
        },
        "Items": [worst] * transfer_config.MAX_ITEMS_PER_BATCH,
    })
    assert len(batch.encode()) < config.STATE_PAYLOAD_LIMIT_BYTES // 2, (
        "a worst-case batch is not far below the limit"
    )


def test_a_worst_case_batch_stays_under_the_limit_with_the_WIDEST_echoed_field():
    """SPEC-189: the bound above was computed against table-share's vocabulary, and the engine no
    longer has one.

    A caller now names the fields echoed onto a failure record, and those fields ride the manifest
    line INTO the child input — so the payload the bound was computed against grows by whatever the
    widest caller echoes. The file-operations plane echoes ``itemKey``, which is an S3 key and may
    be 1024 bytes, on every item. Recomputed here rather than assumed still-true, because the
    original bound's own docstring says raising the batch size without re-checking must fail.

    Re-derived again for SPEC-225's `BatchInput`, on the same principle: the child's input went
    from 26,403 to 26,546 bytes at `MAX_ITEMS_PER_BATCH`, which is 20.3% of the bar. The block is
    per-BATCH rather than per-item, so it does not scale with the batch size — which is exactly
    why the traceparent travels here and not on every manifest line.
    """
    worst = {
        "itemKey": "i" * 1024,
        "srcBucket": "b" * 63,
        "srcKey": "s" * 1024,
        "destBucket": "d" * 63,
        "destKey": "k" * 1024,
        "size": 5 * GIB,
    }
    batch = json.dumps({
        # SPEC-225 put the run's traceparent and the request id in the child's input
        # alongside `Items`, so the payload this bound is computed against grew. Modelled
        # rather than assumed negligible: a cap is computed against what it actually bounds.
        "BatchInput": {
            "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01",
            "requestId": "0" * 36,
        },
        "Items": [worst] * transfer_config.MAX_ITEMS_PER_BATCH,
    })
    assert len(batch.encode()) < config.STATE_PAYLOAD_LIMIT_BYTES // 2, (
        "a worst-case batch carrying the widest echoed field is no longer far below the limit"
    )


def test_the_engine_echoes_the_CALLERS_fields_and_nothing_of_its_own(monkeypatch):
    """SPEC-189 FR-002: the attribution vocabulary belongs to the plane, not to cpcommon.

    Asserted by rendering, not argued (SPEC-156's precedent): the record a failure produces must
    carry exactly the caller's fields plus the reason, in that order, and no field the engine
    decided on its own.
    """
    def boom(item):
        raise RuntimeError("deterministic")

    monkeypatch.setattr(copy_mod, "_copy_item", boom)
    item = {"itemKey": "alice/reports/", "recipient": "bob", "kind": "user", "srcKey": "x"}

    outcome = copy_mod.copy_batch([item], "copy_failed", echo_fields=("itemKey",))

    assert outcome["failures"] == [{"itemKey": "alice/reports/", "reason": "copy_failed"}]
    assert list(outcome["failures"][0]) == ["itemKey", "reason"]


def test_an_EMPTY_echo_set_drops_the_two_nulls_the_archive_used_to_emit(monkeypatch):
    """SPEC-189 FR-002's NAMED exception: an empty echo set writes no attribution at all.

    The archive's manifest carries no recipient and no kind — it has one destination — so the
    hardcoded engine wrote ``{"recipient": null, "kind": null, "reason": ...}`` onto every archive
    failure. An empty set removes both, for any caller with one destination. The archive itself
    now echoes a single field, its boolean folder flag, and still writes neither null. This test
    exists so the empty set reads as intended rather than as a regression someone repairs.
    """
    def boom(item):
        raise RuntimeError("deterministic")

    monkeypatch.setattr(copy_mod, "_copy_item", boom)

    outcome = copy_mod.copy_batch([{"srcKey": "x"}], "copy_failed", echo_fields=())

    assert outcome["failures"] == [{"reason": "copy_failed"}]
    assert "recipient" not in outcome["failures"][0]


def test_the_two_HALVES_of_the_export_produce_the_SAME_record_shape(monkeypatch):
    """A batch that failed as a whole is attributed from its INPUT and one that succeeded from its
    OUTPUT, and the caller joins both into one list.

    So the two halves must agree on the record shape. They are separately implemented — the output
    half copies what the batch verb already wrote, the input half rebuilds it — which is exactly
    the pair that drifts, and a drifted record is one the caller silently cannot attribute.
    """
    fields = ("itemKey",)

    def boom(item):
        raise RuntimeError("deterministic")

    monkeypatch.setattr(copy_mod, "_copy_item", boom)
    from_output = copy_mod.copy_batch(
        [{"itemKey": "alice/a/"}], "copy_failed", echo_fields=fields
    )["failures"]

    from_input, covered = results_mod._from_input(
        {"Input": json.dumps({"Items": [{"itemKey": "alice/a/"}]})},
        "copy_failed",
        "transfer_results_unreadable",
        fields,
    )

    assert [list(r) for r in from_output] == [list(r) for r in from_input]
    assert from_output == from_input
    assert covered == 1


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


#: Every plane that deploys a `copy-objects` verb on the shared engine. FROZEN, and compared by
#: set EQUALITY rather than counted: a count is satisfied by any four planes, so a plane added
#: while another quietly stopped importing the engine would leave the new one unchecked and the
#: guard green. A fifth plane failing here is the guard working — add it, having checked its
#: timeout is the one the batch bound is computed against.
_COPY_OBJECTS_PLANES = frozenset({"archive", "file-ops", "file-send", "table-share"})

#: An actual import of the shared engine, anchored to the start of a line. A substring test over
#: the whole module was the first attempt and it was vacuous on three of the four planes: their
#: module docstrings NAME ``cpcommon.transfer.copy`` in prose, so deleting the real import left
#: them counted. The population half of the check is only as good as this pattern.
_IMPORTS_THE_ENGINE = re.compile(
    r"^\s*(?:from cpcommon\.transfer import"
    r"|from cpcommon import transfer"
    r"|import cpcommon\.transfer)",
    re.MULTILINE,
)

_REPO = pathlib.Path(_HERE).parent.parent


def _planes_deploying_a_copy_verb() -> dict:
    """Every plane whose Terraform deploys a `copy-objects` verb running the shared engine.

    DERIVED from the two artefacts that decide it, rather than from a list: the Terraform row is
    what deploys the verb, and an import of the engine is what makes the verb run THIS one. A
    guard naming a single plane is a guard the other planes believe they have.

    Every read is guarded, and a row this cannot parse is REPORTED rather than skipped. The
    unguarded version raised a bare AttributeError from a module with no relationship to the
    engine — the glob reaches all thirteen ``infra/modules/*/locals.tf`` — which is a crash in a
    shared suite for an ordinary edit somewhere else.

    Args:
      None.

    Returns:
      ``(planes, unparsable)`` — a plane-name-to-configured-timeout map, and the rows that could
      not be read, which the caller reports rather than silently dropping.

    Raises:
      None.
    """
    found: dict[str, int] = {}
    unparsable: list[str] = []
    for locals_tf in sorted((_REPO / "infra" / "modules").glob("*/locals.tf")):
        plane = locals_tf.parent.name
        # Comment lines come off first: `re.search` takes the FIRST match in the file, so a
        # commented-out row left above a live one is the row this guard reads — and the live one
        # can then say anything. Measured: a ghost row let a 600s timeout pass.
        live = "\n".join(
            line for line in locals_tf.read_text().split("\n")
            if not line.lstrip().startswith(("#", "//"))
        )
        row = re.search(r'"copy-objects"\s*=\s*\{([^}]*)\}', live)
        if not row:
            continue
        handler = re.search(r'handler\s*=\s*"([A-Za-z0-9_]+)\.handler"', row.group(1))
        timeout = re.search(r"timeout\s*=\s*(\d+)", row.group(1))
        if not handler or not timeout:
            unparsable.append(f"{plane} (no readable handler or timeout in its copy-objects row)")
            continue
        module = _REPO / "lambdas" / f"{plane}-copy-objects" / f"{handler.group(1)}.py"
        if not module.exists():
            unparsable.append(f"{plane} (no {module.name} under {plane}-copy-objects/)")
            continue
        if not _IMPORTS_THE_ENGINE.search(module.read_text()):
            continue
        found[plane] = int(timeout.group(1))
    return found, unparsable


def test_every_plane_running_the_engine_deploys_the_timeout_it_divides_by():
    """The budget MAX_ITEMS_PER_BATCH is computed against lives in Terraform, once per plane.

    A `copy-objects` timeout moved on any plane while this constant stayed at 900 would leave
    that plane's batch bound computing against a budget its verb no longer has.

    The guard this replaced read table-share's locals ALONE. Two of the other three have since
    grown their own plane-local check, so what this closes is file-send's row, which was held by
    nothing — and the shape, which is the part that matters: four planes each holding one number
    in their own suite is four places to forget, and the fifth plane to deploy the verb would
    have arrived unchecked and silent. Deriving the population puts the question in one place and
    makes a new plane LOUD.
    """
    deployed, unparsable = _planes_deploying_a_copy_verb()

    assert not unparsable, (
        f"a copy-objects row could not be read: {unparsable}. This guard derives its population "
        "from the Terraform, so an unreadable row would silently drop a plane rather than fail — "
        "fix the row, or teach _planes_deploying_a_copy_verb the shape it now takes"
    )
    assert set(deployed) == _COPY_OBJECTS_PLANES, (
        f"the planes running the shared copy engine are {sorted(deployed)}, not "
        f"{sorted(_COPY_OBJECTS_PLANES)}. A plane joined, left, renamed its handler, or stopped "
        "importing cpcommon.transfer. If it JOINED, check its copy-objects timeout is the budget "
        "MAX_ITEMS_PER_BATCH is computed against and add it to _COPY_OBJECTS_PLANES in this file; "
        "the population is frozen so that change is argued rather than absorbed"
    )
    wrong = {p: t for p, t in deployed.items() if t != transfer_config.COPY_TIMEOUT_SECONDS}
    assert not wrong, (
        f"{wrong} disagree with COPY_TIMEOUT_SECONDS "
        f"({transfer_config.COPY_TIMEOUT_SECONDS}s), which sizes MAX_ITEMS_PER_BATCH"
    )


# ── copy_batch ──────────────────────────────────────────────────────────────


def test_every_item_is_copied_to_its_own_destination():
    fake = _setup()
    out = copy_mod.copy_batch([_item("bob", "a.parquet"), _item("carol", "year=2025/b.parquet")], _FAILED, echo_fields=_ECHO)

    assert out == {"copied": 2, "failures": []}
    assert sorted((c["CopySource"]["Key"], c["Key"]) for c in fake.copies) == [
        ("alice/sales/a.parquet", "bob/shared_tables/orders/a.parquet"),
        ("alice/sales/year=2025/b.parquet", "carol/shared_tables/orders/year=2025/b.parquet"),
    ]
    assert fake.multipart == []


def test_a_large_object_still_multipart_copies():
    fake = _setup()
    size = 5 * GIB + 512
    copy_mod.copy_batch([_item(rel="big.parquet", size=size)], _FAILED, echo_fields=_ECHO)

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

    copy_mod.copy_batch([_item()], _FAILED, echo_fields=_ECHO)

    assert set(fake.copies[0]) == {"Bucket", "Key", "CopySource", "MetadataDirective"}
    assert fake.copies[0]["MetadataDirective"] == "COPY"


def test_an_item_carrying_a_storage_class_passes_it_to_the_copy():
    fake = _setup()

    copy_mod.copy_batch([{**_item(), "storageClass": "GLACIER"}], _FAILED, echo_fields=_ECHO)

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
        [{**_item(rel="big.parquet", size=6 * GIB), "storageClass": "GLACIER"}],
        _FAILED,
        echo_fields=_ECHO,
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

    copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    assert set(creates[0]) == {"Bucket", "Key"}


# ── the metadata round trip (SPEC-171 FR-003 AC5) ───────────────────────────


def test_a_single_copy_carries_the_sources_metadata_by_directive():
    """`MetadataDirective: COPY` is S3's default here, and it is stated because the multipart
    path proves the default is not universal. Passing REPLACE with no metadata beside it would
    strip every object's content type on a copy that otherwise looked identical."""
    fake = _setup()

    copy_mod.copy_batch([_item()], _FAILED, echo_fields=_ECHO)

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

    copy_mod.copy_batch([_item(rel="big.csv", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

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
    copy_mod.copy_batch([archived], _FAILED, echo_fields=_ECHO)
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
        echo_fields=_ECHO,
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
        copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    fake = _setup()
    fake.head_object = lambda **kw: (_ for _ in ()).throw(_S3Error("NoSuchKey"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

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

    copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    assert set(creates[0]) == {"Bucket", "Key"}


def test_the_storage_class_travels_per_ITEM_and_not_per_batch():
    """One manifest could in principle mix classes. Nothing does today, and the parameter is
    still per item rather than per call — a batch-level argument would be an invitation for a
    future caller to assume the wrong scope, and the engine has three callers now."""
    fake = _setup()

    copy_mod.copy_batch(
        [{**_item(rel="a.parquet"), "storageClass": "GLACIER"}, _item(rel="b.parquet")],
        _FAILED,
        echo_fields=_ECHO,
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
        echo_fields=_ECHO,
    )

    assert out["copied"] == 2
    assert out["failures"] == [{"recipient": "carol", "kind": "user", "reason": _FAILED}]
    assert len(fake.copies) == 2


def test_a_failure_names_the_recipient_and_never_the_key():
    _setup(copy_error=_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item("bob", "secret-name.parquet")], _FAILED, echo_fields=_ECHO)
    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]


def test_a_throttled_item_raises_so_the_batch_retries():
    _setup(copy_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        copy_mod.copy_batch([_item()], _FAILED, echo_fields=_ECHO)


def test_a_throttled_multipart_create_raises_so_the_batch_retries(caplog):
    """The create is the one multipart call with no upload behind it yet, so a throttle there must
    still retry the batch — failing the item rolls a whole archive back — and must not reach the
    abort, which would run against an upload id that was never assigned. A deterministic fault
    still fails only its own item."""
    fake = _setup()
    fake.create_multipart_upload = lambda **kw: (_ for _ in ()).throw(_S3Error("SlowDown"))

    with pytest.raises(TransientError, match=r"-> user-bkt/bob/shared_tables/orders/big\.parquet: transient SlowDown"):
        copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    assert fake.multipart == [] and fake.aborted == []
    assert "abort_multipart_upload failed" not in caplog.text

    fake = _setup()
    fake.create_multipart_upload = lambda **kw: (_ for _ in ()).throw(_S3Error("AccessDenied"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    assert out == {"copied": 0, "failures": [{"recipient": "bob", "kind": "user", "reason": _FAILED}]}
    assert "big.parquet: AccessDenied" in caplog.text
    assert "abort_multipart_upload failed" not in caplog.text


def test_a_malformed_line_fails_its_own_item_only():
    fake = _setup()
    out = copy_mod.copy_batch([{"recipient": "bob"}, _item("carol")], _FAILED, echo_fields=_ECHO)

    assert out["copied"] == 1
    assert out["failures"] == [{"recipient": "bob", "kind": None, "reason": _FAILED}]
    assert len(fake.copies) == 1


def test_a_failed_multipart_upload_is_aborted():
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]
    assert len(fake.aborted) == 1


def test_a_failed_abort_never_hides_the_copy_failure():
    """The abort is best-effort — an expired upload lifecycles away — but the item still fails."""
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    fake.abort_multipart_upload = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

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
    out = copy_mod.copy_batch([_item(rel=f"p{i}.parquet") for i in range(20)], _FAILED, echo_fields=_ECHO, concurrency=2)

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
        echo_fields=_ECHO,
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
        echo_fields=_ECHO,
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
            echo_fields=_ECHO,
        )


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


# ── the conditional copy (SPEC-237) ─────────────────────────────────────────


_OCCUPIED = "destination_occupied_during_copy"

messages.register_reasons([_OCCUPIED])


def _conditional(rel="part-0.parquet", size=10, **overrides):
    """A manifest line that refuses to overwrite, as a restore's copy-back writes it."""
    return {**_item(rel=rel, size=size), "ifAbsent": True, **overrides}


def test_a_conditional_line_under_the_threshold_conditions_the_copy_object():
    """FR-001 AC1. Asserted on the ARGUMENT SET rather than on "a copy happened": the whole
    behaviour is one header, so a test that only counted calls would pass with it missing."""
    fake = _setup()

    copy_mod.copy_batch([_conditional()], _FAILED, echo_fields=_ECHO)

    assert set(fake.copies[0]) == {"Bucket", "Key", "CopySource", "MetadataDirective", "IfNoneMatch"}
    assert fake.copies[0]["IfNoneMatch"] == "*"
    assert fake.multipart == []


def test_a_conditional_line_over_the_threshold_conditions_ONLY_the_completion():
    """FR-001 AC1, and the half an obvious implementation gets wrong in both directions. S3
    accepts the condition on neither ``CreateMultipartUpload`` nor ``UploadPartCopy`` — passing it
    there is rejected — and omitting it from the completion leaves a multipart copy overwriting
    silently while every object under 5 GiB is protected."""
    fake = _setup()
    creates = []
    real_create = fake.create_multipart_upload
    fake.create_multipart_upload = lambda **kw: creates.append(kw) or real_create(**kw)

    copy_mod.copy_batch([_conditional(rel="big.parquet", size=6 * GIB)], _FAILED, echo_fields=_ECHO)

    completions = [m["complete"] for m in fake.multipart if "complete" in m]
    part_copies = [m for m in fake.multipart if "complete" not in m]
    assert fake.copies == []
    assert part_copies, "the multipart path did not run — this test is measuring nothing"
    assert completions[0]["IfNoneMatch"] == "*"
    assert not any("IfNoneMatch" in create for create in creates)
    assert not any("IfNoneMatch" in part for part in part_copies)


@pytest.mark.parametrize("line", [_item(), {**_item(), "ifAbsent": False}], ids=["absent", "false"])
def test_a_line_that_asks_for_no_condition_issues_exactly_the_request_it_always_did(line):
    """THE PROPERTY THE FOUR EXISTING CALLERS DEPEND ON, asserted the way the storage class's
    equivalent is: on the exact argument set, not on a call count. A neighbouring code path
    produces the same count."""
    fake = _setup()

    copy_mod.copy_batch([line], _FAILED, echo_fields=_ECHO)

    assert set(fake.copies[0]) == {"Bucket", "Key", "CopySource", "MetadataDirective"}


@pytest.mark.parametrize("size", [10, 6 * GIB], ids=["single", "multipart"])
def test_a_line_that_asks_for_no_condition_issues_the_same_multipart_requests_too(size):
    fake = _setup()

    copy_mod.copy_batch([_item(rel="f.parquet", size=size)], _FAILED, echo_fields=_ECHO)

    issued = fake.copies + list(fake.multipart)
    assert issued, "nothing was issued — this test is measuring nothing"
    assert not any("IfNoneMatch" in str(request) for request in issued)


def test_a_non_boolean_ifAbsent_fails_its_item_and_issues_no_copy():
    """FR-001 AC3. Both ways to be lenient are worse than a reported failure: a truthy string
    would condition a copy nobody asked to condition, and an unrecognised value read as False
    turns a line that asked not to overwrite into one that does."""
    fake = _setup()

    out = copy_mod.copy_batch(
        [{**_item(), "ifAbsent": "true"}, _item(recipient="carol")], _FAILED, echo_fields=_ECHO
    )

    assert out["copied"] == 1
    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]
    assert len(fake.copies) == 1


def test_a_conflict_on_a_conditional_write_retries_the_batch():
    """FR-001 AC4. S3 documents the conflict as retryable on both conditioned operations — it is
    an answer about the race, not about the object — so reading it as occupied would turn a write
    race with this run's OWN earlier attempt into a false collision."""
    _setup(copy_error=_S3Error("ConditionalRequestConflict"))

    with pytest.raises(TransientError):
        copy_mod.copy_batch([_conditional()], _FAILED, echo_fields=_ECHO)


def test_the_same_conflict_on_an_UNconditional_line_is_classified_as_it_always_was():
    """The other half of AC4: the classification only changes where a condition was asked for."""
    _setup(copy_error=_S3Error("ConditionalRequestConflict"))

    out = copy_mod.copy_batch([_item()], _FAILED, echo_fields=_ECHO)

    assert out["failures"] == [{"recipient": "bob", "kind": "user", "reason": _FAILED}]


# ── resolving a refused write (FR-002) ──────────────────────────────────────
#
# The fake below honours ``IfNoneMatch`` and computes ETags the way SSE-S3 does, over REAL
# bytes: the MD5 of the object for a single copy, and the MD5 of the concatenated part MD5s
# with ``-N`` for a multipart one. The thresholds are shrunk so the multipart arithmetic runs on
# bytes a test can hold, rather than on a synthetic stand-in for 5 GiB — an ETag model that
# agreed with itself by construction would prove nothing about the comparison it feeds.
#
# Every bucket in this repo is AES256, which is what makes an ETag content-derived and this
# whole resolution possible; under SSE-KMS it is not, and every retried item would read as
# occupied.

_TINY_THRESHOLD = 8
_TINY_PART = 4


def _md5(payload: bytes):
    """MD5 as S3 computes an ETag with it, declared as NOT a security control.

    ``usedforsecurity=False`` is the honest statement and not a way past a scanner: nothing here
    authenticates, signs or protects anything. It models the algorithm S3 uses to derive an ETag
    under ``AES256``, so that this fake's tags have the same structure and derivation as the ones
    the production code compares — which is the whole reason the fake computes them rather than
    inventing opaque strings.

    Args:
      payload: The bytes to digest.

    Returns:
      The hash object.

    Raises:
      None.
    """
    return hashlib.md5(payload, usedforsecurity=False)


def _single_etag(body: bytes) -> str:
    return '"' + _md5(body).hexdigest() + '"'


def _multipart_etag(body: bytes, part_size: int) -> str:
    parts = [body[i : i + part_size] for i in range(0, len(body), part_size)]
    joined = b"".join(_md5(part).digest() for part in parts)
    return '"' + _md5(joined).hexdigest() + f'-{len(parts)}"'


class _ConditionalS3:
    """An S3 fake that refuses a conditional write over an existing key and computes real ETags.

    ``writes`` records every key this fake actually stored, which is how a test asserts that a
    refused copy left the destination ALONE rather than merely reporting that it did.
    """

    def __init__(self, part_size=_TINY_PART):
        self.objects = {}
        self.writes = []
        self.aborted = []
        self.head_errors = {}
        self.transient_once = set()
        self._uploads = {}
        self._part_size = part_size

    def seed(self, bucket, key, body, content_type="text/csv", metadata=None, multipart=False):
        """Puts an object there with the ETag the copy engine itself would have produced.

        ``multipart`` is how a vault object written by this same engine above the threshold is
        modelled: its ETag is composite, and the copy-back re-parts at the same size, which is
        the property that makes the two agree.
        """
        self.objects[(bucket, key)] = {
            "body": body,
            "ContentType": content_type,
            "Metadata": metadata or {},
            "ETag": _multipart_etag(body, self._part_size) if multipart else _single_etag(body),
        }

    def head_object(self, Bucket, Key):
        error = self.head_errors.get((Bucket, Key))
        if error:
            raise error
        try:
            stored = self.objects[(Bucket, Key)]
        except KeyError as err:
            raise _S3Error("NotFound") from err
        return {
            "ETag": stored["ETag"],
            "ContentLength": len(stored["body"]),
            "ContentType": stored["ContentType"],
            "Metadata": stored["Metadata"],
        }

    def _refuse_if_taken(self, kwargs, bucket, key):
        if kwargs.get("IfNoneMatch") == "*" and (bucket, key) in self.objects:
            raise _S3Error("PreconditionFailed")

    def _maybe_transient(self, key):
        if key in self.transient_once:
            self.transient_once.discard(key)
            raise _S3Error("SlowDown")

    def copy_object(self, Bucket, Key, CopySource, **kwargs):
        self._maybe_transient(Key)
        self._refuse_if_taken(kwargs, Bucket, Key)
        source = self.objects[(CopySource["Bucket"], CopySource["Key"])]
        self.objects[(Bucket, Key)] = {
            **source,
            "ETag": _single_etag(source["body"]),
        }
        self.writes.append(Key)

    def create_multipart_upload(self, Bucket, Key, **kwargs):
        upload_id = f"u{len(self._uploads) + 1}"
        self._uploads[upload_id] = {
            "Bucket": Bucket,
            "Key": Key,
            "ContentType": kwargs.get("ContentType", "binary/octet-stream"),
            "Metadata": kwargs.get("Metadata", {}),
            "parts": [],
        }
        return {"UploadId": upload_id}

    def upload_part_copy(self, Bucket, Key, UploadId, PartNumber, CopySource, CopySourceRange):
        start, end = (int(n) for n in CopySourceRange.removeprefix("bytes=").split("-"))
        chunk = self.objects[(CopySource["Bucket"], CopySource["Key"])]["body"][start : end + 1]
        self._uploads[UploadId]["parts"].append(chunk)
        return {"CopyPartResult": {"ETag": _single_etag(chunk)}}

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload, **kwargs):
        self._maybe_transient(Key)
        self._refuse_if_taken(kwargs, Bucket, Key)
        upload = self._uploads[UploadId]
        body = b"".join(upload["parts"])
        joined = b"".join(_md5(part).digest() for part in upload["parts"])
        self.objects[(Bucket, Key)] = {
            "body": body,
            "ContentType": upload["ContentType"],
            "Metadata": upload["Metadata"],
            "ETag": '"' + _md5(joined).hexdigest() + f'-{len(upload["parts"])}"',
        }
        self.writes.append(Key)

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.aborted.append(Key)
        self._uploads.pop(UploadId, None)


@pytest.fixture
def conditional(monkeypatch):
    """Installs the honouring fake with thresholds small enough for real bytes to flow."""
    monkeypatch.setattr(copy_mod, "MULTIPART_COPY_THRESHOLD", _TINY_THRESHOLD)
    monkeypatch.setattr(copy_mod, "MULTIPART_PART_SIZE", _TINY_PART)
    fake = _ConditionalS3()
    clients._s3 = fake
    return fake


def _restore_line(key, size, dest="alice/reports/a.csv"):
    return {
        "srcBucket": "archive-bkt",
        "srcKey": key,
        "destBucket": "user-bkt",
        "destKey": dest,
        "size": size,
        "ifAbsent": True,
    }


@pytest.mark.parametrize(
    ("size", "body"),
    [(6, b"abcdef"), (12, b"abcdefghijkl")],
    ids=["single-copy", "multipart-copy"],
)
def test_a_batch_RETRIED_after_a_transient_fault_reports_its_own_earlier_writes_as_copied(
    conditional, size, body
):
    """**THE TEST THE WHOLE 412 RESOLUTION EXISTS FOR, at both copy sizes.**

    ``copy_batch`` re-raises one item's transient fault once every copy in the batch has
    settled, and the Map's ``Retry`` then re-runs the WHOLE batch — so the items the first
    attempt already finished are copied again, and every one of them answers a conditional write
    with a refusal. Read as "occupied", each would be reported to the user as a file in the way,
    put there by the run reporting it. Resolved by comparing, each is what it is: this run's own
    output.

    The vault object above the threshold is seeded with a COMPOSITE ETag, because the archive's
    copy into the vault was made by this same engine at this same part size. That is the property
    decision 2 rests on, and it is why the two sides agree rather than being made to.
    """
    conditional.seed("archive-bkt", "vault/a", body, multipart=size > _TINY_THRESHOLD)
    conditional.seed("archive-bkt", "vault/b", body, multipart=size > _TINY_THRESHOLD)
    items = [
        _restore_line("vault/a", size, dest="alice/a.csv"),
        _restore_line("vault/b", size, dest="alice/b.csv"),
    ]
    conditional.transient_once.add("alice/b.csv")

    with pytest.raises(TransientError):
        copy_mod.copy_batch(items, _FAILED, echo_fields=(), occupied_reason=_OCCUPIED)
    out = copy_mod.copy_batch(items, _FAILED, echo_fields=(), occupied_reason=_OCCUPIED)

    assert conditional.writes.count("alice/a.csv") == 1, "the first attempt did not land"
    assert out == {"copied": 2, "failures": []}


def test_a_destination_holding_DIFFERENT_bytes_is_occupied_and_is_never_written_over(conditional):
    """FR-002 AC3, and the assertion that matters is the second one: reporting the item is
    worthless if the bytes went anyway."""
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"the user's newer file")

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 8, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out == {"copied": 0, "failures": [{"reason": _OCCUPIED}]}
    assert conditional.writes == []
    assert conditional.objects[("user-bkt", "alice/a.csv")]["body"] == b"the user's newer file"


def test_the_SAME_bytes_under_a_different_content_type_are_occupied(conditional):
    """FR-002 AC3's second half. A copy carries the content type, so a destination that does not
    match on it is not this copy's output — and keeping the archive costs the user nothing, where
    sweeping the vault over a file this run cannot account for costs them a copy."""
    conditional.seed("archive-bkt", "vault/a", b"identical", content_type="text/csv")
    conditional.seed("user-bkt", "alice/a.csv", b"identical", content_type="application/json")

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 9, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out["failures"] == [{"reason": _OCCUPIED}]
    assert conditional.writes == []


def test_the_same_bytes_under_different_user_metadata_are_occupied(conditional):
    conditional.seed("archive-bkt", "vault/a", b"identical", metadata={"origin": "archive"})
    conditional.seed("user-bkt", "alice/a.csv", b"identical", metadata={})

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 9, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out["failures"] == [{"reason": _OCCUPIED}]
    assert conditional.writes == []


@pytest.mark.parametrize(
    ("target", "code"),
    [(("user-bkt", "alice/a.csv"), "AccessDenied"), (("archive-bkt", "vault/a"), "NoSuchKey")],
    ids=["destination-403", "source-404"],
)
def test_a_head_that_answers_anything_but_transiently_resolves_to_occupied(
    conditional, target, code
):
    """FR-002 AC4. **A 403 and a 404 give the same answer here, and that is the safe direction**:
    the caller's move on either is to leave the destination alone and keep the archive, so an
    ambiguous read costs a file that is not restored and never an overwrite. Neither is counted
    as copied."""
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"something")
    conditional.head_errors[target] = _S3Error(code)

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 8, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out == {"copied": 0, "failures": [{"reason": _OCCUPIED}]}
    assert conditional.writes == []


@pytest.mark.parametrize(
    "target",
    [("user-bkt", "alice/a.csv"), ("archive-bkt", "vault/a")],
    ids=["destination-head", "source-head"],
)
def test_a_transient_fault_on_either_head_raises_out_of_the_batch(conditional, target):
    """A throttle is not evidence about the destination, so it must not become a collision the
    user is told about. The batch retries and the comparison is asked again."""
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"something")
    conditional.head_errors[target] = _S3Error("SlowDown")

    with pytest.raises(TransientError):
        copy_mod.copy_batch(
            [_restore_line("vault/a", 8, dest="alice/a.csv")],
            _FAILED,
            echo_fields=(),
            occupied_reason=_OCCUPIED,
        )


def test_a_destination_head_that_fails_means_the_SOURCE_is_never_headed(conditional):
    """Stated in the docstring, so it is pinned: there is nothing to compare against once the
    destination cannot be read, and a second call would be a request made to answer nothing."""
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"something")
    conditional.head_errors[("user-bkt", "alice/a.csv")] = _S3Error("AccessDenied")
    headed = []
    real_head = conditional.head_object
    conditional.head_object = lambda **kw: headed.append(kw["Key"]) or real_head(**kw)

    copy_mod.copy_batch(
        [_restore_line("vault/a", 8, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert headed == ["alice/a.csv"]


def test_a_multipart_completion_refused_by_the_condition_aborts_its_upload(conditional):
    """FR-001 AC5. An upload left open accrues storage until a lifecycle rule sweeps it, and the
    abort is what stops the refusal being expensive as well as unsuccessful."""
    conditional.seed("archive-bkt", "vault/a", b"abcdefghijkl")
    conditional.seed("user-bkt", "alice/a.csv", b"a different twelve!!")

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 12, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out["failures"] == [{"reason": _OCCUPIED}]
    assert conditional.aborted == ["alice/a.csv"]


def test_an_occupied_item_reports_the_CALLERS_reason_and_defaults_to_the_failure_one(conditional):
    """The keyword defaults to None so no existing caller changes: a plane that does not tell the
    two outcomes apart gets the reason it already had."""
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"different")
    line = _restore_line("vault/a", 8, dest="alice/a.csv")

    named = copy_mod.copy_batch([line], _FAILED, echo_fields=(), occupied_reason=_OCCUPIED)
    conditional.objects[("user-bkt", "alice/a.csv")] = {
        "body": b"different",
        "ContentType": "text/csv",
        "Metadata": {},
        "ETag": _single_etag(b"different"),
    }
    unnamed = copy_mod.copy_batch([line], _FAILED, echo_fields=())

    assert named["failures"] == [{"reason": _OCCUPIED}]
    assert unnamed["failures"] == [{"reason": _FAILED}]


def test_no_existing_caller_can_reach_the_comparison_because_none_writes_ifAbsent():
    """FR-002 AC6, asserted against the SOURCE of all four callers rather than a fixture — absent
    in the manifest is what makes absent in the request. The restore's own builder is the one
    that sets it, and it is excluded by name rather than by the grep missing it."""
    lambdas = pathlib.Path(__file__).resolve().parent.parent
    writers = [
        "table-share-build-transfer-manifest",
        "file-send-build-transfer-manifest",
        "file-ops-build-transfer-manifest",
        "archive-build-transfer-manifest",
    ]
    for verb in writers:
        sources = [p for p in (lambdas / verb).glob("*.py") if not p.name.startswith("test_")]
        assert sources, f"{verb} has no production module — this test is measuring nothing"
        body = "".join(p.read_text() for p in sources)
        assert "ifAbsent" not in body, f"{verb} now writes a conditional line"

    restore_builder = lambdas / "archive-build-restore-manifest"
    written = "".join(
        p.read_text() for p in restore_builder.glob("*.py") if not p.name.startswith("test_")
    )
    assert '"ifAbsent": True' in written, "the restore's own builder stopped conditioning its lines"


def test_two_heads_that_carry_NO_etag_or_length_are_occupied_rather_than_identical(conditional):
    """**The guard that stops two empty answers comparing equal**, and it is defence in depth in
    the one function where a silent regression costs the only copy.

    With it removed, two ``head_object`` responses that both omit ``ETag`` and ``ContentLength``
    compare ``None == None`` on every field and ``{} == {}`` on the metadata, so the item counts
    as copied, the verdict goes complete, and the vault is swept for an object that was never
    written. Real S3 always returns both fields — which is exactly why nothing else would catch
    the guard going away.
    """
    conditional.seed("archive-bkt", "vault/a", b"archived")
    conditional.seed("user-bkt", "alice/a.csv", b"something else")
    blank = dict.fromkeys(("ContentType", "Metadata"))
    conditional.head_object = lambda **kw: dict(blank)

    out = copy_mod.copy_batch(
        [_restore_line("vault/a", 8, dest="alice/a.csv")],
        _FAILED,
        echo_fields=(),
        occupied_reason=_OCCUPIED,
    )

    assert out == {"copied": 0, "failures": [{"reason": _OCCUPIED}]}
    assert conditional.writes == []
    assert conditional.objects[("user-bkt", "alice/a.csv")]["body"] == b"something else"
