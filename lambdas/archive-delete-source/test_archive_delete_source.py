"""Unit tests for the archive delete-source Lambda (SPEC-169 FR-005).

The only verb in this portal that deletes a user's data. The batching discipline has its own
suite in ``archive-common``; what is tested here is what only the verb decides — that it deletes
exactly the PLAN's keys under exactly the plan's root, that a partial deletion fails the run and
KEEPS the archive copy, and that a re-driven execution completes.

Runnable under pytest or directly: python3 test_archive_delete_source.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
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


class _FakeS3:
    def __init__(self, plan_body, errors_on=()):
        self._plan_body = plan_body
        self._errors_on = set(errors_on)
        self.deletes = []

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


def _plan(objects=None):
    objects = objects or [
        {"relKey": "reports/a.csv", "bytes": 5},
        {"relKey": "reports/empty/", "bytes": 0},
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


def _install(plan_body=None, errors_on=()):
    fake = _FakeS3(plan_body or _plan(), errors_on)
    clients._s3 = fake
    return fake


def _event():
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": f"personal/alice/archive/{_REQUEST_ID}/"},
        "copyPlanKey": f"archive/{_REQUEST_ID}/copy-plan.json",
        "objectCount": 2,
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


def test_a_folder_placeholder_is_deleted_with_everything_else():
    """It was archived — that is how an empty folder survives — so leaving it behind would make
    the source folder reappear in the browser as an empty shell."""
    fake = _install()

    m.handler(_event(), None)

    assert "alice/reports/empty/" in fake.deletes[0]["Keys"]


def test_a_partial_deletion_fails_the_run_and_keeps_the_archive():
    """FR-005 AC4. The user's data then exists in two places, which is recoverable by hand; the
    alternative — removing the archive after a partial source deletion — is not recoverable at
    all. The message says nothing has been lost, because nothing has."""
    _install(errors_on={"alice/reports/a.csv"})

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "source_delete_incomplete"
    assert err.value.tokens == {"failed": "1", "total": "2"}


def test_the_failure_reports_counts_and_never_a_key(_no_real_notifications):
    """A failure message naming user file paths is a disclosure this plane has no reason to
    make, and the field rule binds what a call site chooses to emit."""
    _install(errors_on={"alice/reports/a.csv"})

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    message = _no_real_notifications[0][1]
    assert "reports/a.csv" not in message
    assert "1 of 2" in message


def test_a_key_outside_the_plans_root_fails_before_any_delete_is_issued():
    """Defence in depth over a plan whose provenance is this same execution. It fails loudly
    rather than filtering: a silent filter would delete a source the archive is missing objects
    from."""
    plan = json.loads(_plan())
    plan["objects"].append({"relKey": "../bob/secrets.csv", "bytes": 1})
    plan["objectCount"] = 3
    fake = _install(json.dumps(plan).encode())

    with pytest.raises(TerminalError):
        m.handler(_event(), None)

    assert fake.deletes == []


def test_a_marker_in_the_plan_fails_the_run_rather_than_being_issued(_no_real_notifications):
    """FR-005 AC6. Both bucket policies deny DeleteObject on it at any depth, so issuing it would
    be refused MID-BATCH — after some of the user's data had already gone. The expansion excludes
    markers, so reaching this means an upstream guarantee has broken."""
    plan = json.loads(_plan())
    plan["objects"] = [{"relKey": "reports/DO_NOT_DELETE.txt", "bytes": 0}]
    plan["objectCount"] = 1
    fake = _install(json.dumps(plan).encode())

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "protected_marker"
    assert fake.deletes == []


def test_deletion_is_replay_safe_so_a_redriven_execution_completes():
    """S3 reports an already-absent key as deleted, which is what makes the state's Retry safe on
    a verb whose effect is a deletion."""
    fake = _install()

    first = m.handler(_event(), None)
    second = m.handler(_event(), None)

    assert first["deletedCount"] == second["deletedCount"] == 2
    assert len(fake.deletes) == 2


def test_an_unreadable_plan_refuses_rather_than_deleting_what_it_can_read():
    """The plan is the ONLY definition of what was copied; a partial read would delete a subset
    chosen by corruption."""
    _install(b"not json")

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "plan_unreadable"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
