"""The copy plan: what it records, and every shape a later verb must not be handed.

The plan is the only thing that knows what an operation will touch — the state carries counts and a
pointer. So the failures worth testing are the ones where a plausible plan is silently the wrong
one: another execution's, a truncated one, or one whose fields were quietly taken off the state
instead.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from focommon import config, plan

_EXECUTION = "arn:aws:states:us-east-1:1:execution:file-ops:run-1"


class _S3Error(Exception):
    def __init__(self, code, status=404):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, objects=None, deny_missing=False, deny_list=False):
        self.objects = objects or {}
        self.puts = []
        self.deny_missing = deny_missing
        self.deny_list = deny_list
        self.lists = []

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=None):
        self.lists.append(Prefix)
        if self.deny_list:
            raise _S3Error("AccessDenied", status=403)
        found = [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]
        if not found:
            return {}
        return {"Contents": found[: MaxKeys or len(found)]}

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise _S3Error("AccessDenied", status=403) if self.deny_missing else _S3Error(
                "NoSuchKey"
            )
        body = self.objects[Key]
        if isinstance(body, Exception):
            raise body

        class _Body:
            def read(self_inner):
                return body

        return {"Body": _Body()}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        self.objects[Key] = Body
        return {}


def _install(objects=None, deny_missing=False, deny_list=False):
    fake = _FakeS3(objects, deny_missing=deny_missing, deny_list=deny_list)
    clients._s3 = fake
    return fake


def _request(**over):
    request = {
        "requestId": "req-1",
        "operation": "move",
        "submittedAt": "2026-08-20T10:00:00+00:00",
        "onConflict": "refuse",
        "execution": {"arn": _EXECUTION},
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "objectCount": 1,
    }
    request.update(over)
    return request


def _items(count=1):
    return [
        {
            "itemKey": f"alice/item{n}/",
            "label": f"item{n}",
            "kind": "folder",
            "targetName": f"item{n}",
            "objects": [{"srcBucket": "user-bkt", "srcKey": f"alice/item{n}/a", "size": 1}],
            "objectCount": 1,
            "totalBytes": 1,
        }
        for n in range(count)
    ]


def _write(fake, **over):
    request = _request(**over)
    return plan.write(
        request,
        {"bucket": "user-bkt", "root": "alice/"},
        {"bucket": "user-bkt", "prefix": "alice/out/"},
        "alice",
        _EXECUTION,
        _items(),
    )


# ── The key and the body ─────────────────────────────────────────────────────


def test_the_key_is_a_pure_function_of_the_request_id():
    """Which is what makes a Retry rewrite the same object rather than leave a second one behind."""
    assert plan.plan_key(_request()) == f"{config.PLAN_PREFIX}/req-1/{plan.BASENAME}"


def test_a_plan_key_without_a_request_id_is_refused_rather_than_invented():
    """A key built from ``None`` is a real object in a real bucket, and a random one gives up the
    property the id buys."""
    with pytest.raises(TerminalError):
        plan.plan_key({"requestId": "  "})


def test_the_body_carries_what_a_later_verb_would_otherwise_take_off_the_state():
    """Without the request id the supersession check has nothing to compare, and reading the
    submission time or the conflict answer off the state is the substitution it exists to catch."""
    fake = _install()

    _write(fake)

    body = json.loads(fake.puts[0]["Body"])
    assert body["requestId"] == "req-1"
    assert body["submittedAt"] == "2026-08-20T10:00:00+00:00"
    assert body["onConflict"] == "refuse"
    assert body["executionArn"] == _EXECUTION
    assert body["actor"] == "alice"
    assert body["source"] == {"bucket": "user-bkt", "root": "alice/"}


def test_the_body_records_the_counts_it_will_later_be_checked_against():
    fake = _install()
    plan.write(
        _request(),
        {"bucket": "user-bkt", "root": "alice/"},
        None,
        "alice",
        _EXECUTION,
        _items(3),
    )

    body = json.loads(fake.puts[0]["Body"])
    assert (body["itemCount"], body["objectCount"], body["totalBytes"]) == (3, 3, 3)


def test_the_plan_goes_to_the_admin_bucket():
    """The SPA never browses it, so it needs no hidden-folder convention — and a user cannot delete
    it out from under a running execution, which they could in their own space."""
    fake = _install()

    _write(fake)

    assert fake.puts[0]["Bucket"] == "admin-bkt"


# ── The reuse guard ──────────────────────────────────────────────────────────


def test_an_unused_request_id_passes():
    _install()

    assert plan.assert_request_id_unused(_request(), _EXECUTION) is None


def test_a_plan_from_ANOTHER_execution_refuses_the_request():
    """Without it a run could plan over another execution's object list while that run was still
    copying from it."""
    fake = _install()
    _write(fake)

    with pytest.raises(TerminalError) as err:
        plan.assert_request_id_unused(_request(), "arn:aws:states:us-east-1:1:execution:file-ops:2")

    assert err.value.reason == "request_id_reused"


def test_THIS_executions_own_plan_is_not_a_reuse():
    """Every task on this machine retries three times, so a transient fault after the write is an
    ordinary event — and a guard refusing any occupied prefix would refuse the request it had just
    planned itself, telling the user their id had been used before."""
    fake = _install()
    _write(fake)

    assert plan.assert_request_id_unused(_request(), _EXECUTION) is None


# ── Reading it back ──────────────────────────────────────────────────────────


def test_a_plan_round_trips():
    fake = _install()
    key = _write(fake)

    loaded = plan.load(key, _request())

    assert loaded["items"][0]["itemKey"] == "alice/item0/"


def test_an_absent_plan_is_a_terminal_rather_than_an_empty_one():
    _install()

    with pytest.raises(TerminalError) as err:
        plan.load("file-ops/req-1/plan.json", _request())

    assert err.value.reason == "plan_unreadable"


def test_a_plan_that_is_not_json_is_refused():
    _install({"file-ops/req-1/plan.json": b"{not json"})

    with pytest.raises(TerminalError) as err:
        plan.load("file-ops/req-1/plan.json", _request())

    assert err.value.reason == "plan_unreadable"


def test_a_plan_that_is_not_an_OBJECT_is_refused():
    """A JSON array parses, and every ``.get`` on it would raise inside the verb rather than here."""
    _install({"file-ops/req-1/plan.json": b"[1, 2]"})

    with pytest.raises(TerminalError) as err:
        plan.load("file-ops/req-1/plan.json", _request())

    assert err.value.reason == "plan_unreadable"


def test_a_deterministic_read_fault_is_a_terminal_rather_than_an_absent_plan():
    """A 403 on the plan key is not "there is no plan" — reading it as one would have the verb behave
    as though the expansion had never run."""
    _install({"file-ops/req-1/plan.json": _S3Error("AccessDenied", 403)})

    with pytest.raises(TerminalError) as err:
        plan.load("file-ops/req-1/plan.json", _request())

    assert err.value.reason == "plan_unreadable"


@pytest.mark.parametrize(
    "damage",
    [
        {"items": "not a list"},
        {"items": [{"itemKey": "alice/a/"}]},
        {"items": [{"objects": []}]},
    ],
)
def test_a_plan_whose_ITEMS_lost_their_shape_is_refused(damage):
    """Each of these is a shape a later verb would read straight past: an item with no object list
    plans nothing, and one with no key attributes its outcome to nobody."""
    fake = _install()
    key = _write(fake)
    body = json.loads(fake.objects[key])
    body.update(damage)
    fake.objects[key] = json.dumps(body).encode()

    with pytest.raises(TerminalError) as err:
        plan.load(key, _request())

    assert err.value.reason == "plan_unreadable"


def test_a_write_fault_that_is_retryable_stays_retryable():
    """The key is a pure function of the request id and the verb is read-only besides this write, so
    a retry is safe — but only if the fault is one the machine's Retry recognises."""

    class _Failing(_FakeS3):
        def put_object(self, Bucket, Key, Body, ContentType):
            raise _S3Error("SlowDown", 503)

    clients._s3 = _Failing()

    with pytest.raises(TransientError):
        _write(clients._s3)


