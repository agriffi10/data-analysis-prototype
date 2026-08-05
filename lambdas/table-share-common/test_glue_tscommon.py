"""SPEC-151 FR-008 — tscommon.glue classifies faults instead of assuming them.

This module had the OPPOSITE bias to the rest of the fleet: every fault that was not
``EntityNotFoundException`` or ``AccessDeniedException`` became a ``TransientError``, so a
deterministic error like ``InvalidInputException`` burned the whole Step Functions Retry
budget before failing — turning an instant refusal into a slow one and telling the user
nothing sooner than a fast failure would have.

Asserted PER CODE rather than by counting classifications, so a rule that stops applying
to one code cannot hide behind another still applying.
"""

import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "control-plane-common"))
sys.path.insert(0, _HERE)

import pytest
from cpcommon import clients
from cpcommon.errors import TerminalError, TransientError
from tscommon import glue as glue_mod

# Imported for its IMPORT SIDE EFFECT: it registers the table-share reason codes with
# cpcommon, and TerminalError refuses an unregistered reason. Without it these tests would
# fail on the registration guard rather than on the classification under test.
from tscommon import messages as _messages  # noqa: F401


class _Boom(Exception):
    """A botocore-shaped fault: `error_code` reads response["Error"]["Code"]."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _FakeGlue:
    def __init__(self, error):
        self._error = error
        self.exceptions = types.SimpleNamespace(EntityNotFoundException=_Boom)

    def get_table(self, DatabaseName, Name):
        raise self._error


def _install(code):
    clients._glue = _FakeGlue(_Boom(code))


#: Glue's routine transients — the state machine's Retry should absorb these.
TRANSIENT = ["InternalServiceException", "OperationTimeoutException", "ThrottlingException"]

#: Deterministic faults. Retrying these changes nothing; they must fail fast.
DETERMINISTIC = ["InvalidInputException", "ValidationException", "GlueEncryptionException"]


@pytest.mark.parametrize("code", TRANSIENT)
def test_get_table_treats_glues_routine_faults_as_transient(code):
    _install(code)
    with pytest.raises(TransientError):
        glue_mod.get_table("alice", "orders")


@pytest.mark.parametrize("code", DETERMINISTIC)
def test_get_table_does_not_call_a_deterministic_fault_transient(code):
    """The defect: `InvalidInputException` is not going to succeed on attempt four."""
    _install(code)
    with pytest.raises(TerminalError) as err:
        glue_mod.get_table("alice", "orders")
    assert err.value.reason == "source_not_readable"


@pytest.mark.parametrize("code", TRANSIENT)
def test_table_exists_treats_glues_routine_faults_as_transient(code):
    _install(code)
    with pytest.raises(TransientError):
        glue_mod.table_exists("bob", "orders_copy")


@pytest.mark.parametrize("code", DETERMINISTIC)
def test_table_exists_does_not_call_a_deterministic_fault_transient(code):
    _install(code)
    with pytest.raises(TerminalError) as err:
        glue_mod.table_exists("bob", "orders_copy")
    assert err.value.reason == "target_not_readable"


def test_the_two_named_terminals_are_unchanged():
    """AccessDenied stays terminal with its own reason, and an absent table is still
    `source_not_found` / False — neither may be swept into the new classification."""
    _install("AccessDeniedException")
    with pytest.raises(TerminalError) as err:
        glue_mod.get_table("alice", "orders")
    assert err.value.reason == "source_not_readable"

    _install("AccessDeniedException")
    with pytest.raises(TerminalError) as err:
        glue_mod.table_exists("bob", "orders_copy")
    assert err.value.reason == "target_not_readable"


def test_an_absent_table_is_still_not_found_rather_than_a_fault():
    _install("EntityNotFoundException")
    with pytest.raises(TerminalError) as err:
        glue_mod.get_table("alice", "orders")
    assert err.value.reason == "source_not_found"

    _install("EntityNotFoundException")
    assert glue_mod.table_exists("bob", "orders_copy") is False
