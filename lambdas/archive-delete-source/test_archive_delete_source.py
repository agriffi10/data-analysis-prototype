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
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"


class _S3Error(Exception):
    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _FakeS3:
    def __init__(self, plan_body, errors_on=(), current=None):
        self._plan_body = plan_body
        self._errors_on = set(errors_on)
        self._current = current
        self.deletes = []
        self.heads = []

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        etags = self._current if self._current is not None else _PLANNED_ETAGS
        if Key not in etags:
            raise _S3Error("404", 404)
        if isinstance(etags[Key], Exception):
            raise etags[Key]
        return {"ETag": etags[Key]}

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._plan_body)}

    def delete_objects(self, Bucket, Delete):
        self.deletes.append({"Bucket": Bucket, "Keys": [o["Key"] for o in Delete["Objects"]]})
        return {
            "Errors": [
                {"Key": o["Key"]} for o in Delete["Objects"] if o["Key"] in self._errors_on
            ]
        }


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


def test_a_source_changed_since_the_plan_is_kept_and_fails_the_run(_no_real_notifications):
    """The vault holds the bytes the copy read, so an original written over after the plan listed
    it is NEWER than its archived copy — and versioning is off, so deleting it destroys the only
    copy of what the user last wrote. The file-ops plane's move has the same shape and compares
    ETags before deleting; this verb deleted by key alone. The changed file stays where it is, the
    unchanged one goes, and the run fails the way any partial deletion does, keeping the archive.
    """
    fake = _install(
        current={**_PLANNED_ETAGS, "alice/reports/a.csv": '"rewritten-after-the-copy"'}
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_delete_incomplete"
    assert fake.deletes == [{"Bucket": "user-bkt", "Keys": ["alice/reports/empty/"]}]
    assert err.value.tokens == {"failed": "1", "total": "1"}


def test_an_entry_the_plan_recorded_no_etag_for_is_never_deleted():
    """Fail-closed, because a missing tag is not evidence the object is unchanged: a plan written
    before the tag was recorded, or one hand-edited, cannot say what was copied. Keeping the file
    costs a partial-deletion message; deleting it on a guess can cost the file."""
    fake = _install(
        _plan([{"relKey": "reports/a.csv", "bytes": 5}, {"relKey": "reports/b.csv", "bytes": 1, "etag": '"b1"'}]),
        current={"alice/reports/a.csv": '"a1"', "alice/reports/b.csv": '"b1"'},
    )

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_delete_incomplete"
    assert fake.deletes == [{"Bucket": "user-bkt", "Keys": ["alice/reports/b.csv"]}]


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
