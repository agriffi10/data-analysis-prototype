"""Unit tests for the archive build-transfer-manifest Lambda (SPEC-169 FR-002).

The dataset the Distributed Map reads. What matters here is that every line carries the four
things the engine needs — source, destination, SIZE and STORAGE CLASS — and that the destination
comes from the one key builder a restore will invert. Runnable under pytest or directly:
python3 test_archive_build_transfer_manifest.py.
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

import archive_build_transfer_manifest as m
import pytest
from arcommon import notify, paths
from arcommon.config import ARCHIVE_STORAGE_CLASS
from cpcommon import clients
from cpcommon.errors import TerminalError
from cpcommon.transfer import copy as copy_mod

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ROOT = f"personal/alice/archive/{_REQUEST_ID}/"


class _FakeS3:
    def __init__(self, plan_body):
        self._plan_body = plan_body
        self.puts = []

    def get_object(self, Bucket, Key):
        class _Body:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

        return {"Body": _Body(self._plan_body)}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.puts.append({"Bucket": Bucket, "Key": Key, "Body": Body, "ContentType": ContentType})
        return {}


def _plan(objects=None):
    objects = objects or [
        {"relKey": "reports/2026/q1.csv", "bytes": 90_112},
        {"relKey": "reports/empty/", "bytes": 0},
    ]
    return json.dumps({
        "requestId": _REQUEST_ID,
        "actor": "alice",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "objectCount": len(objects),
        "totalBytes": sum(o["bytes"] for o in objects),
        "objects": objects,
    }).encode()


def _install(plan_body=None):
    fake = _FakeS3(plan_body or _plan())
    clients._s3 = fake
    return fake


def _event(execution="arch-exec-1"):
    return {
        "requestId": _REQUEST_ID,
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "copyPlanKey": f"archive/{_REQUEST_ID}/copy-plan.json",
        "execution": {"name": execution, "startedAt": "2026-08-10T14:02:11.123Z"},
        "objectCount": 2,
        "totalBytes": 90_112,
    }


def _lines(fake):
    return [json.loads(line) for line in fake.puts[0]["Body"].decode().splitlines()]


@pytest.fixture(autouse=True)
def _no_real_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def test_every_line_carries_the_storage_class_from_the_one_definition():
    """FR-002 AC1. The choice the whole arc is shaped by — a GLACIER object cannot be copied at
    all until a billed, hours-long retrieval has finished — so a second home for it is how one
    verb archives to a class the restore path was not built for."""
    fake = _install()

    m.handler(_event(), None)

    assert {line["storageClass"] for line in _lines(fake)} == {ARCHIVE_STORAGE_CLASS}


def test_every_line_carries_the_size_the_plan_measured():
    """Not decoration: ``copy_one`` chooses the single-copy or multipart path by this number, and
    a manifest without it would send every object over S3's 5 GiB single-copy limit down the path
    that cannot carry it."""
    fake = _install()

    m.handler(_event(), None)
    lines = _lines(fake)

    assert [line["size"] for line in lines] == [90_112, 0]
    assert max(line["size"] for line in lines) < copy_mod.MULTIPART_COPY_THRESHOLD


def test_the_destination_comes_from_the_one_key_builder():
    """The archived key is what a restore reconstructs an origin FROM, so a builder that
    disagreed would put objects where SPEC-170 looks for something else — and the disagreement
    would surface as a restore writing to the wrong place, not as a failure."""
    fake = _install()

    m.handler(_event(), None)
    lines = _lines(fake)

    assert [line["destKey"] for line in lines] == [
        paths.archived_key(_ARCHIVE_ROOT, "alice/", "alice/reports/2026/q1.csv"),
        paths.archived_key(_ARCHIVE_ROOT, "alice/", "alice/reports/empty/"),
    ]
    assert lines[0]["destKey"] == f"{_ARCHIVE_ROOT}reports/2026/q1.csv"
    assert lines[0]["srcKey"] == "alice/reports/2026/q1.csv"
    assert (lines[0]["srcBucket"], lines[0]["destBucket"]) == ("user-bkt", "archive-bkt")


def test_the_manifest_is_json_lines_with_no_trailing_blank():
    """A blank final line is a line the reader may hand back as an empty item, and an empty item
    reaches the copier as a transfer with no source."""
    fake = _install()

    m.handler(_event(), None)
    body = fake.puts[0]["Body"].decode()

    assert not body.endswith("\n")
    assert len(body.splitlines()) == 2
    assert fake.puts[0]["ContentType"] == "application/jsonl"


def test_the_manifest_key_carries_the_stamped_execution_name():
    """FR-002 AC2/AC3. Execution-unique where the plan deliberately is not, and the name comes
    from the Pass-stamped context rather than from ``$$`` in this task's own Parameters."""
    fake = _install()

    result = m.handler(_event("arch-exec-7"), None)

    assert fake.puts[0]["Key"] == f"archive/{_REQUEST_ID}/arch-exec-7/transfer-manifest.jsonl"
    assert result["transfer"]["manifestKey"] == fake.puts[0]["Key"]
    assert result["transfer"]["manifestBucket"] == "admin-bkt"


def test_an_unstamped_execution_is_refused_rather_than_keyed_on_the_request_alone():
    """The fallback a missing name invites is exactly the collision the execution segment exists
    to prevent, and it would only ever appear under concurrency."""
    _install()

    event = _event()
    event.pop("execution")

    with pytest.raises(TerminalError):
        m.handler(event, None)


def test_the_item_count_is_what_the_choice_gates_the_map_on():
    fake = _install()

    result = m.handler(_event(), None)

    assert result["transfer"]["itemCount"] == len(_lines(fake)) == 2
    assert result["transfer"]["resultsPrefix"] == f"archive/{_REQUEST_ID}/results"


def test_a_plan_short_of_its_recorded_count_is_refused_before_a_line_is_written():
    """The shape that would otherwise produce a manifest short of its lines, a copy that
    succeeded over it, a commit gate that agreed with both, and a deletion of a source the
    archive does not hold."""
    truncated = json.loads(_plan())
    truncated["objectCount"] = 5
    fake = _install(json.dumps(truncated).encode())

    with pytest.raises(TerminalError) as err:
        m.handler(_event(), None)

    assert err.value.reason == "plan_unreadable"
    assert fake.puts == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