@pytest.mark.parametrize(
    "field,value",
    [
        ("requestId", "req-2"),
        ("executionArn", "arn:aws:states:us-east-1:1:execution:file-ops:2"),
        ("objectCount", 99),
    ],
)
def test_a_plan_describing_a_different_run_is_refused(field, value):
    """Every later verb takes its destination keys, its conflict answer and eventually its DELETION
    list from whatever it reads back, so a plan that is not this run's is not a plan."""
    fake = _install()
    key = _write(fake)
    body = json.loads(fake.objects[key])
    body[field] = value
    if field == "objectCount":
        body["items"][0]["objects"].extend([{"srcKey": "x"}] * 98)
    fake.objects[key] = json.dumps(body).encode()

    with pytest.raises(TerminalError) as err:
        plan.load(key, _request())

    assert err.value.reason == "plan_superseded"


@pytest.mark.parametrize(
    "field,value",
    [("bucket", "shared-bkt"), ("root", "bob/")],
)
def test_a_plan_naming_a_different_SOURCE_is_refused(field, value):
    """The deletion this plane will eventually do is scoped to the plan's own root, in whichever
    space bucket — so a plan describing another one is the shape that deletes the wrong thing."""
    fake = _install()
    key = _write(fake)
    body = json.loads(fake.objects[key])
    body["source"][field] = value
    fake.objects[key] = json.dumps(body).encode()

    with pytest.raises(TerminalError) as err:
        plan.load(key, _request())

    assert err.value.reason == "plan_superseded"


