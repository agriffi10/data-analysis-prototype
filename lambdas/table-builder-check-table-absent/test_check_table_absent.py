"""Unit tests for the table-builder check-table-absent Lambda (SPEC-068).

Glue is stubbed via ``clients.glue()``: a fake catalog client whose ``get_table``
either returns (table exists), raises ``EntityNotFoundException`` (absent → pass), or
raises a transient error (must propagate, NOT be terminalized). Runnable under pytest
OR directly: ``python3 test_check_table_absent.py``.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import check_table_absent as c  # noqa: E402
from tbcommon import clients  # noqa: E402
from tbcommon.errors import TerminalError  # noqa: E402


class _EntityNotFound(Exception):
    pass


class _Throttling(Exception):
    pass


class _FakeGlue:
    """Minimal Glue client double: `.exceptions.EntityNotFoundException` + get_table."""

    class exceptions:
        EntityNotFoundException = _EntityNotFound

    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def get_table(self, DatabaseName, Name):  # noqa: N803 - boto3 kwarg names
        self.calls.append((DatabaseName, Name))
        if self._behaviour == "found":
            return {"Table": {"Name": Name}}
        if self._behaviour == "absent":
            raise _EntityNotFound("not found")
        if self._behaviour == "transient":
            raise _Throttling("ThrottlingException")
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


def test_transient_glue_error_propagates_not_terminal():
    _install("transient")
    try:
        c.handler(_event(), None)
    except TerminalError:
        raise AssertionError("transient error must NOT be a TerminalError")
    except _Throttling:
        return  # raised for the SFN Retry
    raise AssertionError("expected the transient error to propagate")


def test_targets_the_declared_database_and_table():
    fake = _install("absent")
    c.handler(_event(table="orders", database="salesdata"), None)
    assert fake.calls == [("salesdata", "orders")]


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
