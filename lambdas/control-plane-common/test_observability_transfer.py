"""Guards for the child spans on the shared transfer engine, and for where a step may NOT go.

Three functions in ``cpcommon/transfer/`` carry ``observability.step``, and the reason there are
only three is the correction this spec exists for: five other shared functions look like the same
cheap win and are called once per RECIPIENT, per MEMBER or per TARGET, so stepping them is the
per-item instrumentation the design forbids. Both halves are held here — the three that are
instrumented, exactly, and the five that must never be.

Runnable under pytest. This file has no direct-run block: its guards need the
``captured_events`` and ``step_scan`` fixtures.
"""

import ast
import json
import os
import pathlib
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from cpcommon import clients, messages, observability
from cpcommon.errors import TerminalError, TransientError
from cpcommon.transfer import copy as copy_mod
from cpcommon.transfer import manifest as manifest_mod
from cpcommon.transfer import results as results_mod

_LAMBDAS = pathlib.Path(__file__).resolve().parent.parent
_TRANSFER = pathlib.Path(__file__).resolve().parent / "cpcommon" / "transfer"

#: The instrumented set, as a SORTED LIST rather than a set. Set equality would hide two
#: functions sharing one span name, and the span name is the field an operator filters on.
_INSTRUMENTED = [
    ("copy.py", "copy_batch", "copy-batch"),
    ("manifest.py", "write_manifest", "write-transfer-manifest"),
    ("results.py", "read_failed_items", "read-failed-items"),
]

#: The five shared functions that LOOK eligible and are not, each with the bound that disqualifies
#: it. Named rather than described, because the next author will reach for them too. Scanned at
#: their DEFINITION: shared-space calls the third through a re-export as ``casio.cas_mutate``, so a
#: guard matching the call spelling would miss it.
_MUST_NOT_STEP = [
    ("notify.py", "emit_notification"),
    ("registry.py", "load"),
    ("cas.py", "cas_mutate"),
    ("lock.py", "acquire"),
    ("lock.py", "release"),
]

#: The fixture's per-item delay, and the floor a child span's duration is held to. The floor is a
#: LITERAL and is deliberately not derived from the delay: a derived floor collapses to ``>= 0.0``
#: the moment the delay is mutated to zero, which passes while measuring nothing.
#: ``test_the_fixture_delay_and_the_duration_floor_stay_in_step`` is what keeps the pair honest.
_STEP_DELAY_SECONDS = 0.02
_DURATION_FLOOR_MS = 10.0

_FAILED = "copy_failed"
_UNREADABLE = "transfer_results_unreadable"
_ECHO = ("recipient",)

messages.register(
    {_FAILED: "copying the data failed.", _UNREADABLE: "the transfer results were unreadable."},
    prefix="Test: ",
)


class _SlowFakeS3:
    """An S3 client that serves the three transfer operations and takes measurable time.

    The delay is what lets a duration assertion mean anything: an instantaneous fake makes
    ``duration_ms >= floor`` a test of the clock's resolution rather than of the span.

    Attributes:
      objects: Keyed by ``(bucket, key)``, the payloads ``get_object`` serves.
      copies: One entry per ``copy_object`` call.
      puts: One entry per ``put_object`` call.
    """

    def __init__(self, objects=None):
        """Starts with the given objects and no recorded calls.

        Args:
          objects: Payloads to serve, keyed by ``(bucket, key)``.

        Returns:
          None.

        Raises:
          None.
        """
        self.objects = objects or {}
        self.copies = []
        self.puts = []

    def copy_object(self, **kwargs):
        """Records one copy, slowly.

        Args:
          **kwargs: The ``CopyObject`` arguments.

        Returns:
          None.

        Raises:
          None.
        """
        time.sleep(_STEP_DELAY_SECONDS)
        self.copies.append(kwargs)

    def put_object(self, **kwargs):
        """Records one put, slowly.

        Args:
          **kwargs: The ``PutObject`` arguments.

        Returns:
          None.

        Raises:
          None.
        """
        time.sleep(_STEP_DELAY_SECONDS)
        self.puts.append(kwargs)

    def get_object(self, Bucket, Key):
        """Serves one stored object, slowly.

        Args:
          Bucket: The bucket.
          Key: The key.

        Returns:
          A response whose ``Body`` reads the stored payload as JSON bytes.

        Raises:
          KeyError: When nothing is stored under that key.
        """
        time.sleep(_STEP_DELAY_SECONDS)
        payload = self.objects[(Bucket, Key)]

        class _Body:
            """A minimal streaming body over one payload."""

            def read(self):
                """Returns the payload's bytes.

                Args:
                  None.

                Returns:
                  The JSON-encoded payload.

                Raises:
                  None.
                """
                return json.dumps(payload).encode()

        return {"Body": _Body()}


