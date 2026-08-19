"""The shared compare-and-set lock protocol.

``tbcommon``'s own suite exercises the protocol end to end through the table-builder binding and
was deliberately NOT edited when the protocol moved here — that suite passing unchanged is the
proof the extraction preserved behaviour. What this file adds is what is genuinely about the
SHARED module: the seams a second domain depends on, and the properties no single binding's tests
can state.

The fake implements REAL conditional-put semantics, because every property here rests on what
happens when two writers race. A fake that ignored ``IfMatch``/``IfNoneMatch`` would be green
regardless of the code.
"""

import json
import os
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import clients, lock

HOLDER = "arn:aws:states:us-east-1:1:execution:orchestrator:run-a"
OTHER = "arn:aws:states:us-east-1:1:execution:orchestrator:run-b"
BUCKET = "dat-prod-athena-admin"
KEY = "locks/file-ops/abc123.json"

WORDING = lock.LockWording(
    acquired="space lock acquired",
    refused="space lock refused",
    stealing_stale="stealing stale space lock",
    stealing_unreadable="stealing unreadable space lock",
    released="space lock released",
    release_failed="space lock release failed",
)

FIELDS = {"space": "alice", "bucket": BUCKET}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeS3:
    """Conditional-put semantics over a changing ETag, matching what AWS documents."""

    def __init__(self):
        self.objects = {}
        self.gets = []
        self.puts = []
        self.deletes = []
        self._n = 0

    def get_object(self, Bucket, Key):
        self.gets.append({"Bucket": Bucket, "Key": Key})
        if Key not in self.objects:
            raise KeyError(Key)
        body, etag = self.objects[Key]
        return {"Body": _Body(body), "ETag": etag}

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        current = self.objects.get(key)
        self.puts.append(
            {
                "Bucket": kwargs.get("Bucket"),
                "IfMatch": kwargs.get("IfMatch"),
                "IfNoneMatch": kwargs.get("IfNoneMatch"),
                "Key": key,
            }
        )
        if kwargs.get("IfNoneMatch") == "*" and current is not None:
            raise _ClientError("PreconditionFailed")
        if kwargs.get("IfMatch") is not None:
            if current is None:
                raise _ClientError("NoSuchKey")
            if current[1] != kwargs["IfMatch"]:
                raise _ClientError("PreconditionFailed")
        self._n += 1
        etag = f'"etag-{self._n}"'
        self.objects[key] = (kwargs["Body"], etag)
        return {"ETag": etag}

    def delete_object(self, **kwargs):
        self.deletes.append(kwargs)

    def state_of(self, key):
        return json.loads(self.objects[key][0])


class _ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(clients, "_s3", fake)
    return fake


def _read(key):
    """The reader a domain binding supplies, in its simplest honest form."""
    try:
        response = clients.s3().get_object(Bucket=BUCKET, Key=key)
        return response["Body"].read(), response.get("ETag")
    except Exception:  # noqa: BLE001
        return None, None


def _acquire(holder=HOLDER, read=None, stale=3600):
    return lock.acquire(
        bucket=BUCKET,
        key=KEY,
        holder=holder,
        stale_after_seconds=stale,
        wording=WORDING,
        fields=FIELDS,
        read=read or _read,
    )


def _release(etag):
    return lock.release(bucket=BUCKET, key=KEY, etag=etag, wording=WORDING, fields=FIELDS)


def _seed(fake, *, holder, acquired_at, etag='"etag-0"'):
    body = json.dumps({"version": 1, "holder": holder, "acquiredAt": acquired_at}).encode("utf-8")
    fake.objects[KEY] = (body, etag)


