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


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class _FakeS3:
    def __init__(self, error_code=None, body=None):
        self._error_code = error_code
        self._body = body
        self.puts = []

    def put_object(self, Bucket, Key, Body, ContentType):
        if self._error_code:
            raise _S3Error(self._error_code)
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}

    def get_object(self, Bucket, Key):
        if self._error_code:
            raise _S3Error(self._error_code)
        return {"Body": _Body(self._body)}


def _install(error_code=None, body=None):
    fake = _FakeS3(error_code, body)
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


def test_every_artifact_of_one_request_shares_one_folder():
    """SPEC-166 FR-002/FR-005. The plan, the manifest and the Map Run's export sit under one
    ``file-send/{requestId}/`` folder, which is what makes ONE lifecycle rule expire all three —
    a manifest written a prefix over would outlive every rule this plane has."""
    request = {"requestId": "req-1"}
    folder = f"{copy_plan.PREFIX}/req-1/"

    assert copy_plan.plan_key(request).startswith(folder)
    assert copy_plan.transfer_manifest_key(request).startswith(folder)
    assert copy_plan.transfer_results_prefix(request).startswith(folder)


def test_the_three_artifacts_never_collide_with_each_other():
    """One folder, three distinct objects. The results PREFIX carries no trailing slash — Step
    Functions appends its own Map Run component and manifest basename below it."""
    request = {"requestId": "req-1"}
    keys = {
        copy_plan.plan_key(request),
        copy_plan.transfer_manifest_key(request),
        copy_plan.transfer_results_prefix(request),
    }

    assert len(keys) == 3
    assert not copy_plan.transfer_results_prefix(request).endswith("/")


def test_the_manifest_key_is_execution_stable_rather_than_execution_unique():
    """The deliberate difference from table-share, whose manifest key carries the execution
    name because it has NO request id — its keys are a digest, two overlapping executions of one
    share collide on it, and a manifest's lines depend on which recipients the guard accepted.

    Here the id is the browser's per-submit ``MessageDeduplicationId``: a second execution
    carrying it could only come from a redelivery of the same SQS message, which the Pipe's
    deterministic execution name refuses with ``ExecutionAlreadyExists``. What the key must buy
    is that a RETRY of the manifest verb rewrites one object rather than leaving two, and that
    is what this asserts."""
    request = {"requestId": "req-1"}

    assert copy_plan.transfer_manifest_key(request) == copy_plan.transfer_manifest_key(request)
    assert copy_plan.transfer_manifest_key(request) != copy_plan.transfer_manifest_key(
        {"requestId": "req-2"}
    )


@pytest.mark.parametrize(
    "derive", [copy_plan.transfer_manifest_key, copy_plan.transfer_results_prefix]
)
@pytest.mark.parametrize("request_id", [None, "", "   ", 7])
def test_no_transfer_artifact_invents_a_key_either(derive, request_id):
    """The same refusal as the plan's, on both new keys: a key built from ``None`` is a real
    object in a real bucket, and a shared fallback key would let two requests overwrite each
    other's manifest."""
    with pytest.raises(TerminalError):
        derive({"requestId": request_id})


def _plan_body(**overrides):
    """A well-formed plan document, as ``write`` produces it, with fields overridden per test."""
    return json.dumps(
        {
            "source": _SOURCE,
            "sender": "alice",
            "objects": _OBJECTS,
            "objectCount": len(_OBJECTS),
            "totalBytes": 91746,
            **overrides,
        }
    ).encode()


def test_the_plan_reads_back_whole():
    """The manifest builder needs the sender and the source bucket as well as the objects — the
    plan is the object that knows which sender its keys were expanded for."""
    _install(body=_plan_body())

    plan = copy_plan.load("file-send/req-1/copy-plan.json")

    assert plan["sender"] == "alice"
    assert plan["source"]["bucket"] == "user-bkt"
    assert plan["objects"] == _OBJECTS


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"not json", "not json at all"),
        (b'["objects"]', "not an object"),
        (_plan_body(objects=[], objectCount=0), "no objects"),
        (_plan_body(sender=""), "no sender"),
        (_plan_body(source={"root": "alice/"}), "no source bucket"),
        (_plan_body(objects=_OBJECTS[:1]), "SHORT of the count it records"),
        (_plan_body(objectCount="2"), "a count that is not a number"),
        (_plan_body(objects=[{"relKey": "", "size": 1}], objectCount=1), "an entry with no item name"),
        (_plan_body(objects=[{"item": "notes.txt", "size": 1}], objectCount=1), "an entry with no source key"),
    ],
)
def test_an_unreadable_plan_is_terminal_rather_than_partially_used(body, why):
    """Fail-closed, and the direction is the whole point: a plan short of its objects would
    produce a manifest short of its lines, the copy would succeed over it, and every recipient
    would be told the send went well while holding only some of what was sent."""
    _install(body=body)

    with pytest.raises(TerminalError):
        copy_plan.load("file-send/req-1/copy-plan.json")


def test_a_truncated_plan_is_caught_by_the_count_it_records_itself():
    """The case a non-empty check cannot see, and the one that matters most: a plan short of its
    objects produces a manifest short of its LINES, the copy succeeds over it, and every
    recipient is told the send went well while holding some of what was sent. The plan records
    its own objectCount at write time, so the check is one comparison."""
    _install(body=_plan_body(objects=_OBJECTS[:1]))

    with pytest.raises(TerminalError) as caught:
        copy_plan.load("file-send/req-1/copy-plan.json")

    assert caught.value.reason == "copy_failed"


def test_what_write_produces_is_what_load_accepts():
    """The two halves are held together rather than each asserted against a fixture: a field
    added to the writer and not to the reader's checks (or the reverse) is how a document
    validates against a shape nothing writes."""
    fake = _install()
    copy_plan.write({"requestId": "req-1"}, _SOURCE, "alice", _OBJECTS, 91746)
    written = fake.puts[0]["Body"]
    _install(body=written)

    assert copy_plan.load("file-send/req-1/copy-plan.json")["objects"] == _OBJECTS


def test_a_throttled_plan_read_is_transient_so_the_retry_reruns_the_verb():
    _install(error_code="SlowDown")

    with pytest.raises(TransientError):
        copy_plan.load("file-send/req-1/copy-plan.json")


def test_a_missing_plan_is_terminal_because_no_retry_writes_it():
    """inspect-source wrote it earlier in this same execution, so absence means the object is
    gone or was never written — which retrying the reader cannot fix."""
    _install(error_code="NoSuchKey")

    with pytest.raises(TerminalError):
        copy_plan.load("file-send/req-1/copy-plan.json")


def test_importing_this_module_alone_can_still_raise_its_refusal():
    """The import-order trap that once shipped three unraisable reason codes: TerminalError
    validates its reason against the registered table at the RAISE site, so a process importing
    only this module would get a ValueError where it meant to write a refusal."""
    assert copy_plan.messages.resolver.template("nothing_to_send")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