def _item(index):
    """One manifest line for the copy engine.

    Args:
      index: Distinguishes the line's keys.

    Returns:
      A transfer item.

    Raises:
      None.
    """
    return {
        "recipient": "bob",
        "srcBucket": "user-bkt",
        "srcKey": f"alice/part-{index}.parquet",
        "destBucket": "user-bkt",
        "destKey": f"bob/part-{index}.parquet",
        "size": 10,
    }


def _export(count):
    """A Map Run export accounting for ``count`` items with no failures.

    ONE RESULT FILE PER ITEM rather than one file listing every item, and the shape is the point.
    ``read_failed_items`` loops over the manifest's result files, so an export whose file count is
    fixed makes the two-N test below unable to distinguish a span around the read from a span
    inside its loop — the loop would run once either way, and the guard would pass on the
    instrumentation it exists to forbid.

    Args:
      count: How many items the export accounts for, one per result file.

    Returns:
      The objects a ``_SlowFakeS3`` serves for one export read.

    Raises:
      None.
    """
    objects = {
        ("admin-bkt", "results/manifest.json"): {
            "MapRunArn": "arn:aws:states:us-east-1:1:mapRun/m/r",
            "ResultFiles": {
                "SUCCEEDED": [{"Key": f"results/SUCCEEDED_{i}.json"} for i in range(count)]
            },
        }
    }
    for i in range(count):
        objects[("admin-bkt", f"results/SUCCEEDED_{i}.json")] = [
            {
                "ExecutionArn": "arn:aws:states:us-east-1:1:execution:m:child",
                "Status": "SUCCEEDED",
                "Input": json.dumps({"Items": [_item(i)]}),
                "InputDetails": {"Included": True},
                "Output": json.dumps({"copied": 1, "failures": []}),
                "OutputDetails": {"Included": True},
            }
        ]
    return objects


def _drive(body, n=2):
    """Runs one traced invocation around a transfer operation, the way Lambda does.

    Args:
      body: Called with the item count; performs the instrumented operation.
      n: How many items the operation is given.

    Returns:
      None.

    Raises:
      Exception: Whatever ``body`` raised, unchanged.
    """

    @observability.traced("probe-verb")
    def handler(event, context=None):
        """Calls the operation under a root span.

        Args:
          event: The item count.
          context: Unused.

        Returns:
          None.

        Raises:
          Exception: Whatever the operation raised.
        """
        body(event)

    handler(n)


def _copy(n):
    """Copies ``n`` items through the batch copier.

    Args:
      n: How many items to copy.

    Returns:
      None.

    Raises:
      TransientError: On a retryable fault, which this fixture never produces.
    """
    clients._s3 = _SlowFakeS3()
    copy_mod.copy_batch([_item(i) for i in range(n)], _FAILED, echo_fields=_ECHO)


def _write(n):
    """Writes a manifest of ``n`` items.

    Args:
      n: How many items to write.

    Returns:
      None.

    Raises:
      None.
    """
    clients._s3 = _SlowFakeS3()
    manifest_mod.write_manifest("admin-bkt", "transfer/manifest.jsonl", [_item(i) for i in range(n)])


