"""Unit tests for the archive update-receipt Lambda (SPEC-171 FR-004, FR-006).

One function serves three stages of a restore, and each has a DIFFERENT failure contract — which
is the thing this file mostly exists to pin. Before the bill a failed write fails the run; after
the data has landed it must not; and the third stage always raises whatever the write did.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ARCHIVE_BUCKET", "archive-bkt")

import archive_update_receipt as m
import pytest
from arcommon import notify, receipt
from cpcommon import clients
from cpcommon.errors import TerminalError

_REQUEST_ID = "9f2c1b8e-1111-4222-8333-444444444444"
_ARCHIVE_ID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"
_ARCHIVE_ROOT = f"personal/alice/archive/{_ARCHIVE_ID}/"
_RECEIPT_KEY = f"alice/archive/{_ARCHIVE_ID}/receipt.txt"

#: The vault as a complete archive holds it: five archived objects and this plane's own record,
#: which ``is_archived_object`` excludes by its exact key at the root. The fixture's
#: ``objectCount`` is five, so a full count and the plan agree.
_VAULT_OBJECTS = [f"{_ARCHIVE_ROOT}reports/f{i}.csv" for i in range(5)] + [
    f"{_ARCHIVE_ROOT}_manifest.json"
]

_EXISTING = receipt.render(
    {
        "requestId": _ARCHIVE_ID,
        "startedAt": "2026-08-10T14:02:11.123Z",
        "source": {"bucket": "user-bkt", "root": "alice/"},
        "archive": {"bucket": "archive-bkt", "root": _ARCHIVE_ROOT},
        "objectCount": 1204,
        "totalBytes": 8_412_339_201,
    }
)


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
        return self._payload


class _FakeS3:
    """The receipt's reads and writes, plus a paginator over the VAULT prefix.

    The paginator is what the incomplete branch now depends on: it counts the archived objects
    under the prefix before it decides which failure to raise, because a sibling restore may
    already have swept them. ``vault`` therefore has to agree with the fixture's
    ``objectCount`` — a fake that listed a different population would let a test assert the
    right outcome for the wrong reason.
    """

    def __init__(
        self,
        existing=_EXISTING,
        get_error=None,
        put_error=None,
        vault=None,
        list_errors=(),
    ):
        self._existing = existing
        self._get_error = get_error
        self._put_error = put_error
        self._vault = _VAULT_OBJECTS if vault is None else list(vault)
        self._list_errors = list(list_errors)
        self.listed = []
        self.puts = []

    def get_paginator(self, name):
        fake = self

        class _P:
            def paginate(self, Bucket, Prefix):
                fake.listed.append({"Bucket": Bucket, "Prefix": Prefix})
                if fake._list_errors:
                    raise fake._list_errors.pop(0)
                yield {
                    "Contents": [
                        {"Key": key, "Size": 10}
                        for key in fake._vault
                        if key.startswith(Prefix)
                    ]
                }

        return _P()

    def get_object(self, Bucket, Key):
        if self._get_error:
            raise self._get_error
        if self._existing is None:
            raise _S3Error("NoSuchKey", 404)
        return {"Body": _Body(self._existing.encode())}

    def put_object(self, **kwargs):
        if self._put_error:
            raise self._put_error
        self.puts.append(kwargs)


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _request(status="restored", **overrides):
    base = {
        "requestId": _REQUEST_ID,
        "mode": "restore",
        "actor": {"username": "alice"},
        "source": {"bucket": "user-bkt", "root": "alice/", "kind": "personal", "name": "alice"},
        "archive": {
            "bucket": "archive-bkt",
            "root": _ARCHIVE_ROOT,
            "archiveId": _ARCHIVE_ID,
            "receiptBucket": "user-bkt",
            "receiptKey": _RECEIPT_KEY,
        },
        "totalBytes": 8_412_339_201,
        "objectCount": 5,
        "transferOutcome": {
            "copied": 1204,
            "failed": 0,
            "expected": 1204,
            "occupied": 0,
            "complete": True,
        },
        "restore": {"status": status, "requestedAt": "2026-08-12T09:30:00.000Z"},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _sink(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(m.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _written(fake):
    return fake.puts[0]["Body"].decode()


# ── the three stages ────────────────────────────────────────────────────────


def test_the_requested_stage_marks_the_receipt_before_anything_is_billed():
    """FR-006 AC4. The user is about to wait 3-5 hours and this is the only durable place that
    says a restore is in flight."""
    fake = _install()

    out = m.handler(_request(status="requested"), None)

    assert out["receiptKey"] == _RECEIPT_KEY
    assert fake.puts[0]["Key"] == _RECEIPT_KEY
    assert "Restore requested: 2026-08-12 09:30:00 UTC" in _written(fake).replace("   ", "")
    assert "Restored to:" in _written(fake)


def test_the_restored_stage_names_where_the_data_landed():
    """**The assertion has to be on the `Restored to` LINE, not on the document.** `render`
    already emits `Original path: s3://user-bkt/alice/`, and the rewrite keeps every other line
    verbatim — so "the destination appears somewhere in the text" is true however the restore
    line is filled in. Measured: forcing `restore_lines` to return a placeholder left the
    document-wide version of this test GREEN."""
    fake = _install()

    m.handler(_request(), None)

    line = next(
        ln for ln in _written(fake).splitlines() if ln.startswith(receipt.RESTORED_TO_LABEL)
    )
    assert line.split(":", 1)[1].strip() == "s3://user-bkt/alice/"


def test_the_incomplete_stage_ALWAYS_raises_after_recording_what_it_can():
    """FR-004, and it is the rollback verb's shape: record the outcome, then fail deliberately.
    The message names all three things a user needs — how many came back, that the archive is
    intact under the same id, and that re-requesting will report the files that did land.

    The verdict carries no ``shown`` block, which is what a collector from before the file
    counts writes, so the numbers are the object counts it always named."""
    fake = _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(
            _request(
                status="incomplete",
                transferOutcome={"copied": 40, "failed": 60, "expected": 100, "complete": False},
            ),
            None,
        )

    assert caught.value.reason == "restore_incomplete"
    assert caught.value.tokens == {"restored": "40", "total": "100"}
    assert "did not finish" in _written(fake)
    assert "40 of 100" in _written(fake)


# ── the rewrite itself ──────────────────────────────────────────────────────


def test_a_receipt_proven_absent_is_rendered_fresh_and_counts_files():
    """The fallback the rewrite exists to avoid, reached only when S3 proves the document is
    gone: every archive line is recomposed from the restore's own state. Five objects were
    archived and one is an empty folder's placeholder, so the fresh ``Files archived`` line says
    what the archived notification said — four — read off the restore manifest's block."""
    fake = _install(existing=None)

    m.handler(_request(transfer={"itemCount": 5, "fileCount": 4}), None)

    assert "Files archived:    4" in _written(fake).splitlines()