def test_a_plan_SHORT_OF_THE_COUNT_IT_RECORDS_is_refused():
    """A non-empty list is not a complete one. A truncated plan is precisely the shape that produces
    a copy which succeeds over a user told everything went well."""
    fake = _install()
    key = _write(fake)
    body = json.loads(fake.objects[key])
    body["items"][0]["objects"] = []
    fake.objects[key] = json.dumps(body).encode()

    with pytest.raises(TerminalError) as err:
        plan.load(key, _request())

    assert err.value.reason == "plan_unreadable"


def test_a_plan_that_records_no_objects_AT_ALL_is_legitimate():
    """Every selected item resolving to nothing is a per-item outcome on this plane rather than a
    whole-request refusal, so "carries something" cannot be the check — which is exactly why the
    check is that the plan holds what it RECORDS holding."""
    _install()
    plan.write(
        _request(objectCount=0),
        {"bucket": "user-bkt", "root": "alice/"},
        None,
        "alice",
        _EXECUTION,
        [],
    )

    loaded = plan.load(plan.plan_key(_request()), _request(objectCount=0))

    assert loaded["items"] == []


def test_a_read_fault_that_is_retryable_stays_retryable():
    """A verb that turned a throttle into a terminal would fail a request the machine's own Retry
    would have completed."""
    _install({"file-ops/req-1/plan.json": _S3Error("SlowDown", 503)})

    with pytest.raises(TransientError):
        plan.load("file-ops/req-1/plan.json", _request())


def test_a_denied_read_of_an_ABSENT_plan_is_an_absence_and_not_a_fault():
    """Production's shape, which no fake here reproduced until now.

    A caller whose list grant is conditioned on a prefix cannot satisfy that condition on a
    ``GetObject``, so S3 refuses the read of a MISSING object rather than reporting it missing.
    Every first submission arrives that way, and before the probe it failed the whole operation
    with "the working list for that could not be read back".
    """
    fake = _install(deny_missing=True)

    assert plan.assert_request_id_unused(_request(), _EXECUTION) is None
    assert fake.lists == [plan.plan_key(_request())], (
        "the absence was concluded without asking S3 whether the key is there"
    )


def test_a_denied_read_of_a_PRESENT_plan_still_refuses():
    """The half that stops the fix failing open.

    Were a denial alone read as absence, a request whose plan exists but cannot be read would be
    planned a second time — over a run still copying from the first plan's object list.
    """
    key = plan.plan_key(_request())
    fake = _install({key: _S3Error("AccessDenied", 403)}, deny_missing=True)

    with pytest.raises(TerminalError) as err:
        plan.assert_request_id_unused(_request(), _EXECUTION)

    assert err.value.reason == "plan_unreadable"
    assert fake.lists, "the read was refused without the list that separates denial from absence"


def test_a_denied_LIST_is_a_fault_rather_than_an_absence():
    """The probe cannot answer, so nothing may be concluded from it.

    This is the grant being wrong rather than the object being missing, and guessing absence here
    would restore the fail-open the probe exists to remove.
    """
    fake = _install(deny_missing=True, deny_list=True)

    with pytest.raises(TerminalError) as err:
        plan.assert_request_id_unused(_request(), _EXECUTION)

    assert err.value.reason == "plan_unreadable"
    assert fake.lists == [plan.plan_key(_request())], (
        "the refusal came from the read alone — this test passes against code with no probe at "
        "all unless it asserts the probe was attempted"
    )


def test_a_SIBLING_key_under_the_plan_key_is_not_mistaken_for_the_plan():
    """The exact-match filter, which nothing else in the suite exercises.

    ``_absent`` lists by prefix, and a prefix matches anything that extends it. Were the answer
    taken from "the listing is non-empty", an artifact written beside a plan would make a genuinely
    absent plan read as present and refuse a legitimate request.
    """
    key = plan.plan_key(_request())
    fake = _install({f"{key}.bak": "{}"}, deny_missing=True)

    assert plan.assert_request_id_unused(_request(), _EXECUTION) is None
    assert fake.lists == [key]