def _read(n):
    """Reads an export accounting for ``n`` items.

    Args:
      n: How many items the export accounts for.

    Returns:
      None.

    Raises:
      TerminalError: On an unreadable export, which this fixture never produces.
    """
    clients._s3 = _SlowFakeS3(_export(n))
    results_mod.read_failed_items(
        "admin-bkt",
        "results/manifest.json",
        batch_failure_reason=_FAILED,
        unreadable_reason=_UNREADABLE,
        echo_fields=_ECHO,
    )


_OPERATIONS = {"copy-batch": _copy, "write-transfer-manifest": _write, "read-failed-items": _read}


def _stepped_functions(path, scan):
    """Every function in one module carrying a step, with the span it names.

    Delegates to the shared scanner in ``conftest`` rather than matching the rendered decorator
    text. The text matcher was blind to ``from .observability import step``, which is exactly how
    a step could be added to one of the five forbidden functions with every guard here green.

    Args:
      path: The module file to scan.
      scan: The shared scanner, from the ``step_scan`` fixture.

    Returns:
      A list of ``(function name, span name)`` pairs.

    Raises:
      None.
    """
    return scan(ast.parse(path.read_text()))


def _scanned_modules():
    """The transfer modules the count guards are asserted over.

    Globbed rather than listed so a module added beside ``copy.py`` is scanned the day it is
    written. ``test_the_module_glob_collected`` is the control that the glob is not empty.

    Args:
      None.

    Returns:
      The module paths, sorted.

    Raises:
      None.
    """
    return sorted(_TRANSFER.glob("*.py"))


def test_the_module_glob_collected():
    """A positive control for the population the two count guards are written over.

    Every assertion below is over what this glob returns; an empty glob satisfies all of them.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    names = {path.name for path in _scanned_modules()}
    assert {"copy.py", "manifest.py", "results.py"} <= names, (
        f"the transfer glob collected {sorted(names)}, which is missing an instrumented module"
    )


def test_exactly_these_transfer_functions_carry_a_step(step_scan):
    """The instrumented set, held as a sorted list so a shared span name cannot hide in a set.

    An EXTRA step fails this too, which is the half that matters: the reason only three of the
    shared layer's functions are instrumented is that the rest are called per item, and the
    cheapest way for that correction to be undone is a fourth decorator nobody counted.

    The count is over functions carrying ``observability.step``, not over decorated functions in
    general: ``lock.LockWording`` carries ``@dataclass`` and ``notify.notifies_on_failure``
    carries a nested ``@functools.wraps``, so a literal "decorated functions here" reading is
    unsatisfiable.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    found = sorted(
        (path.name, name, span)
        for path in _scanned_modules()
        for name, span in _stepped_functions(path, step_scan)
    )
    assert found == sorted(_INSTRUMENTED), (
        f"the transfer modules carry {found}, not {sorted(_INSTRUMENTED)} — a step added or "
        "removed here changes what every plane that transfers reports"
    )


def test_no_scanned_transfer_module_imports_log_foundry():
    """The count above is only a fence while ``observability`` is the one door.

    Without this, a span added through ``lf.trace`` directly is invisible to the count AND
    bypasses the field rule at the same time, so the guard would read as load-bearing while
    admitting exactly the thing it exists to refuse.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    offenders = [
        path.name for path in _scanned_modules() if "log_foundry" in path.read_text()
    ]
    assert not offenders, (
        f"{offenders} reach log-foundry directly; every span in this layer goes through "
        "cpcommon.observability so that one module owns the field rule"
    )


def test_the_five_looping_functions_carry_no_step(step_scan):
    """The prohibition an earlier draft of this design got wrong, held by name.

    Each of these is invoked once per recipient, per member or per target by at least one caller,
    so a step on any of them is per-item instrumentation wearing a shared function's clothes.
    They are scanned at their DEFINITION rather than at their call sites: shared-space reaches
    ``cas_mutate`` through a re-export spelled ``casio.cas_mutate``.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    root = pathlib.Path(__file__).resolve().parent / "cpcommon"
    offenders = []
    seen = []
    for module, function in _MUST_NOT_STEP:
        source = (root / module).read_text()
        defined = [
            node.name
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function
        ]
        seen.extend(f"{module}:{name}" for name in defined)
        if any(name == function for name, _ in _stepped_functions(root / module, step_scan)):
            offenders.append(f"{module}:{function}")

    assert len(seen) == len(_MUST_NOT_STEP), (
        f"the scan resolved {seen} of {[f'{m}:{f}' for m, f in _MUST_NOT_STEP]} — an absence "
        "assertion over functions that are no longer there passes without checking anything"
    )
    assert not offenders, (
        f"{offenders} carry a step, and each is called inside a loop by at least one caller — "
        "emit_notification per recipient, registry.load per recipient, cas_mutate per member, "
        "lock.acquire and lock.release per target"
    )


