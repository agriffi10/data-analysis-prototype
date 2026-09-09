"""The destination guard: any collision refuses everything, and an ambiguous answer is one.

Two of these tests are about a direction rather than a value. A guard that reads an unreadable
key as "clear" ends in an overwrite of data this plane holds no right to destroy, and a guard
that issues 200,000 heads to report a conflict in the first hundred times out before it can
report anything at all. Both are asserted by counting what the guard actually did.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from arcommon import guard
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


class _S3Error(Exception):
    def __init__(self, code, status):
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class _FakeS3:
    """Answers HeadObject from a set of occupied keys, counting every call it is asked for."""

    def __init__(self, occupied=(), errors=None):
        self.occupied = set(occupied)
        self.errors = errors or {}
        self.heads = []

    def head_object(self, Bucket, Key):
        self.heads.append(Key)
        if Key in self.errors:
            raise self.errors[Key]
        if Key in self.occupied:
            return {"ContentLength": 1}
        raise _S3Error("404", 404)


def _install(**kwargs):
    fake = _FakeS3(**kwargs)
    clients._s3 = fake
    return fake


def _keys(n, prefix="alice/"):
    return [f"{prefix}f{i}.csv" for i in range(n)]


# ── Clear, and occupied ──────────────────────────────────────────────────────


def test_a_clear_destination_set_passes_and_heads_every_key():
    fake = _install()

    guard.assert_clear("user-bkt", _keys(20), "alice/")

    assert len(fake.heads) == 20


def test_any_single_occupied_key_refuses_the_whole_restore():
    """There is no skip, no overwrite, no merge and no "restore what fits" — S3 has no move and
    no rename, so a restore is a copy and a copy destroys what is under it."""
    _install(occupied={"alice/f7.csv"})

    with pytest.raises(TerminalError) as caught:
        guard.assert_clear("user-bkt", _keys(20), "alice/")

    assert caught.value.reason == "destination_occupied"


def test_an_error_with_no_status_at_all_counts_as_occupied():
    """Fail-closed is the direction, not a list of statuses to enumerate."""
    _install(errors={"alice/f0.csv": RuntimeError("no response metadata")})

    with pytest.raises(TerminalError):
        guard.assert_clear("user-bkt", _keys(1), "alice/")


def test_a_throttle_stays_transient_and_never_falls_through_to_clear():
    """A guard that cannot SEE the destination must retry and then fail its own state. Falling
    through to "nothing is there" is the answer that ends in an overwrite."""
    _install(errors={"alice/f0.csv": _S3Error("SlowDown", 503)})

    with pytest.raises(TransientError):
        guard.assert_clear("user-bkt", _keys(1), "alice/")


# ── The short-circuit, and what the refusal is allowed to claim ──────────────


def test_no_raw_service_text_reaches_the_sample():
    """SPEC-106: the token is the channel that reaches the user, so what rides on it is the
    user's own paths and nothing an AWS client said."""
    _install(errors={"alice/f0.csv": _S3Error("AccessDenied", 403)})

    with pytest.raises(TerminalError) as caught:
        guard.assert_clear("user-bkt", _keys(1), "alice/")

    assert "AccessDenied" not in caught.value.tokens["sample"]
