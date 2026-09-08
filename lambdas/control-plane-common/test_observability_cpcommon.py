"""Guards for `cpcommon.observability`'s contract with log-foundry.

The module had no suite of its own, and neither the `echo` drop nor the per-invocation context
reset was tested at all. Each guard here is written so that removing the thing it guards makes it
fail; where that is not achievable the test says so rather than asserting something weaker.
"""

import ast
import json
import pathlib

import log_foundry as lf
import pytest
from cpcommon import observability

_LAMBDAS = pathlib.Path(__file__).resolve().parent.parent


class _Sink:
    """A sink that keeps every event, so a test can assert on what was emitted.

    Attributes:
      events: Every event handed to `emit`, in delivery order.
    """

    def __init__(self):
        """Starts with no events.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.events = []

    def emit(self, batch):
        """Keeps one batch.

        Args:
          batch: The events log-foundry is delivering.

        Returns:
          None.

        Raises:
          None.
        """
        self.events.extend(batch)

    def close(self):
        """Releases nothing.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """

    def fields_of(self, message):
        """The fields of every event carrying one message.

        Args:
          message: The literal message to match.

        Returns:
          A list of field mappings, one per matching event.

        Raises:
          None.
        """
        return [e.get("fields") or {} for e in self.events if e.get("message") == message]


class _BrokenSink(_Sink):
    """A sink whose `emit` always raises, for the never-fail-the-verb guards."""

    def emit(self, batch):
        """Refuses every batch.

        Args:
          batch: Ignored.

        Returns:
          Never returns.

        Raises:
          RuntimeError: Always.
        """
        raise RuntimeError("sink is down")


@pytest.fixture
def sink():
    """Points log-foundry at a capturing sink for one test.

    Args:
      None.

    Yields:
      The capturing sink.

    Raises:
      None.
    """
    collector = _Sink()
    lf.configure(service="test", version="0", env="test", sink=collector)
    yield collector
    lf.configure(service="test", version="0", env="test", sink=_Sink())


def _run(event):
    """Drives one traced invocation the way Lambda does.

    Args:
      event: The handler's event.

    Returns:
      None.

    Raises:
      None.
    """

    @observability.traced("probe-verb")
    def handler(evt, context=None):
        """Emits one narrative event.

        Args:
          evt: The event.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        observability.info("did a thing")

    handler(event)


def test_a_warm_container_does_not_leak_the_previous_request_id(sink):
    """The reset is what stops a fabricated correlation key, and only this shape proves it.

    The id must arrive ON THE EVENT: `traced` binds it outside the span, which is the only
    binding the reset is responsible for. A test that stamps from inside the handler body passes
    even with the reset removed, because the library pops span-scoped baggage on its own.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _run({"requestId": "REQ-1"})
    _run({})
    observability.flush()

    second = sink.fields_of("did a thing")[1]
    assert "request_id" not in second, (
        f"the second invocation inherited {second.get('request_id')!r} from the first"
    )


def test_the_reset_clears_an_adopted_trace_context(sink):
    """SPEC-225 places its adoption after the reset on the strength of this behaviour.

    Asserted here rather than assumed there: the private variable the reset used to set cleared
    baggage only, so an adopted context would have survived into the next invocation.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    inbound = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    lf.continue_trace(inbound)
    observability._reset_context()
    _run({})
    observability.flush()

    span = next(e for e in sink.events if e["message"] == "span.start")
    assert span["trace_id"] != "4bf92f3577b34da6a3ce929d0e0e4736"
    assert span.get("parent_span_id") is None