def test_no_instrumented_transfer_function_is_a_generator(step_scan):
    """On this pin ``@trace`` refuses a generator AT DECORATION, which is a cold start that fails.

    WHAT THIS CAN AND CANNOT CATCH, because the difference decides whether it is worth having.
    For the three modules this file imports at the top, a decorated generator raises before
    collection and the import failure gets there first — so here the assertion is behind a
    louder guard rather than in front of it. Where it genuinely fires is a NEW module beside
    ``copy.py``: the glob reaches it, this file does not import it, and the fleet-wide guard in
    ``test_observability_cpcommon.py`` would name it only as one path among a hundred. Verified
    by planting exactly that.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    generators = []
    for path in _scanned_modules():
        tree = ast.parse(path.read_text())
        scan_result = step_scan(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in {n for n, _ in scan_result}:
                continue
            nested = {
                id(inner)
                for child in ast.walk(node)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                and child is not node
                for inner in ast.walk(child)
            }
            if any(
                isinstance(c, (ast.Yield, ast.YieldFrom)) and id(c) not in nested
                for c in ast.walk(node)
            ):
                generators.append(f"{path.name}:{node.name}")
    assert not generators, f"these would fail at import on this pin: {generators}"


@pytest.mark.parametrize("span", sorted(_OPERATIONS))
def test_an_instrumented_operation_emits_one_child_span_of_the_handlers_trace(
    span, captured_events
):
    """The span exists, is parented to the verb's root, and covers the work.

    All three halves are asserted together because each is satisfiable without the others: a
    span with a null parent is what a step inside a worker pool emits, and a span whose duration
    is zero is what tracing a generator's CALL used to produce.

    Args:
      span: The span name under test.
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _drive(_OPERATIONS[span])

    root = captured_events.spans("probe-verb")
    assert len(root) == 1, f"expected one root span, got {len(root)}"
    children = captured_events.child_spans("probe-verb", name=span)
    assert len(children) == 1, (
        f"expected exactly one {span!r} child of probe-verb, got {len(children)}"
    )
    assert children[0]["parent_span_id"] == root[0]["span_id"]

    ended = [
        e
        for e in captured_events.events
        if e["message"] == "span.end" and e["function"] == span
    ]
    assert ended and ended[0]["duration_ms"] >= _DURATION_FLOOR_MS, (
        f"{span} reported {ended[0]['duration_ms'] if ended else 'no'} ms against a "
        f"{_DURATION_FLOOR_MS} ms floor — a span that closes before its work has run reports a "
        "duration like this"
    )


