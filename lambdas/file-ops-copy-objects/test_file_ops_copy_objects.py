"""Unit tests for the file-ops copy-objects Lambda.

Thin by design — it is ``cpcommon.transfer.copy`` with this plane's reason code and its attribution
field. What is worth pinning is exactly that: the field it echoes, and the fact that a deterministic
failure does not take its siblings down with it.

Runnable under pytest or directly: python3 test_file_ops_copy_objects.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_ops_copy_objects as m
import pytest
from cpcommon import clients
from cpcommon.errors import TransientError


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, fail=None):
        self._fail = fail or {}
        self.copies = []

    def copy_object(self, **kwargs):
        key = kwargs["CopySource"]["Key"]
        if key in self._fail:
            raise self._fail[key]
        self.copies.append(kwargs)


def _line(item_key, src, dest, size=10):
    return {
        "itemKey": item_key,
        "srcBucket": "user-bkt",
        "srcKey": src,
        "destBucket": "user-bkt",
        "destKey": dest,
        "size": size,
    }


def _install(fail=None):
    fake = _FakeS3(fail)
    clients._s3 = fake
    return fake


def test_a_failure_is_attributed_to_the_ITEM_rather_than_a_recipient():
    """This plane's whole reason for generalising the engine: the other three attribute to a
    recipient, and an ``itemKey`` used to be dropped on the way out of the child execution."""
    _install(fail={"alice/a/1": _S3Error("NoSuchKey")})

    outcome = m.handler({"Items": [_line("alice/a/", "alice/a/1", "alice/out/a/1")]}, None)

    assert outcome["failures"] == [{"itemKey": "alice/a/", "reason": "copy_failed"}]


def test_one_failing_object_does_not_cost_its_SIBLINGS_their_copy():
    """The batch returns its per-item outcomes and SUCCEEDS; the collector attributes the failures
    back from the Map Run's export."""
    fake = _install(fail={"alice/a/1": _S3Error("AccessDenied")})
    items = [
        _line("alice/a/", "alice/a/1", "alice/out/a/1"),
        _line("alice/b/", "alice/b/1", "alice/out/b/1"),
    ]

    outcome = m.handler({"Items": items}, None)

    assert outcome["copied"] == 1
    assert len(fake.copies) == 1
    assert outcome["failures"][0]["itemKey"] == "alice/a/"


def test_a_TRANSIENT_failure_raises_so_the_Map_retries_the_whole_batch():
    """The opposite of a deterministic one, and correct because a copy is idempotent and the
    destination guard has already run — twice."""
    _install(fail={"alice/a/1": _S3Error("SlowDown")})

    with pytest.raises(TransientError):
        m.handler({"Items": [_line("alice/a/", "alice/a/1", "alice/out/a/1")]}, None)


def test_an_empty_batch_is_an_ordinary_zero():
    assert m.handler({"Items": []}, None) == {"copied": 0, "failures": []}


def test_the_echoed_field_is_BOUNDED_and_is_a_key_ONCE_per_line():
    """The failure list rides the exported result and then the state, where a key list is the
    unbounded term that breaches the 256 KB limit ON the Map — destroying every per-item outcome the
    export exists to preserve."""
    assert m.ITEM_KEY == ("itemKey",)


def test_the_reason_code_is_declared_LOCALLY_because_this_verb_carries_no_domain_layer():
    """The deliberate twin every plane's batch verb has: attaching a whole domain layer to a
    function that needs one string from it is the alternative."""
    import pathlib

    source = pathlib.Path(m.__file__).read_text()

    assert 'COPY_FAILED = "copy_failed"' in source
    assert "from focommon" not in source
