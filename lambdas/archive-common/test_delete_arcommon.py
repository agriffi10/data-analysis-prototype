"""The batched deleter, which is the only code in this portal that removes a user's data.

The rules it has to hold are SPEC-151's, and each of them has a failure this plane would suffer
uniquely: a per-item ``Errors`` array read only as a status code reports a completed archive over
a half-deleted source; a batch abandoned on the first failure strands the rest; a delete issued
against a key the bucket policy refuses stops HALF WAY THROUGH, after some of the user's data has
already gone.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import delete
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


class _FakeS3:
    """Records every DeleteObjects call, and can fail a chosen one."""

    def __init__(self, errors_on=(), raise_on=None, error=None):
        self.calls = []
        self._errors_on = set(errors_on)
        self._raise_on = raise_on
        self._error = error

    def delete_objects(self, Bucket, Delete):
        index = len(self.calls)
        self.calls.append({"Bucket": Bucket, "Delete": Delete})
        if self._raise_on == index:
            raise self._error
        failed = [
            {"Key": obj["Key"]} for obj in Delete["Objects"] if obj["Key"] in self._errors_on
        ]
        return {"Errors": failed}


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


# ── The pre-check: a refusal that has moved nothing ──────────────────────────


def test_a_key_outside_the_allowed_prefix_is_refused_before_anything_is_issued():
    """The ordering is the point of the function. A bad key does not fail the run as a whole —
    it fails it PART WAY THROUGH, after some of the user's data has already been deleted."""
    fake = _install()

    with pytest.raises(TerminalError) as err:
        delete.delete_keys("user-bkt", ["alice/a.csv", "bob/b.csv"], "alice/")

    assert err.value.reason == "forbidden"
    assert fake.calls == [], "a delete was issued before the whole list had been checked"


def test_a_prefix_marker_is_refused_for_the_whole_list():
    """Both bucket policies deny DeleteObject on it at any depth, so issuing one would be
    refused mid-batch. Reaching this means an upstream guarantee has already broken, which is
    why it fails loudly rather than filtering: a silent filter would delete a source the archive
    is missing objects from."""
    fake = _install()

    with pytest.raises(TerminalError) as err:
        delete.delete_keys("user-bkt", ["alice/a.csv", "alice/x/DO_NOT_DELETE.txt"], "alice/")

    assert err.value.reason == "protected_marker"
    assert fake.calls == []


# ── The batching, and the array every response carries ───────────────────────


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 403}}
        super().__init__(code)


def test_a_failure_counts_its_folder_placeholders_from_the_keys_that_failed():
    """The count delete-source's sentence needs to leave placeholders out of its total. Two ways
    to fail, and each is counted from a different place: a whole batch refused counts its own
    keys, and a key refused inside a batch counts from the key S3 names in ``Errors``. The first
    batch is full, so the second one exists at all."""
    first = [f"alice/f{i}.csv" for i in range(delete.MAX_KEYS_PER_BATCH - 1)] + ["alice/empty/"]
    second = ["alice/other/", "alice/last.csv"]
    _install(errors_on={"alice/other/"}, raise_on=0, error=_S3Error("AccessDenied"))

    removed = delete.delete_keys("user-bkt", first + second, "alice/")

    assert removed == {
        "deleted": 1,
        "failed": delete.MAX_KEYS_PER_BATCH + 1,
        "failedFolders": 2,
    }


class _HeadError(Exception):
    def __init__(self, code, status):
        self.response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
        super().__init__(code)


class _HeadingS3:
    """Answers each head from a table: a tag, or an exception to raise."""

    def __init__(self, answers):
        self._answers = answers
        self.heads = []

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        answer = self._answers[Key]
        if isinstance(answer, Exception):
            raise answer
        return {"ETag": answer}


def test_only_an_original_still_carrying_its_planned_tag_may_be_deleted():
    """Kept: a rewritten original, one that could not be read, and one the plan recorded no tag
    for, which is never headed. Absence is not a change — a replay re-heads what it removed."""
    fake = _HeadingS3({
        "alice/same.csv": '"a"',
        "alice/rewritten.csv": '"new"',
        "alice/unreadable.csv": _HeadError("AccessDenied", 403),
        "alice/gone.csv": _HeadError("404", 404),
    })
    clients._s3 = fake

    kept = delete.changed_keys(
        "user-bkt",
        {
            "alice/same.csv": '"a"',
            "alice/rewritten.csv": '"old"',
            "alice/unreadable.csv": '"u"',
            "alice/gone.csv": '"g"',
            "alice/untagged.csv": None,
        },
    )

    assert kept == {"alice/rewritten.csv", "alice/unreadable.csv", "alice/untagged.csv"}
    assert "alice/untagged.csv" not in fake.heads


def test_a_throttled_head_retries_rather_than_reading_as_unchanged():
    """A sweep that cannot see an original must not conclude it stood still."""
    clients._s3 = _HeadingS3({"alice/a.csv": _HeadError("SlowDown", 503)})

    with pytest.raises(TransientError):
        delete.changed_keys("user-bkt", {"alice/a.csv": '"a"'})
