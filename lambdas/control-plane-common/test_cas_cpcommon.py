"""The one CAS loop, and the three behaviours its three former copies each depended on.

SPEC-156 FR-001. The copies had already drifted once — two handled the racing 409 and one did
not, and the caps were 6, 5 and 5 — so what is pinned here is not "a loop works" but the
specific properties each caller was relying on, in one place where a future edit has to see
all three at once.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import cas


class _Fault(Exception):
    """A client error carrying a code, shaped like botocore's."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


def _store(initial=None, etag="v0"):
    """A tiny conditional-write object: read returns (value, etag), write checks the tag."""
    state = {"value": initial, "etag": etag if initial is not None else None, "writes": 0}

    def read():
        return state["value"], state["etag"]

    def write(value, etag, *, conflicts=None):
        if conflicts and state["writes"] < conflicts:
            state["writes"] += 1
            raise _Fault("PreconditionFailed")
        if etag != state["etag"]:
            raise _Fault("PreconditionFailed")
        state["value"] = value
        state["etag"] = f"v{int((state['etag'] or 'v0')[1:]) + 1}"
        state["writes"] += 1

    return state, read, write


@pytest.mark.parametrize(
    "code", ["PreconditionFailed", "412", "ConditionalRequestConflict", "409"]
)
def test_all_four_precondition_codes_retry(code):
    """409 is the one a copy was missing. It is what S3 returns when two CREATE-ONLY writes
    race — the first run a space ever records, where the object does not exist yet and two
    writers are most likely to collide. Treating it as fatal drops that run."""
    assert cas.is_precondition(_Fault(code))


@pytest.mark.parametrize("code", ["AccessDenied", "NoSuchKey", "", "InternalError"])
def test_an_unrelated_fault_is_not_a_precondition(code):
    assert not cas.is_precondition(_Fault(code))


def test_the_transform_is_re_applied_to_the_freshly_read_value():
    """The whole point of the loop. Re-using a value read before a losing write would
    re-introduce the lost update the CAS exists to prevent."""
    state, read, write = _store([], etag="v0")
    seen = []

    def _apply(value):
        seen.append(list(value))
        return [*value, "mine"]

    def _racing_write(value, etag):
        if state["writes"] == 0:
            state["value"] = ["theirs"]
            state["etag"] = "v1"
            state["writes"] += 1
            raise _Fault("ConditionalRequestConflict")
        write(value, etag)

    result = cas.cas_mutate(read, _apply, _racing_write)
    assert result == ["theirs", "mine"], "the retry did not re-apply to the winner's value"
    assert seen == [[], ["theirs"]]


def test_exhaustion_raises_cas_exhausted_which_is_a_runtime_error():
    """Both halves matter: the distinct type lets log-sweep report exhaustion differently from
    a write fault, and the RuntimeError base keeps the shared-space callers that predate this
    module working unchanged."""
    _, read, _ = _store([])
    attempts = []

    def _always_conflicts(value, etag):
        attempts.append(1)
        raise _Fault("PreconditionFailed")

    with pytest.raises(cas.CasExhausted) as excinfo:
        cas.cas_mutate(read, lambda v: [*v, "x"], _always_conflicts, label="thing")
    assert isinstance(excinfo.value, RuntimeError)
    assert "thing" in str(excinfo.value)
    assert len(attempts) == cas.MAX_ATTEMPTS


def test_a_non_precondition_write_fault_re_raises_without_retrying():
    """A read error propagates rather than causing a silent overwrite; so does a write error
    that is not a lost race."""
    _, read, _ = _store([])
    attempts = []

    def _broken(value, etag):
        attempts.append(1)
        raise _Fault("AccessDenied")

    with pytest.raises(_Fault):
        cas.cas_mutate(read, lambda v: [*v, "x"], _broken)
    assert len(attempts) == 1


def test_on_conflict_reports_one_based_attempts():
    """The retry count is the signal — a write that succeeds on the fourth attempt is one that
    nearly did not — so log-sweep narrates each one."""
    _state, read, write = _store([], etag="v0")
    reported = []

    def _twice_then_ok(value, etag):
        write(value, etag, conflicts=2)

    cas.cas_mutate(read, lambda v: [*v, "x"], _twice_then_ok, on_conflict=reported.append)
    assert reported == [1, 2]


def test_skip_no_op_defaults_to_skipping_and_can_be_turned_off():
    """The shared-space contract skips; the two append callers pass False so a transform that
    happens to reproduce the current document still writes, exactly as their own loops did."""
    state, read, write = _store(["same"], etag="v0")

    cas.cas_mutate(read, lambda v: list(v), write)
    assert state["writes"] == 0

    cas.cas_mutate(read, lambda v: list(v), write, skip_no_op=False)
    assert state["writes"] == 1


def test_one_cap_for_every_caller():
    """FR-001's explicit resolution: 6, 5 and 5 became one value. Preserving three caps through
    a consolidation would have been a failed consolidation, so the number is asserted rather
    than left to whichever copy a reader happens to open."""
    import importlib
    import pathlib

    # shared-space-common and log-sweep are not on the suite's path (conftest.py adds the three
    # package layers only), so the two callers are imported by location rather than trusted to
    # a copy of their numbers written here — a hand-copied cap is the thing this FR deleted.
    lambdas = pathlib.Path(__file__).resolve().parent.parent
    for directory in ("shared-space-common", "log-sweep"):
        sys.path.insert(0, str(lambdas / directory))
    try:
        casio = importlib.import_module("casio")
        log_sweep = importlib.import_module("log_sweep")
    finally:
        for directory in ("shared-space-common", "log-sweep"):
            sys.path.remove(str(lambdas / directory))

    assert cas.MAX_ATTEMPTS == 6
    assert casio.MAX_CAS_ATTEMPTS == cas.MAX_ATTEMPTS
    assert log_sweep.MAX_CAS_ATTEMPTS == cas.MAX_ATTEMPTS


def test_no_second_copy_of_the_loop_survives():
    """The twin comment named SPEC-125 as the convergence point and the twin outlived it. A
    grep is the only thing that makes 'there is one loop' a property rather than a claim."""
    import pathlib

    lambdas = pathlib.Path(__file__).resolve().parent.parent
    offenders = [
        path
        for path in lambdas.rglob("*.py")
        if "__pycache__" not in str(path)
        and path != lambdas / "control-plane-common" / "cpcommon" / "cas.py"
        and "ConditionalRequestConflict" in path.read_text()
        and not path.name.startswith("test_")
    ]
    assert not offenders, f"a precondition predicate reappeared in {[p.name for p in offenders]}"
