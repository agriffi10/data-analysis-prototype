"""Unit tests for the archive inspect-source Lambda (SPEC-169 FR-001).

The expansion rules and the caps have their own suite in ``archive-common``; this file exercises
them THROUGH the real handler and covers what only the verb can carry: the plan pointer coming
back on the state, the object list NOT coming back with it, and the actor being notified before
the Catch records a refusal.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_inspect_source as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
#: The execution name the machine stamps onto the state before this verb runs. It is here
#: because the stamp precedes inspect-source on the archive arm, so a fixture without it is a
#: shape the machine cannot produce.
_EXECUTION = "e4a1c0d2-5b6f-4e37-9a80-1c2d3e4f5a6b"


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


class _FakeS3:
    """A fake that honours ``IfNoneMatch`` on put, because the claim's whole behaviour is there.

    ``claims`` is the stored object rather than a flag: the refused run reads the claim back to
    find out whose it is, so a fake that only reported "taken" could not tell a retry of the
    holder from a second execution — which is the one distinction the claim exists to make.
    """

    def __init__(self, objects, archived=(), stored=None):
        self._objects = objects
        self._archived = list(archived)
        self.stored = dict(stored or {})
        self.puts = []
        self.listed = []
        self.get_error = None

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=None):
        self.listed.append({"Bucket": Bucket, "Prefix": Prefix})
        found = [{"Key": key} for key in self._archived if key.startswith(Prefix)]
        return {"KeyCount": len(found), "Contents": found}

    def get_paginator(self, name):
        objects = self._objects

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": k, "Size": s}
                        for k, s in sorted(objects.items())
                        if k.startswith(Prefix)
                    ]
                }

        return _P()

    def head_object(self, Bucket, Key):
        if Key not in self._objects:
            raise _S3Error("NoSuchKey")
        return {"ContentLength": self._objects[Key]}

    def put_object(self, Bucket, Key, Body, ContentType, **kwargs):
        if kwargs.get("IfNoneMatch") == "*" and Key in self.stored:
            raise _S3Error("PreconditionFailed")
        self.stored[Key] = Body
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, **kwargs})
        return {}

    def get_object(self, Bucket, Key):
        if self.get_error:
            raise self.get_error
        try:
            return {"Body": _Body(self.stored[Key])}
        except KeyError as err:
            raise _S3Error("NoSuchKey") from err


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


def _install(objects, archived=(), stored=None):
    fake = _FakeS3(objects, archived, stored)
    clients._s3 = fake
    return fake


def _claim_key(request_id=_REQUEST_ID):
    return f"archive/{request_id}/claim.json"


def _claim_body(execution=None):
    return json.dumps(
        {
            "execution": execution or _EXECUTION,
            "requestId": _REQUEST_ID,
            "claimedAt": "2026-09-17T09:30:00.000Z",
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _event(items=None):
    return {
        "requestId": _REQUEST_ID,
        "mode": "archive",
        "actor": {"username": "alice"},
        "execution": {"name": _EXECUTION, "startedAt": "2026-09-17T09:30:00.000Z"},
        "source": {
            "bucket": "user-bkt",
            "root": "alice/",
            "kind": "personal",
            "name": "alice",
            "items": items or [{"kind": "folder", "key": "alice/reports/"}],
        },
        "archive": {
            "bucket": "archive-bkt",
            "root": f"personal/alice/archive/{_REQUEST_ID}/",
            "receiptBucket": "user-bkt",
            "receiptKey": f"alice/archive/{_REQUEST_ID}/receipt.txt",
        },
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)), raising=False)
    return sent


def test_the_plan_key_comes_back_and_the_object_list_does_not():
    """At ARCHIVE_MAX_OBJECTS the plan is tens of megabytes against a 256 KB payload limit, and
    States.DataLimitExceeded escapes every Catch here (States.ALL does not match it and none
    names it) — which on this plane is a run that deleted nothing and told nobody. What rides is
    the pointer, the count and the byte total."""
    fake = _install({"alice/reports/a.csv": 5, "alice/reports/b.csv": 7})

    result = m.handler(_event(), None)

    assert result["copyPlanKey"] == f"archive/{_REQUEST_ID}/copy-plan.json"
    assert result["objectCount"] == 2
    assert result["totalBytes"] == 12
    assert "objects" not in result
    assert len(json.dumps(result).encode()) < 4096
    assert fake.puts[0]["Bucket"] == "admin-bkt"
    # The stamp runs ABOVE this verb, and this state is threaded Payload.$=$ with
    # OutputPath=$.Payload — so the verb's return REPLACES the state, and $.execution survives
    # only because the verb echoes its input. That is a behavioural property where it used to be
    # a structural one, and nothing downstream would fail loudly if it stopped holding: the
    # manifest key would simply refuse as malformed on every archive.
    assert result["execution"] == {"name": _EXECUTION, "startedAt": "2026-09-17T09:30:00.000Z"}


def test_a_refusal_notifies_the_actor_before_the_catch_records_it(_no_real_notifications):
    """The decorator is what makes a refusal a message rather than a silent failed execution;
    the machine's own NotifyFailure then suppresses the duplicate on the TerminalError name."""
    _install({})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "nothing_to_archive"
    assert [user for user, _ in _no_real_notifications] == ["alice"]


