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
from cpcommon.errors import TerminalError, TransientError


class _S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


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


def test_a_dot_segment_is_refused_even_though_it_starts_with_the_allowed_prefix():
    """**Found in review, and the prefix test alone did not catch it.** Keys are rebuilt here
    from a root and a stored relative key, and ``alice/../bob/secrets.csv`` starts with
    ``alice/`` — so containment has to be BOTH of ``cpcommon.paths``' rules, not the first one.

    S3 resolves nothing, so such a key names an object that almost certainly does not exist and
    no delete of anyone else's data follows. It is refused because a containment rule that holds
    only while every consumer stays careful is not a rule, and this consumer is the one that
    deletes.
    """
    fake = _install()

    with pytest.raises(TerminalError) as err:
        delete.delete_keys("user-bkt", ["alice/../bob/secrets.csv"], "alice/")

    assert err.value.reason == "forbidden"
    assert fake.calls == []


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


def test_a_non_string_key_is_refused_rather_than_stringified():
    fake = _install()

    with pytest.raises(TerminalError):
        delete.delete_keys("user-bkt", [None], "alice/")

    assert fake.calls == []


# ── The batching, and the array every response carries ───────────────────────


def test_deletion_is_batched_at_s3s_own_limit():
    """1000 is not a preference: it is what DeleteObjects accepts in one request."""
    fake = _install()
    keys = [f"alice/f{i}.csv" for i in range(2500)]

    result = delete.delete_keys("user-bkt", keys, "alice/")

    assert [len(call["Delete"]["Objects"]) for call in fake.calls] == [1000, 1000, 500]
    assert result == {"deleted": 2500, "failed": 0}
    assert delete.MAX_KEYS_PER_BATCH == 1000


def test_the_quiet_flag_is_set_so_the_errors_array_is_populated_at_all():
    """Without it S3 returns nothing per item, and the whole discipline below reads a list that
    is empty for the wrong reason."""
    fake = _install()

    delete.delete_keys("user-bkt", ["alice/a.csv"], "alice/")

    assert fake.calls[0]["Delete"]["Quiet"] is False


def test_a_per_item_error_is_counted_rather_than_swallowed():
    """**DeleteObjects returns HTTP 200 with a per-item Errors array.** A response inspected only
    by its status code is the defect SPEC-151 fixed on the shared-space teardown, where it freed
    a space name whose objects were still in the bucket. Here it would report a completed archive
    over a source that is still half there."""
    _install(errors_on={"alice/b.csv"})

    result = delete.delete_keys("user-bkt", ["alice/a.csv", "alice/b.csv"], "alice/")

    assert result == {"deleted": 1, "failed": 1}


def test_every_batch_is_attempted_before_anything_is_reported():
    """A denial in the first page must not strand the rest of the objects, and the count is only
    meaningful whole."""
    fake = _install(errors_on={"alice/f0.csv"})
    keys = [f"alice/f{i}.csv" for i in range(1500)]

    result = delete.delete_keys("user-bkt", keys, "alice/")

    assert len(fake.calls) == 2
    assert result == {"deleted": 1499, "failed": 1}


def test_a_deterministic_batch_fault_counts_its_items_and_keeps_going():
    """The whole batch is unaccounted for, so every key in it is counted as failed — fail-closed,
    because which of them landed is genuinely unknown."""
    fake = _install(raise_on=0, error=_S3Error("AccessDenied"))
    keys = [f"alice/f{i}.csv" for i in range(1200)]

    result = delete.delete_keys("user-bkt", keys, "alice/")

    assert len(fake.calls) == 2, "the second batch was never attempted"
    assert result == {"deleted": 200, "failed": 1000}


def test_a_transient_fault_is_raised_only_after_every_batch_has_been_attempted():
    """The caller's Retry then re-runs the whole verb, which is correct because an already-absent
    key is not an error — so the batches that did land cost nothing to repeat."""
    fake = _install(raise_on=0, error=_S3Error("SlowDown"))
    keys = [f"alice/f{i}.csv" for i in range(1200)]

    with pytest.raises(TransientError):
        delete.delete_keys("user-bkt", keys, "alice/")

    assert len(fake.calls) == 2


def test_an_empty_list_issues_nothing_and_reports_nothing():
    fake = _install()

    assert delete.delete_keys("user-bkt", [], "alice/") == {"deleted": 0, "failed": 0}
    assert fake.calls == []


def test_the_counts_never_carry_a_key():
    """The numbers reach a user-facing message, the Step Functions record and
    logs/service=archive/. A failure naming file paths is a disclosure this plane has no reason
    to make, and the field rule binds what a call site chooses to emit."""
    _install(errors_on={"alice/secret-project.csv"})

    result = delete.delete_keys("user-bkt", ["alice/secret-project.csv"], "alice/")

    assert set(result) == {"deleted", "failed"}
    assert "secret-project" not in repr(result)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
