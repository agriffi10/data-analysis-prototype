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


@pytest.mark.parametrize(
    ("code", "failed", "conflict"),
    [
        ("PreconditionFailed", True, False),
        ("412", True, False),
        ("ConditionalRequestConflict", False, True),
        ("409", False, True),
        ("AccessDenied", False, False),
        ("", False, False),
    ],
)
def test_the_two_halves_answer_their_own_code_and_not_the_other_one(code, failed, conflict):
    """The collapse is right for a compare-and-set and wrong for a caller whose two answers
    differ. A conditional copy has to tell them apart: a precondition failure is a fact about
    the OBJECT and is settled by comparing it, while a conflict is a fact about the RACE, where
    nothing is yet known to be at the key — so comparing would be comparing against whatever the
    other writer had happened to finish.

    Asserted in BOTH directions per code, because a half that answered True to everything would
    satisfy a one-sided check and would make the union useless."""
    assert cas.is_precondition_failed(_Fault(code)) is failed
    assert cas.is_conditional_conflict(_Fault(code)) is conflict


@pytest.mark.parametrize(
    "code",
    ["PreconditionFailed", "412", "ConditionalRequestConflict", "409", "AccessDenied", "NoSuchKey", "", "InternalError"],
)
def test_the_union_still_answers_exactly_what_it_answered_before_it_was_split(code):
    """Every input the tests above give it, asserted against the halves rather than against a
    second copy of the code list — a list written twice is a list that is eventually wrong in one
    copy, and here the wrong copy would be a retry that stopped happening."""
    fault = _Fault(code)
    assert cas.is_precondition(fault) == (
        cas.is_precondition_failed(fault) or cas.is_conditional_conflict(fault)
    )


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
    import ast
    import pathlib

    lambdas = pathlib.Path(__file__).resolve().parent.parent

    def _bound_to_cas(path, name):
        """True iff ``name`` is assigned an attribute of the shared module, not a literal.

        Read from SOURCE rather than imported. Importing ``log_sweep`` to read one integer runs
        its module scope, which calls ``observability.init`` and installs a root-logger filter
        for the rest of the session — a side effect this file has no business causing, and one
        the conftest's shared-layer snapshot does not cover. Reading the binding also asserts
        the stronger property: not "these numbers agree today" but "there is one number".
        """
        bindings = [
            node.value
            for node in ast.walk(ast.parse((lambdas / path).read_text()))
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
        ]
        # EVERY binding, not the first: a second module-level assignment shadows the first at
        # runtime, so stopping at the first match would read a value the module does not use.
        return bool(bindings) and all(
            (isinstance(value, ast.Attribute) and value.attr == "MAX_ATTEMPTS")
            or (isinstance(value, ast.Name) and value.id == "MAX_ATTEMPTS")
            for value in bindings
        )

    assert cas.MAX_ATTEMPTS == 6
    assert _bound_to_cas("shared-space-common/casio.py", "MAX_CAS_ATTEMPTS")
    assert _bound_to_cas("log-sweep/log_sweep.py", "MAX_CAS_ATTEMPTS")


