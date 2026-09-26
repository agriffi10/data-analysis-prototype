"""Unit tests for the archive delete-source Lambda (SPEC-169 FR-005).

The only verb in this portal that deletes a user's data. The batching discipline has its own
suite in ``archive-common``; what is tested here is what only the verb decides — that it deletes
exactly the PLAN's keys under exactly the plan's root, that a partial deletion fails the run and
KEEPS the archive copy, and that a re-driven execution completes.
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

import archive_delete_source as m
import pytest
from arcommon import notify
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"


class _S3Error(Exception):
    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    """A stateful S3: deletes remove what they name, so a Retry sees what its first attempt left.

    ``source`` is the originals by key to their current tag (an exception to raise on a head of
    it), ``vault`` the archive prefix's keys, and ``admin`` the admin bucket's objects — the plan
    and whatever decision record a run writes. ``throttle_on`` makes the Nth ``DeleteObjects``
    call raise a retryable fault, once.
    """

    def __init__(self, plan_body, errors_on=(), current=None):
        self._errors_on = set(errors_on)
        self.source = dict(current if current is not None else _PLANNED_ETAGS)
        self.vault = set(_VAULT_KEYS)
        self.admin = {f"archive/{_REQUEST_ID}/copy-plan.json": plan_body}
        self.throttle_on = None
        self.deletes = []
        self.heads = []

    def get_paginator(self, name):
        fake = self

        class _Pages:
            def paginate(self, Bucket, Prefix):
                yield {
                    "Contents": [
                        {"Key": key, "Size": 1} for key in sorted(fake.vault) if key.startswith(Prefix)
                    ]
                }

        return _Pages()

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key not in self.source:
            raise _S3Error("404", 404)
        if isinstance(self.source[Key], Exception):
            raise self.source[Key]
        return {"ETag": self.source[Key]}

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        if Key not in self.admin:
            raise _S3Error("AccessDenied", 403)
        return {"Body": _Body(self.admin[Key])}

    def put_object(self, Bucket, Key, Body, ContentType, IfNoneMatch=None):
        if IfNoneMatch == "*" and Key in self.admin:
            raise _S3Error("PreconditionFailed", 412)
        self.admin[Key] = Body

    def delete_objects(self, Bucket, Delete):
        keys = [o["Key"] for o in Delete["Objects"]]
        self.deletes.append({"Bucket": Bucket, "Keys": keys})
        if self.throttle_on == len(self.deletes):
            raise _S3Error("SlowDown", 503)
        store = self.vault if Bucket == "archive-bkt" else self.source
        for key in keys:
            if key not in self._errors_on:
                store.discard(key) if isinstance(store, set) else store.pop(key, None)
        return {"Errors": [{"Key": key} for key in keys if key in self._errors_on]}


def _decision(fake):
    """The decision record the run wrote, parsed."""
    return json.loads(fake.admin[f"archive/{_REQUEST_ID}/source-decision.json"])


_VAULT_KEYS = (
    f"personal/alice/archive/{_REQUEST_ID}/_manifest.json",
    f"personal/alice/archive/{_REQUEST_ID}/reports/a.csv",
    f"personal/alice/archive/{_REQUEST_ID}/reports/empty/",
)

_PLANNED_ETAGS = {
    "alice/reports/a.csv": '"a1"',
    "alice/reports/empty/": '"d41d8cd98f00b204e9800998ecf8427e"',
}


def _plan(objects=None):
    objects = objects or [
        {"relKey": "reports/a.csv", "bytes": 5, "etag": '"a1"'},
        {"relKey": "reports/empty/", "bytes": 0, "etag": '"d41d8cd98f00b204e9800998ecf8427e"'},
    ]
    return json.dumps({
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": f"personal/alice/archive/{_REQUEST_ID}/"},
        "objectCount": len(objects),
        "totalBytes": sum(o["bytes"] for o in objects),
        "objects": objects,
    }).encode()


def _install(plan_body=None, errors_on=(), current=None):
    fake = _FakeS3(plan_body or _plan(), errors_on, current)
    clients._s3 = fake
    return fake


def _event(object_count=2):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": f"personal/alice/archive/{_REQUEST_ID}/"},
        "copyPlanKey": f"archive/{_REQUEST_ID}/copy-plan.json",
        "objectCount": object_count,
        "totalBytes": 5,
        "manifestKey": f"personal/alice/archive/{_REQUEST_ID}/_manifest.json",
    }


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_it_deletes_exactly_the_plans_keys_in_the_plans_bucket():
    """An object that was never copied is also never deleted, because the plan is the same list
    the manifest was built from and the commit gate counted against."""
    fake = _install()

    result = m.handler(_event(), None)

    assert fake.deletes == [
        {"Bucket": "user-bkt", "Keys": ["alice/reports/a.csv", "alice/reports/empty/"]}
    ]
    assert result["deletedCount"] == 2


@pytest.mark.parametrize(
    "refused,counted",
    [({"alice/reports/a.csv"}, "1 of 1"), ({"alice/reports/empty/"}, "1 of 2")],
    ids=["the-file-stays", "the-folder-placeholder-stays"],
)
def test_a_partial_deletion_fails_the_run_and_keeps_the_archive(
    _no_real_notifications, refused, counted
):
    """FR-005 AC4. The user's data then exists in two places, which is recoverable by hand; the
    alternative — removing the archive after a partial source deletion — is not recoverable at
    all. The message says nothing has been lost, because nothing has.

    **The count is in files, and the plan holds one file and one New-folder placeholder.** A
    file left behind is "1 of 1", because the placeholder that did go is not a file; a placeholder
    left behind is counted, as "1 of 2", because it is the thing that could not be removed."""
    _install(errors_on=refused)

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_delete_incomplete"
    assert _no_real_notifications == [
        (
            "alice",
            (
                f"Couldn't archive that: your files were archived, but {counted} could not be "
                "removed from your space. Nothing has been lost - they are safe in both places. "
                "Please contact an administrator."
            ),
        )
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("requestId", "11111111-2222-4333-8444-555555555555"),
        ("source", {"bucket": "shared-bkt", "root": "team-space/"}),
        ("objectCount", 99),
    ],
    ids=["another-request", "another-space", "another-selection-size"],
)
def test_a_plan_that_does_not_describe_this_run_deletes_nothing(field, value):
    """**Found in review, and it is the half that could have deleted the wrong data.** The plan's
    key is a pure function of the request id — which is what makes a Retry rewrite the same object
    — so a second execution carrying a reused id OVERWRITES it. This verb takes the bucket, the
    root and the key list from whatever it reads back, and the commit gate upstream compares two
    values that both come from the STATE, so it cannot see a plan that changed underneath it.

    Without this check, run 1 could pass its own gate on its own counts and then delete run 2's
    selection — in either space bucket, since the grant covers both.
    """
    plan = json.loads(_plan())
    plan[field] = value
    if field == "objectCount":
        plan["objects"] = plan["objects"] + [{"relKey": f"filler{i}.csv", "bytes": 0} for i in range(97)]
    fake = _install(json.dumps(plan).encode())

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "plan_superseded"
    assert fake.deletes == []


def test_an_original_changed_since_the_plan_refuses_the_whole_deletion_and_removes_the_vault_copy(
    _no_real_notifications,
):
    """The vault holds the version the plan listed, so an original written over since is NEWER
    than its archived copy, and with versioning off deleting it destroys what the user last wrote.
    So nothing is deleted — not even the unchanged originals, which would otherwise go into a vault
    the user holds no receipt for and cannot find — and the vault copy is removed, leaving the user
    exactly where they started, and told so."""
    fake = _install(
        current={**_PLANNED_ETAGS, "alice/reports/a.csv": '"rewritten-after-the-copy"'}
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_changed_during_archive"
    assert fake.deletes == [
        {
            "Bucket": "archive-bkt",
            "Keys": sorted(_VAULT_KEYS),
        }
    ]
    assert _no_real_notifications == [
        (
            "alice",
            (
                "Couldn't archive that: 1 file(s) changed while they were being archived, so "
                "nothing was archived and your files are exactly where they were. Please try again."
            ),
        )
    ]


def test_an_entry_the_plan_recorded_no_etag_for_is_never_deleted():
    """Fail-closed, because a missing tag is not evidence the object is unchanged: a plan written
    before the tag was recorded, or edited since, cannot say what the vault holds. It is never
    headed, and it refuses the deletion like a changed original."""
    fake = _install(
        _plan([{"relKey": "reports/a.csv", "bytes": 5}, {"relKey": "reports/b.csv", "bytes": 1, "etag": '"b1"'}]),
        current={"alice/reports/a.csv": '"a1"', "alice/reports/b.csv": '"b1"'},
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_changed_during_archive"
    assert "alice/reports/a.csv" not in fake.heads
    assert all(call["Bucket"] == "archive-bkt" for call in fake.deletes)


def test_a_retry_after_an_interrupted_refusal_deletes_no_original_even_when_none_now_looks_changed():
    """The refusal removes the vault copy, and a throttle part way through that removal re-runs the
    verb. If the first attempt's "change" was a head it could not read, every original now looks
    unchanged — and without counting the vault, the re-run would delete them all with the copy
    already half gone. The vault is counted first, and a short one refuses."""
    fake = _install()
    fake.vault.discard(f"personal/alice/archive/{_REQUEST_ID}/reports/a.csv")

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "archive_copy_unconfirmed"
    assert all(call["Bucket"] == "archive-bkt" for call in fake.deletes)


_THREE = {"alice/r/a.csv": '"a"', "alice/r/b.csv": '"b"', "alice/r/c.csv": '"c"'}


def _three_file_run(monkeypatch):
    """Three planned files, one per delete batch, and the vault holding all three."""
    monkeypatch.setattr(m.delete, "MAX_KEYS_PER_BATCH", 1)
    fake = _install(
        _plan([
            {"relKey": key.removeprefix("alice/"), "bytes": 1, "etag": tag}
            for key, tag in _THREE.items()
        ]),
        current=_THREE,
    )
    root = f"personal/alice/archive/{_REQUEST_ID}/"
    fake.vault = {f"{root}_manifest.json"} | {f"{root}{key.removeprefix('alice/')}" for key in _THREE}
    event = {**_event(object_count=3), "totalBytes": 3}
    return fake, event


def test_a_retry_after_a_partial_deletion_never_turns_into_a_refusal(monkeypatch):
    """The verdict was DELETE and one batch throttled after another had gone. Before the Retry the
    user saved a file still waiting to be deleted. Re-deciding would refuse and remove the vault —
    the only copy of what the first attempt already deleted. Following the recorded verdict keeps
    the changed file, deletes nothing else, and leaves the vault whole."""
    fake, event = _three_file_run(monkeypatch)
    fake.throttle_on = 2
    with pytest.raises(TransientError):
        m.handler(event, None)
    fake.source["alice/r/b.csv"] = '"b-saved-after-the-first-attempt"'

    with pytest.raises(TerminalError) as err:
        m.handler(event, None)

    assert err.value.reason == "source_delete_incomplete"
    assert _decision(fake)["decision"] == "delete"
    assert fake.source == {"alice/r/b.csv": '"b-saved-after-the-first-attempt"'}
    assert len(fake.vault) == 4
    assert not any(call["Bucket"] == "archive-bkt" for call in fake.deletes)


def test_a_retry_after_a_partial_refusal_never_turns_into_a_deletion(monkeypatch):
    """The verdict was REFUSE and removing the vault copy throttled part way. Before the Retry the
    user deleted the file they had changed, so nothing now heads as changed. Re-deciding would
    delete every original with the copy half gone; following the recorded refusal finishes
    removing the copy and deletes no original."""
    fake, event = _three_file_run(monkeypatch)
    fake.source["alice/r/a.csv"] = '"a-changed"'
    fake.throttle_on = 1
    with pytest.raises(TransientError):
        m.handler(event, None)
    del fake.source["alice/r/a.csv"]

    with pytest.raises(TerminalError) as err:
        m.handler(event, None)

    assert err.value.reason == "source_changed_during_archive"
    assert _decision(fake) == {"changed": 1, "decision": "refuse", "execution": None}
    assert set(fake.source) == {"alice/r/b.csv", "alice/r/c.csv"}
    assert fake.vault == set()
    assert not any(call["Bucket"] == "user-bkt" for call in fake.deletes)


def test_a_source_already_gone_is_not_a_change_so_a_replay_completes():
    """A Retry after a lost response re-runs the verb over keys its first attempt removed. Those
    head as 404, and reading that as "changed" would fail an archive that finished — so absence is
    the outcome asked for, exactly as the deletion itself treats it."""
    fake = _install(current={"alice/reports/empty/": _PLANNED_ETAGS["alice/reports/empty/"]})

    result = m.handler(_event(), None)

    assert result["deletedCount"] == 2
    assert fake.deletes == [
        {"Bucket": "user-bkt", "Keys": ["alice/reports/a.csv", "alice/reports/empty/"]}
    ]