def test_a_field_named_fields_is_dropped_and_its_siblings_still_land(sink):
    """`fields` is the library's escape hatch, so an un-dropped one is silently reinterpreted.

    Both halves are asserted. A guard that dropped everything would satisfy the first alone.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    observability.info("narrative", fields={"a": 1}, sibling="kept")
    observability.flush()

    landed = sink.fields_of("narrative")[0]
    assert landed.get("sibling") == "kept"
    assert "a" not in landed, "the reserved name was forwarded and unpacked over the event"


def test_a_field_named_echo_is_dropped_before_it_can_raise(sink):
    """The other prohibited name, dropped for a different reason.

    Left in, `echo` collides with the keyword `_emit` always passes and raises `TypeError` at the
    call boundary — inside business logic. This is the failure the `try` in `_emit` exists for,
    now that the library absorbs a raising sink on both paths.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    observability.info("narrative", echo=True, sibling="kept")
    observability.flush()

    landed = sink.fields_of("narrative")[0]
    assert landed.get("sibling") == "kept"
    assert "echo" not in landed


def test_a_broken_sink_never_reaches_the_verb():
    """Logging must not be the reason a verb fails, on the orphan path or in a span.

    The library absorbs a sink failure itself now, so this asserts the invariant end to end
    rather than this module's guard specifically — the `echo` test above is what covers the
    failure `_emit` still catches.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    lf.configure(service="test", version="0", env="test", sink=_BrokenSink())
    try:
        observability.info("orphan against a broken sink")
        _run({"requestId": "REQ-2"})
    finally:
        lf.configure(service="test", version="0", env="test", sink=_Sink())


def _decorated_functions():
    """Every function in `lambdas/` carrying `@observability.traced` or `@observability.step`.

    Args:
      None.

    Returns:
      A list of `(path, function name, is a generator)` triples.

    Raises:
      None.
    """
    found = []
    for path in sorted(_LAMBDAS.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any(
                d.startswith(("observability.traced", "observability.step")) for d in decorators
            ):
                continue
            nested = {
                id(inner)
                for child in ast.walk(node)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
                and child is not node
                for inner in ast.walk(child)
            }
            generator = any(
                isinstance(c, (ast.Yield, ast.YieldFrom)) and id(c) not in nested
                for c in ast.walk(node)
            )
            found.append((path, node.name, generator))
    return found


def test_no_traced_or_stepped_function_is_a_generator():
    """On this pin, `@trace` on a generator is a TypeError AT DECORATION — a cold start that fails.

    The library refuses it because tracing a generator traced the CALL, not the iteration: the
    span opened and closed before the body ran, reporting success in microseconds for work that
    had not happened. That is a better failure than the silent one, but it is a whole plane
    failing to start, so the fleet is held to it here.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    decorated = _decorated_functions()
    assert len(decorated) > 100, (
        f"the walk found only {len(decorated)} decorated functions, so it is not scanning the "
        "fleet and an empty result would pass this guard vacuously"
    )
    generators = [f"{p.parent.name}/{p.name}:{n}" for p, n, gen in decorated if gen]
    assert not generators, f"these would fail at import on this pin: {generators}"


def test_no_module_reaches_into_log_foundrys_privates():
    """The reach that broke silently once, kept closed in both spellings it can wear.

    `getattr(module, "_worker", None)` is a string literal rather than an attribute access, so an
    Attribute-only walk misses it — which is how the retirement this spec deleted went on reading
    as load-bearing after the name behind it was gone.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    allowed = {"observability.py", "conftest.py", "test_log_sweep.py"}
    offenders = []
    for path in sorted(_LAMBDAS.rglob("*.py")):
        if "__pycache__" in str(path) or path.name in allowed:
            continue
        source = path.read_text()
        if "log_foundry" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            rendered = ast.unparse(node)
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and ("log_foundry" in rendered or "lf_" in rendered)
            ):
                offenders.append(f"{path.name}:{node.lineno} {rendered}")
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "getattr":
                literals = [
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
                if any(name.startswith("_") for name in literals):
                    offenders.append(f"{path.name}:{node.lineno} {ast.unparse(node)}")
    assert not offenders, f"private log-foundry reaches outside the sanctioned files: {offenders}"


def test_the_stack_capture_claim_is_re_derived_rather_than_re_dated():
    """Three register entries rest on there being no way to turn stack capture off.

    Asserted against the INSTALLED library so the claim maintains itself: a release that adds an
    opt-out reddens this instead of silently outliving the decision. It reddens on any new
    `Config` field too, which is intended — the point is that somebody looks.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(lf.Config)}
    assert fields == {
        "service",
        "version",
        "env",
        "sink",
        "defaults",
        "max_value_bytes",
        "max_stack_bytes",
        "max_keys",
        "max_depth",
    }, f"Config's fields changed: {sorted(fields)} — re-read the stack-capture decision"

    with pytest.raises(ValueError):
        lf.configure(max_stack_bytes=0)