# ── the incomplete branch counts the vault before it says anything (SPEC-237) ────────────────
#
# Two restores of one archive can run at once and the first to finish sweeps the vault, so "the
# archive is still there" cannot be inferred from this run having deleted nothing. The branch
# counts, and says only what the count proves. The asymmetry is the whole design: a wrong
# "could not be confirmed" costs a user a conversation with an administrator, and a wrong "still
# complete" can cost them the only copy of their files.


def _incomplete(**overrides):
    outcome = {"copied": 3, "failed": 2, "expected": 5, "occupied": 0, "complete": False}
    outcome.update(overrides.pop("transferOutcome", {}))
    return _request(status="incomplete", transferOutcome=outcome, **overrides)


def test_a_full_count_earns_the_body_that_calls_the_archive_complete(_sink):
    """The five archived objects are four files and one empty folder's placeholder, and the
    placeholder is among the four that came back. The receipt line and the sentence both take
    the collector's ``shown`` counts, so both say 3 of 4 files where the objects say 4 of 5 —
    and the vault count still compares objects, because that is what the prefix holds."""
    fake = _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(
            _incomplete(
                transferOutcome={
                    "copied": 4,
                    "failed": 1,
                    "shown": {"copied": 3, "total": 4, "occupied": 0},
                }
            ),
            None,
        )

    assert caught.value.reason == "restore_incomplete"
    assert fake.listed[0]["Prefix"] == _ARCHIVE_ROOT
    assert "The archive was still complete when this restore stopped." in _written(fake)
    assert "Restore did not finish - 3 of 4 file(s) were written" in _written(fake)
    assert _sink[0][1].startswith(
        "Couldn't restore that: 3 of 4 file(s) were restored to your space before the restore "
        "stopped"
    )


def test_occupied_items_select_the_sibling_body_that_says_nothing_was_overwritten():
    """The two are the same asymmetry reached by different causes, and the user needs to be told
    which: "we could not copy your file" and "your own newer file was in the way, so we left it"
    call for different next actions."""
    fake = _install()

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(transferOutcome={"occupied": 2}), None)

    assert caught.value.reason == "restore_incomplete_occupied"
    assert caught.value.tokens == {"restored": "3", "total": "5", "occupied": "2"}
    assert "The archive was still complete when this restore stopped." in _written(fake)


