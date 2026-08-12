"""Unit tests for the table-share copy-objects Lambda as a BATCH verb (SPEC-160).

The copy mechanics themselves moved to ``cpcommon.transfer.copy`` and are tested there. What
this file holds is what is table-share's: the batch contract with the Distributed Map, and the
FR-003 property that the verb knows nothing about recipients, plans or requests. Runnable under
pytest or directly: python3 test_table_share_copy_objects.py.
"""

import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
import table_share_copy_objects as m
from cpcommon import clients
from cpcommon.errors import TransientError

GIB = 1024**3
_SOURCE = pathlib.Path(__file__).resolve().parent / "table_share_copy_objects.py"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, copy_error=None):
        self.copies = []
        self.multipart = []
        self.copy_error = copy_error
        self._uploads = 0

    def copy_object(self, **kwargs):
        error = self.copy_error(kwargs) if callable(self.copy_error) else self.copy_error
        if error:
            raise error
        self.copies.append(kwargs)

    def head_object(self, **kwargs):
        """The source read the MULTIPART path takes since SPEC-171.

        `CreateMultipartUpload` has no `MetadataDirective`, so the copier re-states the source's
        own content type and metadata onto it — without which every object over 5 GiB lost both.
        A share carries no custom headers today, so this reports none and the create call is the
        one that shipped before.
        """
        del kwargs
        return {"ContentLength": 0}

    def create_multipart_upload(self, **kwargs):
        self._uploads += 1
        return {"UploadId": f"u{self._uploads}"}

    def upload_part_copy(self, **kwargs):
        self.multipart.append(kwargs)
        return {"CopyPartResult": {"ETag": f"etag-{kwargs['PartNumber']}"}}

    def complete_multipart_upload(self, **kwargs):
        self.multipart.append({"complete": kwargs})

    def abort_multipart_upload(self, **kwargs):
        pass


def _setup(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _batch(*items):
    return {"Items": list(items)}


def _item(recipient="bob", rel="part-0.parquet", size=10):
    return {
        "recipient": recipient,
        "kind": "user",
        "srcBucket": "user-bkt",
        "srcKey": f"alice/sales/{rel}",
        "destBucket": "user-bkt",
        "destKey": f"{recipient}/shared_tables/orders_copy/{rel}",
        "size": size,
    }


def test_a_batch_copies_every_item_layout_preserved():
    fake = _setup()

    out = m.handler(_batch(_item(rel="part-0.parquet"), _item(rel="year=2025/part-1.parquet")), None)

    assert out == {"copied": 2, "failures": []}
    assert sorted((c["CopySource"]["Key"], c["Key"]) for c in fake.copies) == [
        ("alice/sales/part-0.parquet", "bob/shared_tables/orders_copy/part-0.parquet"),
        ("alice/sales/year=2025/part-1.parquet", "bob/shared_tables/orders_copy/year=2025/part-1.parquet"),
    ]


def test_one_batch_spans_recipients():
    """The fan-out is over (recipient x object) pairs, so a batch is NOT one recipient's work."""
    fake = _setup()

    out = m.handler(_batch(_item("bob"), _item("carol"), _item("dave")), None)

    assert out["copied"] == 3
    assert {c["Key"].split("/")[0] for c in fake.copies} == {"bob", "carol", "dave"}


def test_a_deterministic_failure_does_not_fail_the_batch():
    """FR-003 AC3 — the batch SUCCEEDS so its siblings' copies stand and attribution happens
    downstream. Raising here would abort 49 good copies for one bad key."""
    _setup(copy_error=lambda kwargs: _S3Error("AccessDenied") if "bad" in kwargs["Key"] else None)

    out = m.handler(_batch(_item("bob", "good.parquet"), _item("carol", "bad.parquet")), None)

    assert out == {"copied": 1, "failures": [{"recipient": "carol", "kind": "user", "reason": "copy_failed"}]}


def test_a_throttle_still_raises_so_the_map_retries_the_batch():
    _setup(copy_error=_S3Error("SlowDown"))
    with pytest.raises(TransientError):
        m.handler(_batch(_item()), None)


def test_a_large_object_still_multipart_copies():
    fake = _setup()
    m.handler(_batch(_item(rel="big.parquet", size=6 * GIB)), None)
    assert fake.copies == []
    assert [c for c in fake.multipart if "PartNumber" in c]


def test_an_empty_batch_is_a_no_op():
    fake = _setup()
    assert m.handler({"Items": []}, None) == {"copied": 0, "failures": []}
    assert fake.copies == []


def test_re_running_an_identical_batch_is_harmless():
    """FR-003 AC5 — copy is idempotent and the conflict guard has already run, which is what
    makes the Map's whole-batch retry safe."""
    fake = _setup()
    batch = _batch(_item(rel="a.parquet"))

    first = m.handler(batch, None)
    second = m.handler(batch, None)

    assert first == second == {"copied": 1, "failures": []}
    assert len(fake.copies) == 2
    assert fake.copies[0]["Key"] == fake.copies[1]["Key"]


def test_the_verb_imports_nothing_recipient_shaped():
    """FR-003 AC4 — the property, asserted rather than described.

    Destination resolution, the copy plan and every per-recipient concept moved upstream. A
    reintroduced ``copy_plan`` or ``glue`` import here means this verb has started deciding
    something the manifest already decided, and the two would drift.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    forbidden = {name for name in imported if any(
        part in name for part in ("copy_plan", "cognito", "glue", "registry", "ddl", "athena")
    )}
    assert not forbidden, f"copy-objects must stay recipient-agnostic; it imports {forbidden}"
    assert not [name for name in imported if name.startswith("tscommon")], (
        "copy-objects imports the table-share domain layer, so it is no longer the shared "
        "batch copier the send-files and archive planes are meant to reuse"
    )


def test_the_verb_never_names_the_copy_plan():
    """The other half of AC4: an import scan cannot see a key read off the event.

    ``copyPlanKey`` is the one field that would let this verb resolve work for itself, and
    resolving it in two places is how the manifest and the copy drift apart.
    """
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    read_keys = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert read_keys == {"Items"}, (
        f"copy-objects reads {read_keys} off its event; a batch verb reads its batch and "
        "nothing else"
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
