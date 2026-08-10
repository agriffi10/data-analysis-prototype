"""Unit tests for the shared transfer engine (SPEC-160).

The manifest writer's file format, the batch copier's failure isolation, and the result
reader's two attribution paths — including the one a FAILED-only collector silently passes.
AWS is stubbed with a recording fake. Runnable under pytest or directly:
python3 test_transfer_cpcommon.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

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
    def __init__(self, objects=None, copy_error=None, get_error=None):
        self.objects = objects or {}
        self.puts = []
        self.copies = []
        self.multipart = []
        self.aborted = []
        self.copy_error = copy_error
        self.get_error = get_error
        self._uploads = 0

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

    parts = [c for c in fake.multipart if "PartNumber" in c]
    complete = [c for c in fake.multipart if "complete" in c]
    assert fake.copies == []
    assert len(parts) == 6
    assert parts[0]["CopySourceRange"] == f"bytes=0-{GIB - 1}"
    assert parts[-1]["CopySourceRange"] == f"bytes={5 * GIB}-{size - 1}"
    assert [p["PartNumber"] for p in complete[0]["complete"]["MultipartUpload"]["Parts"]] == [1, 2, 3, 4, 5, 6]


def test_one_bad_item_never_costs_its_siblings_their_copy():
    """FR-003 AC3 — the batch SUCCEEDS and reports the failure per item."""
    fake = _setup(copy_error=lambda kwargs: _S3Error("AccessDenied") if "bad" in kwargs["Key"] else None)

    out = copy_mod.copy_batch(
        [_item("bob", "good-1.parquet"), _item("carol", "bad.parquet"), _item("bob", "good-2.parquet")],
        _FAILED,
    )

    assert out["copied"] == 2
    assert out["failures"] == [{"recipient": "carol", "reason": _FAILED}]
    assert len(fake.copies) == 2


def test_a_failure_names_the_recipient_and_never_the_key():
    _setup(copy_error=_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item("bob", "secret-name.parquet")], _FAILED)
    assert out["failures"] == [{"recipient": "bob", "reason": _FAILED}]


def test_a_throttled_item_raises_so_the_batch_retries():
    _setup(copy_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        copy_mod.copy_batch([_item()], _FAILED)


def test_a_malformed_line_fails_its_own_item_only():
    fake = _setup()
    out = copy_mod.copy_batch([{"recipient": "bob"}, _item("carol")], _FAILED)

    assert out["copied"] == 1
    assert out["failures"] == [{"recipient": "bob", "reason": _FAILED}]
    assert len(fake.copies) == 1


def test_a_failed_multipart_upload_is_aborted():
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert out["failures"] == [{"recipient": "bob", "reason": _FAILED}]
    assert len(fake.aborted) == 1


def test_a_failed_abort_never_hides_the_copy_failure():
    """The abort is best-effort — an expired upload lifecycles away — but the item still fails."""
    fake = _setup()
    fake.upload_part_copy = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))
    fake.abort_multipart_upload = lambda **kwargs: (_ for _ in ()).throw(_S3Error("AccessDenied"))

    out = copy_mod.copy_batch([_item(rel="big.parquet", size=6 * GIB)], _FAILED)

    assert out["failures"] == [{"recipient": "bob", "reason": _FAILED}]


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
    _setup(objects=objects)
    return results_mod.read_failed_items(
        "admin-bkt",
        "table-share/h/exec/results/manifest.json",
        batch_failure_reason=_FAILED,
        unreadable_reason=_UNREADABLE,
    )


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
                [_item("bob"), _item("carol")], [{"recipient": "carol", "reason": _FAILED}]
            )
        ],
    }) == [{"recipient": "carol", "reason": _FAILED}]


def test_a_whole_batch_failure_is_attributed_from_its_input():
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(FAILED=["r/FAILED_0.json"]),
        "r/FAILED_0.json": [_failed_record([_item("bob"), _item("carol")])],
    }) == [
        {"recipient": "bob", "reason": _FAILED},
        {"recipient": "carol", "reason": _FAILED},
    ]


def test_a_pending_batch_is_attributed_too():
    """A run stopped mid-flight leaves items that never ran; they did not copy either."""
    assert _read({
        "table-share/h/exec/results/manifest.json": _run_manifest(PENDING=["r/PENDING_0.json"]),
        "r/PENDING_0.json": [_failed_record([_item("bob")])],
    }) == [{"recipient": "bob", "reason": _FAILED}]


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


def test_a_result_file_entry_with_no_key_is_skipped():
    """The manifest's own shape, not a payload — an entry naming no object has nothing to read."""
    assert _read({
        "table-share/h/exec/results/manifest.json": {
            "ResultFiles": {"SUCCEEDED": [{"Size": 0}]},
        },
    }) == []


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
