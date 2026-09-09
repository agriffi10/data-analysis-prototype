"""Unit tests for the table-builder check-table-absent Lambda.

Glue is stubbed via clients.glue(): a fake catalog client whose get_table either
returns (table exists), raises EntityNotFoundException (absent → pass), or raises a
transient error (must propagate, not be terminalized).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import check_table_absent as c
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError


class _EntityNotFound(Exception):
    pass


class _FakeClientError(Exception):
    """A botocore-SHAPED error: carries ``.response["Error"]["Code"]`` so the verb's
    ``raise_if_transient`` classifier can actually read the code. The old ``_Throttling``
    double had the code in its message only (no ``.response``), so the transient mapping
    never fired and the transient test passed regardless of the fix."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}


class _FakeGlue:
    """Minimal Glue client double: `.exceptions.EntityNotFoundException` + get_table."""

    class exceptions:
        EntityNotFoundException = _EntityNotFound

    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def get_table(self, DatabaseName, Name):  # boto3 kwarg names
        self.calls.append((DatabaseName, Name))
        if self._behaviour == "found":
            return {"Table": {"Name": Name}}
        if self._behaviour == "absent":
            raise _EntityNotFound("not found")
        if self._behaviour == "transient":
            raise _FakeClientError("ThrottlingException")
        if self._behaviour == "denied":
            raise _FakeClientError("AccessDenied")
        raise AssertionError(self._behaviour)


def _install(behaviour):
    fake = _FakeGlue(behaviour)
    clients._glue = fake
    return fake


def _event(table="sales_2026", database="alice"):
    return {"space": {"database": database}, "tableName": table, "requestId": "r1"}


def test_absent_table_passes_through_unchanged():
    _install("absent")
    out = c.handler(_event(), None)
    assert out == _event()  # untouched


def test_existing_table_is_terminal_table_exists():
    _install("found")
    try:
        c.handler(_event(), None)
    except TerminalError as exc:
        assert exc.reason == "table_exists"
        assert "sales_2026" in str(exc) and "alice" in str(exc)
        return
    raise AssertionError("expected TerminalError(table_exists)")


def test_transient_glue_throttle_is_raised_as_TransientError():
    """A Glue throttle must reach the SFN as TransientError — the name CheckTableAbsent's
    Retry list now recognizes. A bare ClientError matches nothing there and would
    permanently fail the build."""
    _install("transient")
    try:
        c.handler(_event(), None)
    except TransientError:
        return
    except TerminalError:
        raise AssertionError("a throttle must not be terminalized")
    raise AssertionError("expected TransientError from a throttled get_table")