def _iso(seconds_ago):
    return (datetime.now(UTC) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── The seam a second domain depends on ──────────────────────────────────────


def test_the_injected_reader_is_the_one_the_protocol_calls(s3):
    """The reader is a parameter so a caller's test can pin it, which is the only way to reach
    the concurrent case: two acquires seeing one stale tag, decided by the compare-and-set rather
    than by the age check. If the protocol read S3 itself, that seam would not exist and the
    second caller would be turned away by the live-holder branch instead."""
    seen = []

    def reader(key):
        seen.append(key)
        return None, None

    _acquire(read=reader)

    assert seen == [KEY]


def test_two_simultaneous_steals_and_only_one_wins(s3):
    """Both readers see the SAME stale tag, so the compare-and-set decides."""
    _seed(s3, holder=OTHER, acquired_at=_iso(4000))
    stale = s3.objects[KEY]

    first, first_etag = _acquire(HOLDER, read=lambda key: (stale[0], stale[1]))
    second, second_etag = _acquire(OTHER, read=lambda key: (stale[0], stale[1]))

    assert first is True
    assert first_etag is not None
    assert second is False
    assert second_etag is None
    assert s3.state_of(KEY)["holder"] == HOLDER


def test_a_reclaim_returns_a_NEW_tag_and_the_old_one_is_dead(s3):
    """The re-claim branch REWRITES the object, so an earlier tag no longer matches.

    A caller that acquires more than once — a waiter looping until the lock frees — must release
    against the most recent tag. Releasing against the first is a silent no-op, and the lock then
    stays held until it goes stale, which for a machine-ceiling-derived threshold is hours. The
    behaviour is correct; this test exists so a caller cannot be unaware of it.
    """
    _, first = _acquire()
    _, second = _acquire()

    assert first is not None
    assert second is not None
    assert first != second

    _release(first)
    assert s3.state_of(KEY)["holder"] == HOLDER

    _release(second)
    assert s3.state_of(KEY)["holder"] is None


# ── Properties the protocol owns whichever domain binds it ───────────────────


def test_the_holder_guard_is_exposed_and_fires_before_any_write(s3):
    """Exposed separately so a binding can run it before composing its own key, which is what
    keeps a bad holder and a bad key raising in the binding's established order."""
    with pytest.raises(ValueError, match="holder is not a usable identity"):
        lock.assert_usable_holder("")

    with pytest.raises(ValueError, match="holder is not a usable identity"):
        _acquire(holder=None)

    assert s3.puts == []


def test_the_body_is_exactly_three_keys_under_the_callers_version(s3):
    """A fourth key would change what every existing lock object means."""
    lock.acquire(
        bucket=BUCKET,
        key=KEY,
        holder=HOLDER,
        stale_after_seconds=3600,
        wording=WORDING,
        fields=FIELDS,
        read=_read,
        version=7,
    )

    state = s3.state_of(KEY)
    assert set(state) == {"version", "holder", "acquiredAt"}
    assert state["version"] == 7


def test_the_callers_fields_reach_every_event(s3, captured_events):
    """The domain's identifying fields are a parameter, not a fixed pair: this plane keys by
    space where table-builder keys by database and table."""
    _seed(s3, holder=OTHER, acquired_at=_iso(4000))
    _acquire()

    stolen = captured_events.messages("stealing stale space lock")
    acquired = captured_events.messages("space lock acquired")

    assert stolen[0]["fields"]["space"] == "alice"
    assert acquired[0]["fields"]["space"] == "alice"
    assert acquired[0]["fields"]["stolen"] is True


def test_a_lost_compare_and_set_narrates_a_refusal_with_no_held_since(s3, captured_events):
    """The refusal has two call sites and they carry different evidence: a live holder reports
    when it was claimed, a lost race has nobody to name."""
    _seed(s3, holder=OTHER, acquired_at=_iso(4000))
    stale = s3.objects[KEY]
    _acquire(HOLDER, read=lambda key: (stale[0], stale[1]))
    _acquire(OTHER, read=lambda key: (stale[0], stale[1]))

    refusals = captured_events.messages("space lock refused")

    assert refusals[0]["fields"]["held_since"] is None


def test_the_lock_is_never_deleted(s3):
    """Releasing by OVERWRITE rather than DELETE is what makes "free" a state of the object.

    The grep moved here with the protocol. Left on ``tbcommon.table_lock`` it would have kept
    passing while asserting nothing — the module it reads no longer holds the code that could
    delete anything.
    """
    _, etag = _acquire()
    _release(etag)

    assert s3.deletes == []

    source = (pathlib.Path(__file__).parent / "cpcommon" / "lock.py").read_text()
    assert "delete_object" not in source


def test_the_bucket_parameter_is_the_one_written_to(s3):
    """The most important new parameter, and the one nothing else asserts.

    A regression writing to a hard-coded or wrong bucket leaves every other test in both suites
    green while the lock object lands somewhere nothing reads — no serialization at all, and
    silently, which is the worst shape a lock failure can take.
    """
    _, etag = _acquire()
    _release(etag)

    assert [put["Bucket"] for put in s3.puts] == [BUCKET, BUCKET]


def test_fields_may_not_shadow_the_protocols_own_event_names(s3):
    """Expanded alongside a branch-specific keyword, a colliding field raises ``TypeError`` on
    that branch alone — a steal-only or refusal-only crash on the rarest path. It fails up front
    instead, on every call, so a binding cannot ship with one."""
    for name in ("stolen", "held_since", "age_seconds"):
        with pytest.raises(ValueError, match="may not use the protocol's own names"):
            lock.acquire(
                bucket=BUCKET,
                key=KEY,
                holder=HOLDER,
                stale_after_seconds=3600,
                wording=WORDING,
                fields={name: "x"},
                read=_read,
            )

    assert s3.puts == []


def test_every_one_of_the_six_sentences_is_the_callers(s3, captured_events):
    """All six, because a binding that mis-wired one of the rarer three — the unreadable steal,
    the release, the failed release — would otherwise be caught only by another plane's suite."""
    s3.objects[KEY] = (b"not json at all", '"etag-0"')
    _, etag = _acquire()
    _release(etag)

    def _fail(**kwargs):
        raise _ClientError("ServiceUnavailable")

    _, etag2 = _acquire()
    s3.put_object = _fail
    _release(etag2)

    for message in (
        "stealing unreadable space lock",
        "space lock acquired",
        "space lock released",
        "space lock release failed",
    ):
        assert captured_events.messages(message), f"nothing narrated {message!r}"
