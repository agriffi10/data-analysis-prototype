"""Unit tests for the table-share copy-objects Lambda as a BATCH verb (SPEC-160).

The copy mechanics themselves moved to ``cpcommon.transfer.copy`` and are tested there. What
this file holds is what is table-share's: the batch contract with the Distributed Map, and the
FR-003 property that the verb knows nothing about recipients, plans or requests.
"""

import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-share-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
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
