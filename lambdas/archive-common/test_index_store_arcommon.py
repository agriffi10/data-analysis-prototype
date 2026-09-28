"""The per-space archive index: what it records, and every way it declines to.

The fake S3 enforces the conditional-put contract (If-Match / If-None-Match against a changing
ETag), because the index is a compare-and-swap and a fake that ignored the preconditions would
pass every race without running one. Every failure here is swallowed by design, so every test
asserts what was WRITTEN — a test that only checked a return value would pass with the index
code never reached.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from arcommon import config, index_store
from cpcommon import cas, clients

BUCKET = "user-bkt"
KEY = "alice/system_settings/archive/index.json"
A1 = "9f2c1b8e-1111-4222-8333-444444444444"
A2 = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"


class _ClientError(Exception):
    """Shaped like botocore's, which is all ``cpcommon.cas`` and the absence check read."""

    def __init__(self, code, status=400):
        super().__init__(code)
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeS3:
    def __init__(self, stored=None, get_error=None, put_error=None):
        self.objects = {} if stored is None else {KEY: (stored, '"etag-0"')}
        self.get_error = get_error
        self.put_error = put_error
        self.put_attempts = 0
        self.version = 0
        self.on_put = None

    def get_object(self, Bucket, Key):
        if self.get_error:
            raise self.get_error
        if Key not in self.objects:
            raise _ClientError("NoSuchKey", 404)
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, Bucket, Key, Body, ContentType=None, IfMatch=None, IfNoneMatch=None):
        self.put_attempts += 1
        if self.put_error:
            raise self.put_error
        if self.on_put:
            hook, self.on_put = self.on_put, None
            hook()
        current = self.objects.get(Key)
        if IfNoneMatch == "*" and current is not None:
            raise _ClientError("ConditionalRequestConflict", 409)
        if IfMatch is not None and (current is None or current[1] != IfMatch):
            raise _ClientError("PreconditionFailed", 412)
        self.version += 1
        self.objects[Key] = (Body, f'"etag-{self.version}"')

    def document(self):
        return json.loads(self.objects[KEY][0])


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _entry(archive_id=A1, name="Q1 reports"):
    return {
        "archiveId": archive_id,
        "name": name,
        "archivedAt": "2026-09-01T10:00:00.000Z",
        "archivedBy": "alice",
        "items": [{"kind": "folder", "path": "reports/"}],
        "itemCount": 1,
        "fileCount": 12,
        "totalBytes": 2048,
        "restore": None,
    }


def _v1(*entries):
    return json.dumps({"version": 1, "archives": list(entries)}).encode()


def test_an_archive_is_recorded_once_however_often_its_verb_runs():
    fake = _install()

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry())
    assert index_store.record_archive(BUCKET, KEY, lambda: _entry())

    assert fake.document() == {"version": 1, "archives": [_entry()]}


def test_two_archives_finishing_together_both_survive_the_race():
    """The second writer's first attempt loses to the first writer; the loop re-reads and keeps both."""
    fake = _install(stored=_v1(_entry(A1)))
    fake.on_put = lambda: index_store.record_archive(BUCKET, KEY, lambda: _entry(A2, "Other"))

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry(A1, "Renamed"))

    names = {row["archiveId"]: row["name"] for row in fake.document()["archives"]}
    assert names == {A1: "Renamed", A2: "Other"}


def test_the_index_keeps_the_newest_entries_up_to_its_cap():
    cap = config.ARCHIVE_INDEX_MAX_ENTRIES
    fake = _install(stored=_v1(*(_entry(f"id-{i}") for i in range(cap))))

    index_store.record_archive(BUCKET, KEY, lambda: _entry("id-new"))

    ids = [row["archiveId"] for row in fake.document()["archives"]]
    assert len(ids) == cap
    assert ids[0] == "id-1" and ids[-1] == "id-new"


def test_each_restore_stage_is_recorded_on_the_archive_it_is_of():
    fake = _install(stored=_v1(_entry(A1), _entry(A2)))

    index_store.record_restore(BUCKET, KEY, A1, "requested", "2026-09-02T08:00:00.000Z")
    index_store.record_restore(BUCKET, KEY, A1, "restored", "2026-09-02T08:00:00.000Z")

    rows = {row["archiveId"]: row for row in fake.document()["archives"]}
    assert rows[A1]["restore"]["status"] == "restored"
    assert rows[A1]["restore"]["requestedAt"] == "2026-09-02T08:00:00.000Z"
    assert rows[A1]["restore"]["updatedAt"] > "2026-09-02T08:00:00.000Z"
    assert rows[A2]["restore"] is None


