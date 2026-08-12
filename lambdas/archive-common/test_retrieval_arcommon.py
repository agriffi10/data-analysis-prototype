"""The retrieval module's own rules (SPEC-171 FR-001, FR-002).

Two things live here that nothing else in this repo does: a call that costs real money the
moment it is issued, and a completion check that reads a header rather than a state. The tests
that matter most are the ones about what is TOLERATED — because the tolerances are what make a
re-submission free — and the one about the absent ``Restore`` header, which is the difference
between a slow restore and a dropped one.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from arcommon import retrieval
from arcommon.config import GLACIER_CLASSES, RESTORE_MAX_POLLS, RESTORE_POLL_PAGE
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


class _S3Error(Exception):
    def __init__(self, code, status=400):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class _Body:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload if isinstance(self._payload, bytes) else json.dumps(self._payload).encode()


class _FakeS3:
    def __init__(self, restore_error=None, heads=None, progress=None, get_error=None):
        self.restores = []
        self.puts = []
        self.headed = []
        self._restore_error = restore_error
        self._heads = heads or {}
        self._progress = progress
        self._get_error = get_error

    def restore_object(self, **kwargs):
        self.restores.append(kwargs)
        error = self._restore_error
        if callable(error):
            error = error(kwargs)
        if error:
            raise error

    def head_object(self, Bucket, Key):
        self.headed.append(Key)
        found = self._heads.get(Key, {"Restore": 'ongoing-request="false"'})
        if isinstance(found, Exception):
            raise found
        return found

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise self._get_error
        if self._progress is None:
            raise _S3Error("NoSuchKey", 404)
        return {"Body": _Body(self._progress)}

    def put_object(self, **kwargs):
        self.puts.append(kwargs)


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _keys(count, start=0):
    return [f"personal/alice/archive/x/f{n}.csv" for n in range(start, start + count)]


# ── FR-001: what is asked for, and what is tolerated ─────────────────────────


def test_every_object_is_asked_for_at_the_configured_tier_and_window():
    from arcommon import config

    fake = _install()

    assert retrieval.request_retrieval([("archive-bkt", key) for key in _keys(3)]) == 3
    # A SET, not a list: the pool records completion order, which is not a property of this
    # function and would be a latent flake asserted as one.
    assert {call["Key"] for call in fake.restores} == set(_keys(3))
    for call in fake.restores:
        assert call["RestoreRequest"]["Days"] == config.RESTORE_AVAILABILITY_DAYS
        assert call["RestoreRequest"]["GlacierJobParameters"]["Tier"] == config.RESTORE_TIER


def test_an_already_in_progress_retrieval_is_tolerated_and_never_raised():
    """FR-001 AC4, AND IT IS WHAT MAKES A RE-SUBMISSION FREE. A retrieval already under way is
    the state this call wanted to bring about, so a 409 is success wearing an error's clothes.
    Raised instead, a redriven execution — or a user re-submitting after any later failure —
    would fail on the very objects that were already on their way back."""
    fake = _install(restore_error=_S3Error("RestoreAlreadyInProgress", 409))

    assert retrieval.request_retrieval([("archive-bkt", key) for key in _keys(2)]) == 2
    assert len(fake.restores) == 2


def test_an_object_that_needs_no_retrieval_is_tolerated_too():
    """FR-001 AC5's neighbour, and the thing that keeps the restore path UNCONDITIONAL on
    ARCHIVE_STORAGE_CLASS. `InvalidObjectState` is what S3 says when an object is not in an
    archival class at all; tolerating it means setting the constant to GLACIER_IR would leave
    this machinery harmlessly in place rather than requiring a branch that deletes a code path."""
    _install(restore_error=_S3Error("InvalidObjectState", 403))

    assert retrieval.request_retrieval([("archive-bkt", "personal/alice/archive/x/a.csv")]) == 1


def test_a_genuine_failure_raises_but_only_after_every_object_was_attempted():
    """FR-001 AC7. The failure fails the run either way, and a half-issued batch would make the
    re-submission the user is being asked for cost more retrievals than it had to."""
    def _fail_one(call):
        return _S3Error("AccessDenied", 403) if call["Key"].endswith("f1.csv") else None

    fake = _install(restore_error=_fail_one)

    # The RAW fault, not TransientError and not a TerminalError: a deterministic failure here
    # propagates for the Map to fail the child on, and wrapping it would hide the S3 code an
    # operator needs.
    with pytest.raises(_S3Error):
        retrieval.request_retrieval([("archive-bkt", key) for key in _keys(4)])

    assert len(fake.restores) == 4, "a failure stranded the rest of the batch un-requested"


def test_a_throttle_raises_transient_so_the_map_retries_the_batch():
    _install(restore_error=_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        retrieval.request_retrieval([("archive-bkt", key) for key in _keys(2)])


def test_the_bucket_travels_per_object_rather_than_being_taken_off_the_first():
    """The caller is a Map child holding manifest items and no request, so a bucket read off
    item zero and applied to the rest would be an assumption nothing on that state can check."""
    fake = _install()

    retrieval.request_retrieval([("archive-bkt", "a"), ("other-bkt", "b")])

    assert {(call["Bucket"], call["Key"]) for call in fake.restores} == {
        ("archive-bkt", "a"),
        ("other-bkt", "b"),
    }


# ── FR-002: the Restore header, and the case that is not a "not yet" ─────────


def test_a_finished_retrieval_reads_complete():
    header = 'ongoing-request="false", expiry-date="Fri, 21 Dec 2012 00:00:00 GMT"'

    assert retrieval.classify({"Restore": header, "StorageClass": "GLACIER"}) == retrieval.COMPLETE


def test_a_running_retrieval_reads_pending():
    assert (
        retrieval.classify({"Restore": 'ongoing-request="true"', "StorageClass": "GLACIER"})
        == retrieval.PENDING
    )


def test_an_absent_header_on_a_glacier_object_is_NEVER_REQUESTED_and_not_a_not_yet():
    """FR-002 AC3, AND IT IS THE ONE CASE THIS FUNCTION EXISTS FOR. Nothing about an archived
    object changes when a retrieval completes — it stays GLACIER, and what appears beside it is a
    temporary copy the header describes — so "no header" cannot mean "not ready yet". It means
    nobody ever asked.

    Read as pending it would burn every remaining iteration, wait six hours, and then report a
    timeout naming the wrong cause for something that was never going to complete.
    """
    for storage_class in GLACIER_CLASSES:
        assert retrieval.classify({"StorageClass": storage_class}) == retrieval.NEVER_REQUESTED


def test_an_absent_header_on_a_non_glacier_object_is_simply_readable():
    """The other side of the same rule. An object S3 reports no storage class for is STANDARD,
    and a STANDARD object needs no retrieval — so treating a missing header as a failure there
    would refuse a restore of something already readable."""
    assert retrieval.classify({}) == retrieval.COMPLETE
    assert retrieval.classify({"StorageClass": "INTELLIGENT_TIERING"}) == retrieval.COMPLETE


def test_a_header_with_no_ongoing_directive_is_read_as_complete_rather_than_guessed_at():
    """A header S3 sent but this parser does not recognise still means a retrieval EXISTS, which
    is the only fact the absent-header rule turns on."""
    assert retrieval.classify({"Restore": 'expiry-date="Fri, 21 Dec 2012 00:00:00 GMT"'}) == (
        retrieval.COMPLETE
    )


# ── FR-002: the paged sweep ──────────────────────────────────────────────────


def test_a_fully_complete_archive_sweeps_to_the_end_in_one_invocation():
    """The half a strict one-page-per-iteration reading gets wrong. Every object was requested at
    once at one tier, so they finish together — stopping after one page would add a five-minute
    Wait per RESTORE_POLL_PAGE objects to a retrieval that had already completed."""
    keys = _keys(RESTORE_POLL_PAGE * 2 + 5)
    _install()

    assert retrieval.advance("archive-bkt", keys, 0) == (len(keys), True)


def test_a_pending_object_stops_the_sweep_at_its_own_PAGE_and_not_at_its_index():
    """Progress is recorded at page granularity, so the next iteration re-heads that page and
    nothing before it. Stopping at the pending object's own index would be finer and would also
    mean re-heading a partial page on every iteration for the rest of the wait."""
    keys = _keys(RESTORE_POLL_PAGE + 10)
    pending = {keys[RESTORE_POLL_PAGE + 3]: {"Restore": 'ongoing-request="true"'}}
    _install(heads=pending)

    assert retrieval.advance("archive-bkt", keys, 0) == (RESTORE_POLL_PAGE, False)


def test_the_sweep_starts_where_the_last_one_reached_and_re_heads_nothing_below_it():
    """FR-002 AC4. An archive of 200,000 objects must not issue 200,000 heads every five minutes
    for hours."""
    keys = _keys(RESTORE_POLL_PAGE + 20)
    fake = _install(heads={keys[RESTORE_POLL_PAGE + 1]: {"Restore": 'ongoing-request="true"'}})

    retrieval.advance("archive-bkt", keys, RESTORE_POLL_PAGE)

    assert not [key for key in fake.headed if key in set(keys[:RESTORE_POLL_PAGE])]


def test_a_never_requested_object_refuses_the_sweep_rather_than_reporting_pending():
    keys = _keys(4)
    _install(heads={keys[2]: {"StorageClass": "GLACIER"}})

    with pytest.raises(TerminalError) as caught:
        retrieval.advance("archive-bkt", keys, 0)

    assert caught.value.reason == "restore_never_requested"


def test_an_unreadable_archived_object_refuses_rather_than_waiting_out_the_budget():
    keys = _keys(2)
    _install(heads={keys[1]: _S3Error("NoSuchKey", 404)})

    with pytest.raises(TerminalError) as caught:
        retrieval.advance("archive-bkt", keys, 0)

    assert caught.value.reason == "restore_never_requested"


def test_a_throttled_head_raises_transient_and_never_reports_progress_it_did_not_see():
    _install(heads={"personal/alice/archive/x/f0.csv": _S3Error("SlowDown", 503)})

    with pytest.raises(TransientError):
        retrieval.advance("archive-bkt", _keys(2), 0)


def test_a_start_index_outside_the_plan_is_clamped_rather_than_trusted():
    """A recorded index past the end would report a restore complete that had never been looked
    at, and a negative one would slice from the wrong end."""
    _install()

    assert retrieval.advance("archive-bkt", _keys(3), 99) == (3, True)
    assert retrieval.advance("archive-bkt", _keys(3), -5) == (3, True)


# ── FR-002: the progress record, which is an optimisation and not a fact ─────


def test_progress_round_trips_through_the_admin_bucket():
    fake = _install(progress={"pollCount": 7, "completedThrough": 4000, "objectCount": 9000})

    assert retrieval.read_progress("archive/r/restore-progress.json", 9000) == {
        "pollCount": 7,
        "completedThrough": 4000,
    }

    retrieval.write_progress("archive/r/restore-progress.json", "r", 8, 5000, 9000)
    written = json.loads(fake.puts[0]["Body"])
    assert written["pollCount"] == 8 and written["completedThrough"] == 5000


@pytest.mark.parametrize(
    "stored",
    [
        None,
        b"not json",
        {"pollCount": 1, "completedThrough": 2, "objectCount": 999},
        {"pollCount": "seven", "completedThrough": 2, "objectCount": 10},
        {"pollCount": 1, "completedThrough": 99, "objectCount": 10},
        {"pollCount": 1, "completedThrough": -1, "objectCount": 10},
        [1, 2, 3],
    ],
)
def test_every_unusable_progress_record_reads_as_no_progress(stored):
    """**The record is an OPTIMISATION, not a fact**, and every tolerance here follows from that
    one sentence. Losing it costs one iteration a full re-head; refusing on it would fail a
    restore in its fourth hour over a JSON parse. A recorded index that does not fit the plan it
    claims to describe is discarded for the sharper reason: resuming past the end would report a
    restore complete that had never been looked at."""
    _install(progress=stored)

    assert retrieval.read_progress("archive/r/restore-progress.json", 10) == {
        "pollCount": 0,
        "completedThrough": 0,
    }


def test_a_throttled_progress_read_raises_rather_than_reading_as_no_progress():
    """The one way this tolerance could cost something: swallowing a throttle would re-head the
    whole archive, which at the object cap is 20,000 heads paid for a retry that would have
    worked."""
    _install(get_error=_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        retrieval.read_progress("archive/r/restore-progress.json", 10)


def test_a_throttled_progress_write_raises_so_the_states_retry_reruns_the_poll():
    fake = _install()
    fake.put_object = lambda **kw: (_ for _ in ()).throw(_S3Error("SlowDown", 503))

    with pytest.raises(TransientError):
        retrieval.write_progress("archive/r/restore-progress.json", "r", 1, 0, 10)


# ── FR-002: the budget's own boundary ────────────────────────────────────────


def test_the_budget_is_spent_only_at_the_cap_and_not_before_it():
    assert not retrieval.exhausted(RESTORE_MAX_POLLS - 1)
    assert retrieval.exhausted(RESTORE_MAX_POLLS)
    assert retrieval.exhausted(RESTORE_MAX_POLLS + 1)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