def test_the_fixture_delay_and_the_duration_floor_stay_in_step():
    """Keeps the literal floor honest without deriving it from the delay.

    Deriving the floor would make it collapse with the delay; leaving them unrelated would let
    the delay drop below the floor and turn every duration assertion into a flake. So they stay
    separate values with one assertion between them.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert _STEP_DELAY_SECONDS * 1000 >= _DURATION_FLOOR_MS, (
        f"the fixture sleeps {_STEP_DELAY_SECONDS * 1000} ms against a {_DURATION_FLOOR_MS} ms "
        "floor, so the duration assertions would fail for the fixture's reason, not the span's"
    )


class _Exploding:
    """An S3 client whose every operation raises one chosen botocore fault.

    Attributes:
      response: The botocore error envelope ``errors.error_code`` reads, so a test can choose
        whether the fault classifies as transient or deterministic.
    """

    def __init__(self, code):
        """Refuses every call with one error code.

        Args:
          code: The botocore error code to raise under.

        Returns:
          None.

        Raises:
          None.
        """
        self._code = code

    def _boom(self):
        """Raises the configured fault.

        Args:
          None.

        Returns:
          Never returns.

        Raises:
          _S3Error: Always.
        """
        raise _S3Error(self._code)

    def copy_object(self, **kwargs):
        """Refuses.

        Args:
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          _S3Error: Always.
        """
        self._boom()

    def put_object(self, **kwargs):
        """Refuses.

        Args:
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          _S3Error: Always.
        """
        self._boom()

    def get_object(self, **kwargs):
        """Refuses.

        Args:
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          _S3Error: Always.
        """
        self._boom()


class _S3Error(Exception):
    """A botocore-shaped fault carrying an error code.

    Attributes:
      response: The envelope ``cpcommon.errors.error_code`` reads the code out of.
    """

    def __init__(self, code):
        """Carries one error code.

        Args:
          code: The botocore error code.

        Returns:
          None.

        Raises:
          None.
        """
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


#: What each instrumented operation raises when its S3 call fails, and under which fault. The
#: three DIFFER, and the difference is the design rather than an accident: the batch copier
#: isolates deterministic per-item faults deliberately and only a TRANSIENT one escapes it, the
#: manifest writer lets a deterministic fault propagate raw, and the results reader converts an
#: unreadable export into its caller's registered terminal reason. A single expected type across
#: all three would have to be wrong for two of them.
_FAILURES = {
    "copy-batch": ("Throttling", TransientError),
    "write-transfer-manifest": ("AccessDenied", _S3Error),
    "read-failed-items": ("AccessDenied", TerminalError),
}


def _reach(span):
    """Calls one instrumented operation against whatever client is installed.

    Split out from the fixture helpers so the failure-path test can install a refusing client
    without one of them replacing it on the way in.

    Args:
      span: The span name whose operation to call.

    Returns:
      None.

    Raises:
      Exception: Whatever the operation raised.
    """
    if span == "copy-batch":
        copy_mod.copy_batch([_item(0)], _FAILED, echo_fields=_ECHO)
    elif span == "write-transfer-manifest":
        manifest_mod.write_manifest("admin-bkt", "transfer/manifest.jsonl", [_item(0)])
    else:
        results_mod.read_failed_items(
            "admin-bkt",
            "results/manifest.json",
            batch_failure_reason=_FAILED,
            unreadable_reason=_UNREADABLE,
            echo_fields=_ECHO,
        )


@pytest.mark.parametrize("span", sorted(_FAILURES))
def test_a_failure_inside_an_instrumented_operation_propagates_and_marks_its_span(
    span, captured_events
):
    """Both halves, because the propagation half alone passes on an UNDECORATED function.

    ``step`` is a thin alias for the library's decorator precisely so that it records the
    failure and re-raises unchanged. A step that swallowed would convert a terminal failure into
    a silent wrong answer, underneath the notifier that should have told the user.

    Args:
      span: The span name under test.
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    code, expected = _FAILURES[span]

    def explode(_n):
        """Reaches the instrumented operation with a client that refuses.

        Args:
          _n: Unused.

        Returns:
          Never returns.

        Raises:
          Exception: Whatever the operation raises.
        """
        clients._s3 = _Exploding(code)
        _reach(span)

    with pytest.raises(expected):
        _drive(explode)

    ended = [
        e
        for e in captured_events.events
        if e["message"] == "span.end" and e["function"] == span
    ]
    assert ended, f"no {span} span was closed on the failure path"
    assert ended[0]["status"] == "error", (
        f"{span} closed with status {ended[0]['status']!r} on an invocation that raised"
    )
    assert ended[0].get("error", {}).get("type") == expected.__name__, (
        f"{span}'s span recorded {ended[0].get('error', {}).get('type')!r}, so the exception "
        f"that reached the caller is not the one the span saw"
    )


