"""The batched deleter, which is the only code in this portal that removes a user's data.

The rules it has to hold are SPEC-151's, and each of them has a failure this plane would suffer
uniquely: a per-item ``Errors`` array read only as a status code reports a completed archive over
a half-deleted source; a batch abandoned on the first failure strands the rest; a delete issued
against a key the bucket policy refuses stops HALF WAY THROUGH, after some of the user's data has
already gone.

Runnable under pytest or directly: python3 test_delete_arcommon.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import delete
from cpcommon import clients
from cpcommon.errors import TerminalError


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