def test_a_request_id_that_has_been_used_before_is_refused_before_anything_is_read(
    _no_real_notifications,
):
    """**Found in review.** The request id is browser-supplied and is the WHOLE identity of an
    archive: the plan, the archive prefix, the record and the receipt are keyed on it alone. The
    queue's FIFO dedup window is five minutes against a three-hour ceiling, and this arc's live
    checks submit hand-crafted messages, so a reused id is reachable.

    What it costs is not a duplicate. Two archives mix under one prefix that SPEC-170 will list
    and restore wholesale, the first run's record and receipt are overwritten, and — if the second
    run fails its commit gate — its ROLLBACK deletes the FIRST archive's objects out of a bucket
    with versioning off. That last one is unrecoverable, which is why this refuses rather than
    being left to the producer's conventions.

    **And it tells nobody.** The objects under the prefix are the first run's, and that run
    reports under this id; a second message saying nothing was archived would sit beside its
    "Archived". The run after it is the positive control: the same actor, through the same
    decorator, IS told a refusal that is not silent.
    """
    fake = _install(
        {"alice/reports/a.csv": 5},
        archived=[f"personal/alice/archive/{_REQUEST_ID}/reports/old.csv"],
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)
    silent = list(_no_real_notifications)
    _install({})
    with pytest.raises(TerminalError) as told:
        m.handler(_event(), None)

    assert err.value.reason == "request_id_reused"
    assert fake.puts == []
    assert silent == []
    assert told.value.reason == "nothing_to_archive"
    assert [user for user, _ in _no_real_notifications] == ["alice"]


# ── the claim: one archive id is one run ────────────────────────────────────


def test_two_runs_of_one_id_racing_past_the_listing_end_with_exactly_one_proceeding(
    _no_real_notifications,
):
    """**The case the listing cannot decide, and the reason the claim exists.**

    ``assert_archive_unused`` refuses an id reused minutes or days later. It cannot refuse two
    runs that reach it together: both list the same empty prefix and both pass. Until the claim,
    both then wrote the copy plan at a key that is a pure function of the request id, so the
    loser overwrote the winner's plan — and delete-source takes its bucket, root and KEY LIST
    from whatever it reads back, so the winner could go on to delete a selection it never
    expanded, out of a bucket with versioning off.

    The listing is pinned empty for BOTH runs, which is what makes this the race rather than the
    ordinary reuse the test above covers: the fake reports no archived objects throughout, so
    nothing but the claim can separate them.
    """
    fake = _install({"alice/reports/a.csv": 5})
    first = _event()
    second = {**_event(), "execution": {"name": "other-execution", "startedAt": "2026-09-17T09:31:00.000Z"}}

    winner = m.handler(first, None)
    with pytest.raises(TerminalError) as loser:
        m.handler(second, None)

    assert fake.listed and all(entry["Prefix"].endswith(f"{_REQUEST_ID}/") for entry in fake.listed)
    assert loser.value.reason == "request_id_reused"
    assert winner["copyPlanKey"] == f"archive/{_REQUEST_ID}/copy-plan.json"
    written = json.loads(fake.stored[winner["copyPlanKey"]])
    assert written["requestId"] == _REQUEST_ID
    assert [entry["relKey"] for entry in written["objects"]] == ["reports/a.csv"]
    assert json.loads(fake.stored[_claim_key()])["execution"] == _EXECUTION
    assert _no_real_notifications == []