def _span_starts(sink):
    """How many spans have been opened so far, ROOT SPANS INCLUDED.

    Counting only children is what makes a step inside a worker pool invisible: those spans
    carry a null parent, so a child-only count reports zero for the exact mistake it is meant
    to detect.

    Args:
      sink: The capturing sink.

    Returns:
      The number of ``span.start`` events collected.

    Raises:
      None.
    """
    return len([e for e in sink.events if e["message"] == "span.start"])


@pytest.mark.parametrize("span", sorted(_OPERATIONS))
def test_the_span_count_does_not_move_with_the_item_count(span, captured_events):
    """The property that separates a bounded step from per-item instrumentation.

    Driven at two values of N rather than reasoned about, and counting EVERY span rather than
    the children of the root. A step planted inside ``copy_batch``'s worker pool emits one span
    per item with ``parent_span_id`` null and its own trace id — so it is invisible to a guard
    that counts children, and shows up here as N extra roots.

    TWO of the three parametrisations have a reachable plant and one does not, which is said here
    rather than left to be assumed. ``copy-batch`` has its worker pool and ``read-failed-items``
    loops over one result file per item, so a step in either place reddens this — both verified by
    planting. ``write-transfer-manifest`` has no per-item function at all: its lines are built by one
    ``join``, so there is nowhere for a per-item step to go and this case asserts a property that
    cannot currently be violated.

    Args:
      span: The span name under test.
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _drive(_OPERATIONS[span], n=2)
    at_two = _span_starts(captured_events)
    _drive(_OPERATIONS[span], n=20)
    at_twenty = _span_starts(captured_events) - at_two

    assert at_two == at_twenty, (
        f"{span} emitted {at_two} spans for 2 items and {at_twenty} for 20, so the instrumentation "
        "scales with the work rather than with the invocation"
    )


#: The three entry points a calling verb reaches. Matched on the trailing name, because every
#: caller reaches them through a module alias of its own choosing.
_ENTRYPOINTS = {"copy_batch", "write_manifest", "read_failed_items"}



def test_no_caller_reaches_a_transfer_operation_from_inside_a_loop():
    """The bound stated in each docstring, enumerated over the whole population rather than read.

    The driven test above proves N-independence for the engine itself. This is the other half:
    the engine being called once says nothing about a CALLER that calls it per recipient, which
    is exactly the mistake that had to be corrected in five other shared functions. So every call
    site in the fleet is enumerated and checked for a loop above it.

    The control is that EACH of the three entry points was found, not that the total cleared a
    floor. A floor pinned at the measured population reddens when a legitimate caller is deleted,
    and — worse — a total stays comfortably above it while one entry point stops matching
    entirely, which is the failure that would make this guard silently stop covering a third of
    its subject.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    loops = (
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
    )
    sites, offenders, found_names = 0, [], set()
    for path in sorted(_LAMBDAS.rglob("*.py")):
        if "__pycache__" in str(path) or path.name.startswith("test_"):
            continue
        if path.parent == _TRANSFER:
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        _ENTRYPOINT_ALIASES = {name: name for name in _ENTRYPOINTS}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _ENTRYPOINTS:
                        _ENTRYPOINT_ALIASES[alias.asname or alias.name] = alias.name
        inside = {
            id(inner)
            for node in ast.walk(tree)
            if isinstance(node, loops)
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _ENTRYPOINT_ALIASES.get(ast.unparse(node.func).split(".")[-1])
            if name is None:
                continue
            sites += 1
            found_names.add(name)
            if id(node) in inside:
                offenders.append(f"{path.relative_to(_LAMBDAS)}:{node.lineno}")

    missing = _ENTRYPOINTS - found_names
    assert not missing, (
        f"the scan found no call site for {sorted(missing)} anywhere in the fleet ({sites} sites "
        "for the rest). An absence assertion over a population that stopped collecting passes "
        "without checking anything — and a count floor would not catch this, because the other "
        "two entry points keep it satisfied."
    )
    assert not offenders, (
        f"{offenders} call a stepped transfer operation from inside a loop, which makes its "
        "child span per item rather than per invocation"
    )