@pytest.mark.parametrize(
    "stored",
    [None, _v1(_entry(A2)), b"not json", json.dumps({"version": 2, "archives": []}).encode()],
    ids=["no-index", "no-entry-for-it", "corrupt", "newer"],
)
def test_a_restore_never_creates_or_repairs_an_entry(stored):
    fake = _install(stored=stored)

    index_store.record_restore(BUCKET, KEY, A1, "restored", "2026-09-02T08:00:00.000Z")

    assert fake.put_attempts == 0


@pytest.mark.parametrize(
    "stored", [b"not json", json.dumps({"version": 1, "archives": "x"}).encode()], ids=["not-json", "wrong-shape"]
)
def test_a_corrupt_index_is_rebuilt_around_the_new_archive(stored):
    fake = _install(stored=stored)

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry())

    assert fake.document() == {"version": 1, "archives": [_entry()]}


def test_an_index_from_a_newer_build_is_never_overwritten():
    newer = json.dumps({"version": 2, "archives": [], "extra": True}).encode()
    fake = _install(stored=newer)

    index_store.record_archive(BUCKET, KEY, lambda: _entry())

    assert fake.put_attempts == 0
    assert fake.objects[KEY][0] == newer


def test_a_read_that_proves_nothing_writes_nothing():
    """A 403 is not an absence: taking it as one would start a fresh index over the real one."""
    fake = _install(stored=_v1(_entry(A2)), get_error=_ClientError("AccessDenied", 403))

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry()) is False

    assert fake.put_attempts == 0


def test_a_write_that_keeps_failing_is_swallowed_after_trying():
    fake = _install(put_error=_ClientError("AccessDenied", 403))

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry()) is False

    assert fake.put_attempts == 1


def test_the_index_is_written_unescaped_and_compact():
    """The cap was measured on this encoding; ``ensure_ascii`` would triple a CJK name's bytes."""
    fake = _install()

    index_store.record_archive(BUCKET, KEY, lambda: _entry(name="報告"))

    body = fake.objects[KEY][0]
    assert "報告".encode() in body
    assert b", " not in body and b": " not in body


def test_no_key_on_the_state_skips_the_index():
    """A run validated before the key existed reaches a new verb after a deploy."""
    fake = _install()

    assert index_store.record_archive(BUCKET, None, lambda: _entry()) is False
    assert index_store.record_restore(BUCKET, None, A1, "restored", "t") is False

    assert fake.put_attempts == 0


def test_an_entry_names_the_first_items_relative_to_the_space_and_cuts_long_paths():
    long_key = "alice/" + "d" * 300 + ".csv"
    event = {
        "requestId": A1,
        "actor": {"username": "alice"},
        "source": {
            "root": "alice/",
            "items": [
                {"kind": "folder", "key": "alice/reports/"},
                {"kind": "file", "key": long_key},
                {"kind": "file", "key": "alice/a.csv"},
                {"kind": "file", "key": "alice/b.csv"},
            ],
        },
        "archive": {"name": "Q1"},
        "execution": {"startedAt": "2026-09-01T10:00:00.000Z"},
        "totalBytes": 99,
    }

    entry = index_store.entry_from(event, 7)

    assert [item["path"][:8] for item in entry["items"]] == ["reports/", "dddddddd", "a.csv"]
    assert len(entry["items"][1]["path"]) == index_store.ITEM_PATH_MAX_CHARS
    assert entry["items"][1]["path"].endswith(index_store.ELLIPSIS)
    assert (entry["itemCount"], entry["fileCount"], entry["name"]) == (4, 7, "Q1")


def test_a_writer_that_loses_every_race_gives_up_quietly_after_the_last_attempt():
    fake = _install(put_error=_ClientError("PreconditionFailed", 412))

    assert index_store.record_archive(BUCKET, KEY, lambda: _entry()) is False

    assert fake.put_attempts == cas.MAX_ATTEMPTS


def test_an_entry_that_cannot_be_built_costs_the_label_and_nothing_else():
    fake = _install()

    def _broken():
        raise TypeError("a state nobody anticipated")

    assert index_store.record_archive(BUCKET, KEY, _broken) is False

    assert fake.put_attempts == 0