def test_the_loser_of_that_race_writes_no_copy_plan_at_all():
    """The claim is taken BEFORE anything else is written, so the refusal costs nothing. A claim
    taken after the plan would still refuse the second run — after it had already overwritten the
    first run's plan, which is the damage rather than a step on the way to it."""
    fake = _install({"alice/reports/a.csv": 5}, stored={_claim_key(): _claim_body("someone-else")})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "request_id_reused"
    assert [put["Key"] for put in fake.puts] == []


def test_the_same_execution_claiming_twice_proceeds_because_a_retry_is_not_a_reuse():
    """A ``Retry`` of this verb meets its own claim. Reading the holder back is the only thing
    that tells that apart from a second execution, which is why a bare "the key is taken" answer
    would refuse every retried archive."""
    fake = _install(
        {"alice/reports/a.csv": 5}, stored={_claim_key(): _claim_body()}
    )

    result = m.handler(_event(), None)

    assert result["objectCount"] == 1
    assert json.loads(fake.stored[_claim_key()])["execution"] == _EXECUTION


@pytest.mark.parametrize(
    ("stored", "label"),
    [({}, "absent"), ({f"archive/{_REQUEST_ID}/claim.json": b"not json"}, "unparseable")],
    ids=["absent-on-read-back", "unreadable-on-read-back"],
)
def test_a_claim_that_cannot_be_read_back_refuses_rather_than_clearing_the_run(stored, label):
    """**None is not "free".** This is only reached after a create-only write was refused, so
    something IS at the key and the only question is whose. An answer that cannot clear this run
    must not clear it: proceeding would hand the id to a second run, which is the unrecoverable
    case the claim exists to remove."""
    fake = _install({"alice/reports/a.csv": 5})
    fake.stored.update(stored)
    original_put = fake.put_object

    def refuse_the_claim(Bucket, Key, Body, ContentType, **kwargs):
        if Key.endswith("claim.json"):
            raise _S3Error("PreconditionFailed")
        return original_put(Bucket, Key, Body, ContentType, **kwargs)

    fake.put_object = refuse_the_claim

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "request_id_reused", label
    assert [put["Key"] for put in fake.puts] == []


def test_a_transient_read_of_the_claim_retries_rather_than_refusing():
    """A throttled read says nothing about who holds the id, and refusing on it would fail an
    archive that may well hold the claim itself. The state's Retry asks again."""
    fake = _install({"alice/reports/a.csv": 5}, stored={_claim_key(): _claim_body()})
    fake.get_error = _S3Error("SlowDown")

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_a_conflict_on_the_claim_write_retries_because_it_is_about_the_race_not_the_object():
    """S3 answers a create-only write interrupted by a concurrent one with a conflict rather than
    a precondition failure, and documents it as retryable: nothing is known about what is at the
    key, so reading it as "taken" would refuse a run on the strength of a race it might win."""
    fake = _install({"alice/reports/a.csv": 5})

    def conflict(Bucket, Key, Body, ContentType, **kwargs):
        raise _S3Error("ConditionalRequestConflict")

    fake.put_object = conflict

    with pytest.raises(TransientError):
        m.handler(_event(), None)


def test_a_request_with_no_stamped_execution_is_malformed_rather_than_unclaimed():
    """The claim's holder is the execution name, so a request without one cannot be claimed at
    all. It refuses for the reason the execution-keyed manifest paths already do: the fallback
    would be exactly the collision the claim exists to prevent, appearing only under concurrency."""
    fake = _install({"alice/reports/a.csv": 5})
    unstamped = {k: v for k, v in _event().items() if k != "execution"}

    with pytest.raises(TerminalError) as err:
        m.handler(unstamped, None)

    assert err.value.reason == "malformed_event"
    assert [put["Key"] for put in fake.puts] == []