def test_a_collector_verdict_with_no_occupied_field_stays_on_the_ordinary_body():
    """A verb pointed at the new image before the collector beside it would otherwise fail a run
    whose only remaining work is telling the user what happened. Read with a default, the skew is
    invisible."""
    _install()
    outcome = {"copied": 3, "failed": 2, "expected": 5, "complete": False}

    with pytest.raises(TerminalError) as caught:
        m.handler(_request(status="incomplete", transferOutcome=outcome), None)

    assert caught.value.reason == "restore_incomplete"


@pytest.mark.parametrize(
    ("vault", "label"),
    [
        ([f"{_ARCHIVE_ROOT}reports/f0.csv", f"{_ARCHIVE_ROOT}_manifest.json"], "short"),
        ([], "empty"),
        ([f"{_ARCHIVE_ROOT}_manifest.json"], "only-the-record"),
    ],
)
def test_a_count_that_does_not_add_up_selects_the_cleared_outcome(vault, label):
    """**The case a sibling restore produces, and the one that used to cost the only copy.** The
    other run swept the vault while this one was still copying; the old body told this user the
    archive was intact and invited them to clear the files that came back — which by then were
    the only copy. "Only the record" is the exact state a completed sweep leaves behind."""
    fake = _install(vault=vault)

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(), None)

    assert caught.value.reason == "restore_archive_cleared", label
    assert caught.value.tokens == {"restored": "3", "total": "5"}
    assert "could not be confirmed as complete" in _written(fake)


def test_an_occupied_run_whose_vault_is_gone_still_takes_the_cleared_outcome():
    """The count takes precedence over the occupied count, because it is the only one of the two
    that is about the user's remaining copy. Both of the other bodies say the archive was
    complete, and neither may be raised without the count that earns it."""
    _install(vault=[])

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(transferOutcome={"occupied": 2}), None)

    assert caught.value.reason == "restore_archive_cleared"


def test_a_listing_that_fails_deterministically_reports_the_archive_as_unconfirmed():
    """Fail closed: an unreadable vault is an unconfirmed one. A denial is not evidence the
    archive is there, and claiming it is costs more than claiming it is not."""
    _install(list_errors=[_S3Error("AccessDenied", 403)])

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(), None)

    assert caught.value.reason == "restore_archive_cleared"


def test_a_listing_throttled_on_every_attempt_reports_the_archive_as_unconfirmed():
    """Bounded well inside the verb's own 30-second timeout. A verb killed anyway surfaces as a
    sandbox timeout on the state's Catch, whose generic wording makes no claim about the archive
    at all."""
    fake = _install(list_errors=[_S3Error("SlowDown", 503)] * 3)

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(), None)

    assert caught.value.reason == "restore_archive_cleared"
    assert len(fake.listed) == 3


def test_a_throttle_followed_by_a_good_listing_still_earns_the_complete_body():
    """**THE CASE THAT PROVES THE RETRY IS REACHABLE AT ALL.** The two tests above assert the
    fail-closed direction, which a retry that never runs would also produce — so without this one
    the retry could be dead code and the suite would not notice. The listing raises a RAW client
    error rather than a classified one, which is why the verb classifies it itself."""
    fake = _install(list_errors=[_S3Error("SlowDown", 503)])

    with pytest.raises(TerminalError) as caught:
        m.handler(_incomplete(), None)

    assert caught.value.reason == "restore_incomplete"
    assert len(fake.listed) == 2, "the retry did not run"


@pytest.mark.parametrize(
    ("vault", "replacement"),
    [
        (_VAULT_OBJECTS, "The archive was still complete when this restore stopped."),
        ([], "The archive could not be confirmed as complete when this restore stopped."),
    ],
    ids=["counted-complete", "counted-short"],
)
def test_the_receipt_never_says_the_archive_is_intact_and_says_what_it_counted_instead(
    vault, replacement
):
    """The sentence this whole branch exists to remove, over both values of the flag that selects
    between its two replacements.

    **The absence is asserted WITH the positive, and that pairing is the point.** An assertion
    that a retired string is missing passes against whatever renders — including an empty
    document, a failed write, or a third sentence nobody intended. It stops meaning anything the
    moment the wording moves, and no reviewer can see that, because a reviewer reads what the
    assertion says rather than what still produces the string. Pinning the replacement is what
    keeps this checking the code rather than checking the past.
    """
    fake = _install(vault=vault)

    with pytest.raises(TerminalError):
        m.handler(_incomplete(), None)

    written = _written(fake)
    assert replacement in written
    assert "The archive is intact" not in written
    assert "archive is still intact" not in written
