"""The copy plan travels by pointer, and its key is the request id (SPEC-165 FR-004).

Runnable under pytest or directly: python3 test_copy_plan_fscommon.py.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from cpcommon import clients
from cpcommon import config as cpconfig
from cpcommon.errors import TerminalError, TransientError
from fscommon import copy_plan

_SOURCE = {"bucket": "user-bkt", "root": "alice/"}

_OBJECTS = [
    {"item": "reports", "relKey": "2026/q1.csv", "srcKey": "alice/reports/2026/q1.csv", "size": 91234},
    {"item": "notes.txt", "relKey": "", "srcKey": "alice/notes.txt", "size": 512},
]


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, error_code=None):
        self._error_code = error_code
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._error_code:
            raise _S3Error(self._error_code)
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}


def _install(error_code=None):
    fake = _FakeS3(error_code)
    clients._s3 = fake
    return fake


def test_the_key_is_the_request_id_under_the_planes_prefix():
    assert copy_plan.plan_key({"requestId": "req-1"}) == "file-send/req-1/copy-plan.json"


def test_the_key_matches_the_lifecycle_rules_prefix():
    """The rule in modules/analytics/s3.tf filters on `file-send/`, and a plan written outside
    it would never expire — an accumulating class of objects nobody looks at."""
    assert copy_plan.plan_key({"requestId": "req-1"}).startswith(f"{copy_plan.PREFIX}/")


def test_the_same_request_derives_the_same_key():
    """Replay safety, which is what the request id buys over a random key: a Retry of
    inspect-source rewrites the same object rather than leaving a second plan behind."""
    assert copy_plan.plan_key({"requestId": "req-1"}) == copy_plan.plan_key({"requestId": "req-1"})


def test_two_requests_never_collide_however_similar_their_selections():
    """The difference from table-share, which hashes the fields identifying a share because it
    has no request id. Two identical selections from one user are two different sends here."""
    assert copy_plan.plan_key({"requestId": "req-1"}) != copy_plan.plan_key({"requestId": "req-2"})


@pytest.mark.parametrize("request_id", [None, "", "   ", 7])
def test_a_request_without_a_usable_id_refuses_rather_than_inventing_a_key(request_id):
    """A key built from `None` is a real object in a real bucket. Falling back to a shared or
    random key would give up the one property the id is here for."""
    with pytest.raises(TerminalError) as caught:
        copy_plan.plan_key({"requestId": request_id})

    assert caught.value.reason == "malformed_event"


def test_the_plan_records_everything_the_manifest_builder_needs():
    """FR-004 AC3: per object the source key, the size and the relative key WITH its owning item
    name — so SPEC-166 can compute a destination without listing anything a second time."""
    fake = _install()

    key = copy_plan.write({"requestId": "req-1"}, _SOURCE, "alice", _OBJECTS, 91746)

    written = json.loads(fake.puts[0]["Body"])
    assert key == "file-send/req-1/copy-plan.json"
    assert written == {
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "sender": "alice",
        "objects": _OBJECTS,
        "objectCount": 2,
        "totalBytes": 91746,
    }


def test_the_plan_goes_to_the_admin_bucket():
    """Not a user's space: the SPA never browses it, so it needs no hidden-folder convention,
    and a user cannot delete it out from under a running execution."""
    fake = _install()

    copy_plan.write({"requestId": "req-1"}, _SOURCE, "alice", _OBJECTS, 91746)

    assert fake.puts[0]["Bucket"] == cpconfig.ADMIN_BUCKET
    assert fake.puts[0]["ContentType"] == "application/json"


def test_a_throttled_write_is_transient_so_the_retry_reruns_the_verb():
    """Safe to retry precisely because the key is a pure function of the request id: the second
    attempt overwrites the first's object rather than adding one."""
    _install(error_code="SlowDown")

    with pytest.raises(TransientError):
        copy_plan.write({"requestId": "req-1"}, _SOURCE, "alice", _OBJECTS, 91746)


def test_a_deterministic_write_failure_propagates_rather_than_retrying():
    _install(error_code="AccessDenied")

    with pytest.raises(_S3Error):
        copy_plan.write({"requestId": "req-1"}, _SOURCE, "alice", _OBJECTS, 91746)


def test_importing_this_module_alone_can_still_raise_its_refusal():
    """The import-order trap that once shipped three unraisable reason codes: TerminalError
    validates its reason against the registered table at the RAISE site, so a process importing
    only this module would get a ValueError where it meant to write a refusal."""
    assert copy_plan.messages.resolver.template("nothing_to_send")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