def test_a_sink_swap_redirects_delivery_and_the_teardown_reports_what_it_delivers(sink):
    """The control for the harness change, asserting both halves of a swap and the teardown.

    The first half alone would pass for a swap that delivered nothing anywhere. The teardown half
    is what the deleted `_config` restore failed: on this pin the library keeps a live sink beside
    the stored config, so restoring the config left `get_config()` naming one sink while events
    went to another.

    Args:
      sink: The capturing sink, standing in as the first sink.

    Returns:
      None.

    Raises:
      None.
    """
    _run({"requestId": "A"})
    observability.flush()
    assert sink.events, "the first sink collected nothing, so the swap below proves nothing"
    before = len(sink.events)

    second = _Sink()
    lf.configure(service="test", version="0", env="test", sink=second)
    _run({"requestId": "B"})
    observability.flush()

    assert len(sink.events) == before, "the retired sink kept receiving after the swap"
    assert second.events, "the new sink received nothing"
    assert lf.get_config().sink is second, (
        "the library reports one sink while delivering to another"
    )


def test_the_shared_fixtures_teardown_leaves_reporting_and_delivery_agreeing():
    """The guard on the `_config` restore this spec deleted, driven rather than reasoned about.

    A test cannot observe the teardown of a fixture it requests — its own finalizer runs first —
    and importing the root `conftest` by name does not resolve to it under this repo's flattened
    layout. So the fixture's generator is driven by hand: setup, yield, teardown, then ask the
    library where it delivers and where it says it delivers.

    The deleted restore failed exactly here. On this pin a live sink sits beside the stored
    config, so assigning the old config back left `get_config()` naming one sink while events
    went to another — reported health that could not be backed up, in the fixture every plane's
    tests depend on.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "root_conftest_probe", _LAMBDAS / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    before_the_fixture = _Sink()
    lf.configure(service="test", version="0", env="test", sink=before_the_fixture)

    generator = module.captured_events.__wrapped__()
    next(generator)
    for _ in generator:
        break

    observability.info("after the teardown")
    observability.flush()

    reported = lf.get_config().sink
    received = [s for s in (before_the_fixture,) if s.events]
    assert reported is not None, "the library reports no sink at all after the teardown"
    assert not received, (
        "the teardown left delivery pointed at the sink configured BEFORE the fixture ran"
    )
    assert getattr(reported, "events", None) is not None and any(
        e.get("message") == "after the teardown" for e in reported.events
    ), "the library reports a sink that did not receive the event it delivered"


def test_the_capturing_fixture_collects_through_the_shared_harness(captured_events):
    """A positive control over `conftest.captured_events` itself.

    Every plane's absence assertions are written over this fixture, and an empty collector
    satisfies all of them. It is asserted here so a harness that quietly stopped collecting
    fails one named test rather than making a hundred others meaningless.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _run({"requestId": "REQ-3"})
    observability.flush()

    assert captured_events.events, "the shared fixture collected nothing"
    assert captured_events.levels(), "boundaries only — no narrative was captured"
    assert captured_events.spans("probe-verb"), "no span named probe-verb"


def test_every_event_carries_the_build_stamp_and_the_verb(sink):
    """The two fields a record is useless without, asserted where they are cheapest to lose.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _run({"requestId": "REQ-4"})
    observability.flush()

    start = next(e for e in sink.events if e["message"] == "span.start")
    assert start["function"] == "probe-verb"
    assert (start.get("fields") or {}).get("verb") == "probe-verb"
    assert (start.get("fields") or {}).get("request_id") == "REQ-4"
    assert json.dumps(start), "the event does not serialize, so the sweep could not write it"