def test_the_precondition_predicate_has_not_reappeared():
    """Named for what it checks, which is NARROWER than "there is one loop".

    It greps for the S3 response codes, so it catches a re-grown ``_is_precondition`` — the
    concrete drift FR-001 found, where two copies knew the racing 409 and one did not. It does
    NOT catch a second read-modify-write loop written against ``casio.error_code`` or against
    ``cas.is_precondition``: a hand-rolled loop calling the shared predicate passes, and one
    such loop legitimately exists (``registry._resolve_reserve_collision``, which returns three
    outcomes rather than a committed value and so is not a ``cas_mutate``). Detecting loop
    SHAPE would flag that one too, so the guard is scoped to the part that can silently differ.
    """
    import pathlib

    lambdas = pathlib.Path(__file__).resolve().parent.parent
    owner = lambdas / "control-plane-common" / "cpcommon" / "cas.py"
    offenders = sorted(
        str(path.relative_to(lambdas))
        for path in lambdas.rglob("*.py")
        if "__pycache__" not in str(path)
        and path != owner
        and not path.name.startswith("test_")
        # shared-space-common/fakes.py RAISES these codes to drive the loop under test rather
        # than classifying them, and never ships (the layer's copy list excludes it). Exempted
        # by full path: a function directory's own fakes.py WOULD ship, so the bare name is too
        # wide a hole to leave.
        and path != lambdas / "shared-space-common" / "fakes.py"
        # file-ops' conditional DELETE classifier names these codes to tell them APART, which is
        # the opposite of what this predicate does. cas.is_precondition deliberately collapses 409
        # and 412 because a compare-and-set retries on either. A conditional delete must not: a 412
        # means the object changed, which is terminal for that item because its destination copy now
        # holds stale bytes, while a 409 means a concurrent delete or put won the race and is
        # retryable. Binding that module to the shared predicate would give one answer to two
        # questions. Exempted by FULL PATH, and the assertion below keeps the exemption honest.
        and path != lambdas / "file-ops-common" / "focommon" / "delete.py"
        # The multipart complete route names PreconditionFailed for the same reason delete.py
        # does — to tell one outcome APART, not to collapse two for a retry. Its `If-None-Match:
        # *` asks S3 to decide occupancy at the instant the object is written, and a 412 is that
        # question's ANSWER: the destination was taken while the upload ran, which is terminal
        # and is reported to the user as a Conflict. There is no read-modify-write and nothing
        # retries. Exempted by FULL PATH, and the assertion below keeps it honest.
        and path != lambdas / "api" / "routes" / "objects_upload.py"
        # The converter's upload names the same two codes for the same reason as the two above:
        # `If-None-Match: *` asks S3 to decide, at the instant of the write, whether the
        # destination name was taken since the browser last looked, and a 412 is that question's
        # ANSWER. It reaches the user as `destination_occupied` and nothing retries — the
        # machine's Retry for that Task is TransientError alone, precisely so a re-invocation
        # cannot meet its own write. Exempted by FULL PATH, and kept honest below.
        and path != lambdas / "results-conversion-convert" / "rc_convert.py"
        # The data-quality request-id claim names both codes to tell them APART, as delete.py
        # does. Its `If-None-Match: *` create is refused 412 when another execution already
        # holds the id, which it answers by reading the holder back, and 409 when a concurrent
        # request interrupted the write, which S3 says to retry. Collapsing the two would read
        # a claim holder that is not there. Exempted by FULL PATH, and kept honest below.
        and path != lambdas / "data-quality-common" / "dqcommon" / "run_claim.py"
        and any(
            code in path.read_text()
            for code in ("ConditionalRequestConflict", "PreconditionFailed")
        )
    )
    assert not offenders, f"a precondition predicate reappeared in {offenders}"

    # The exemption above is only safe while that module is not a compare-and-set. If it ever grows
    # a read-modify-write loop it must use the shared one, and this is what says so.
    # The same honesty check for the multipart route: it may name the code, but the moment it
    # grows a compare-and-set it must bind to the shared predicate like everything else.
    multipart = (lambdas / "api" / "routes" / "objects_upload.py").read_text()
    assert "PreconditionFailed" in multipart, (
        "the objects_upload exemption has outlived its subject — remove it"
    )
    assert "cas" not in multipart.replace("case", ""), (
        "objects_upload has started doing compare-and-set; it must bind to cpcommon.cas"
    )

    converter = (lambdas / "results-conversion-convert" / "rc_convert.py").read_text()
    assert "PreconditionFailed" in converter, (
        "the results-conversion exemption has outlived its subject — remove it"
    )
    # Checked on `IfMatch` and the import rather than on the substring "cas", which the two
    # exemptions above can use because neither of their modules says "cast". A compare-and-set
    # is an ETag precondition, and `If-None-Match: *` is not one: it asks whether the object
    # exists, not whether it is the version we read.
    assert "IfMatch" not in converter, (
        "the converter has started conditioning on an ETag, which is a compare-and-set; it "
        "must bind to cpcommon.cas rather than roll its own"
    )
    assert "import cas" not in converter and "cas." not in converter, (
        "the converter now touches the shared CAS; re-argue its exemption from the sweep above"
    )

    claim = (lambdas / "data-quality-common" / "dqcommon" / "run_claim.py").read_text()
    assert "PreconditionFailed" in claim, (
        "the run_claim exemption has outlived its subject — remove it"
    )
    assert "IfMatch" not in claim and "cas." not in claim and "import cas" not in claim, (
        "run_claim has started conditioning on an ETag or touching the shared CAS; it must bind to "
        "cpcommon.cas, and its exemption from the sweep above has to be re-argued"
    )

    conditional_delete = (lambdas / "file-ops-common" / "focommon" / "delete.py").read_text()
    assert "cas" not in conditional_delete.split('"""')[2], (
        "focommon.delete has started doing compare-and-set; it must bind to cpcommon.cas, and its "
        "exemption from the sweep above has to be re-argued"
    )
