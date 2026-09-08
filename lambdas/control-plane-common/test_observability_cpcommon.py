"""Guards for `cpcommon.observability`'s contract with log-foundry.

The module had no suite of its own, and neither the `echo` drop nor the per-invocation context
reset was tested at all. Each guard here is written so that removing the thing it guards makes it
fail; where that is not achievable the test says so rather than asserting something weaker.
"""

import ast
import json
import logging
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


# ── SPEC-225 FR-001: the four shapes a verb receives, and the one it must never read ────────

#: The inbound trace every adoption test joins. Its flags are `-00` — UNSAMPLED — on purpose:
#: the library's accessor discards version and flags, so an implementation that rebuilt the
#: string from `(trace_id, parent_span_id)` would hand back `-01` and every byte-for-byte
#: assertion below would fail. The value is a W3C specification example.
_INBOUND = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00"
_INBOUND_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
_INBOUND_PARENT = "00f067aa0ba902b7"

#: One entry per shape `_shape_values` walks, as the event a verb actually receives.
#: `test_the_shape_table_covers_every_shape_the_extractor_walks` is what stops a fifth shape
#: being added to the module without one here — otherwise this table is a list of the shapes
#: someone remembered, and the parametrisation below proves nothing about the rest.
_SHAPES = {
    "state payload": lambda value: {"requestId": "REQ", "traceparent": value},
    "pipe envelope": lambda value: [
        {"body": json.dumps({"requestId": "REQ", "traceparent": value})}
    ],
    "distributed-map batch": lambda value: {
        "BatchInput": {"requestId": "REQ", "traceparent": value},
        "Items": [{"relKey": "a.csv"}],
    },
    "inline-map child": lambda value: {
        "recipient": {"kind": "user", "name": "bob"},
        "request": {"requestId": "REQ", "traceparent": value},
    },
}


def _span_start(sink):
    """The one `span.start` event a single traced invocation emitted.

    Args:
      sink: The capturing sink.

    Returns:
      The event.

    Raises:
      StopIteration: If the invocation opened no span, which is itself the bug.
    """
    return next(e for e in sink.events if e["message"] == "span.start")


@pytest.mark.parametrize("shape", sorted(_SHAPES), ids=sorted(_SHAPES))
def test_a_traced_handler_joins_the_inbound_trace_on_every_shape(sink, shape):
    """One run is one trace only if every entry point a verb has adopts the run's context.

    Two of these four could not carry a request id at all before this change, so a test that
    only covered the state payload and the pipe envelope would have passed on the day nine verbs
    were unjoinable.

    Args:
      sink: The capturing sink.
      shape: The shape name, keying `_SHAPES`.

    Returns:
      None.

    Raises:
      None.
    """
    _run(_SHAPES[shape](_INBOUND))
    observability.flush()

    span = _span_start(sink)
    assert span["trace_id"] == _INBOUND_TRACE, f"{shape} did not join the inbound trace"
    assert span["parent_span_id"] == _INBOUND_PARENT, f"{shape} lost the inbound parent"


def test_the_shape_table_covers_every_shape_the_extractor_walks():
    """The table above is a claim about the module, so it is checked against the module.

    `_shape_values` reads one shape per `yield` plus one per name in the nested-block tuple, so
    a fifth shape cannot be added without moving one of those two counts. Without this, the
    parametrisation is a list of the shapes whoever wrote it remembered.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    source = pathlib.Path(observability.__file__).read_text(encoding="utf-8")
    fn = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "_shape_values"
    )
    yields = [n for n in ast.walk(fn) if isinstance(n, ast.Yield)]
    nested = [
        c.value
        for loop in ast.walk(fn)
        if isinstance(loop, ast.For) and isinstance(loop.iter, ast.Tuple)
        for c in loop.iter.elts
        if isinstance(c, ast.Constant)
    ]

    assert yields, "the extractor yields nothing, so the walk collapsed"
    assert nested == ["BatchInput", "request"], (
        f"the nested blocks the extractor reads are {nested}, which the shape table does not "
        "describe"
    )
    # One yield sits inside the nested loop and stands for len(nested) shapes, not one.
    assert len(yields) - 1 + len(nested) == len(_SHAPES), (
        f"the extractor walks {len(yields) - 1 + len(nested)} shapes and the table names "
        f"{len(_SHAPES)}"
    )


def test_an_api_gateway_body_can_set_neither_the_trace_nor_the_request_id(sink):
    """The one shape the extractor must never read, and the reason the body branch is a list.

    For an API Gateway payload-2.0 request, `body` IS the caller's own HTTP body. Both halves are
    asserted because they fail for different reasons: the request id was reachable and merely
    overwritten later by the gateway's value, so it was a latent hazard; nothing overwrites an
    adopted trace, so widening the same walk without narrowing it would have made the second one
    live. The request-id half fails against the extractor as it stood before this change.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    poisoned = {
        "version": "2.0",
        "routeKey": "POST /v1/enqueue/archive",
        "rawPath": "/v1/enqueue/archive",
        "requestContext": {"requestId": "GATEWAY-ID", "http": {"method": "POST"}},
        "body": json.dumps({"requestId": "CALLER-CHOSEN", "traceparent": _INBOUND}),
        "isBase64Encoded": False,
    }

    _run(poisoned)
    observability.flush()

    span = _span_start(sink)
    assert span["trace_id"] != _INBOUND_TRACE, (
        "a caller put this service's API span into a trace of their choosing"
    )
    assert span.get("parent_span_id") is None
    assert observability._extract_request_id(poisoned) is None, (
        "a caller named this service's correlation key from their own HTTP body"
    )


def test_the_inline_map_shape_yields_the_request_id_it_used_to_lose():
    """The three inline-Map children were the run's only unjoinable success-path verbs.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    child = {"recipient": {}, "request": {"requestId": "REQ-1"}}
    assert observability._extract_request_id(child) == "REQ-1"


def test_no_traceparent_mints_a_fresh_trace_and_says_nothing_about_it(sink, caplog):
    """Absence is the ordinary case and must not write a line per invocation.

    The API is the root of every run and carries no inbound traceparent by definition, and the
    producer writes the field unconditionally, so `None` arrives on a real path too. A warning
    here would be one CloudWatch line per HTTP request.

    Args:
      sink: The capturing sink.
      caplog: pytest's log capture.

    Returns:
      None.

    Raises:
      None.
    """
    with caplog.at_level(logging.WARNING, logger="cpcommon.observability"):
        _run({"requestId": "REQ"})
        _run({"requestId": "REQ", "traceparent": None})
        observability.flush()

    assert _span_start(sink)["trace_id"] != _INBOUND_TRACE
    assert caplog.records == [], (
        f"absence warned: {[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.parametrize(
    "malformed",
    ["not-a-traceparent", "00-zzzz-00f067aa0ba902b7-01", 12345],
    ids=["wrong-shape", "non-hex-trace-id", "not-a-string"],
)
def test_a_malformed_traceparent_mints_a_fresh_trace_and_does_warn(sink, caplog, malformed):
    """Malformed is a producer bug, so it is worth exactly one line; absent is not.

    The non-string case is why `_extract_traceparent` hands its value on unvalidated: dropping it
    at the extractor would make a producer sending the wrong type indistinguishable from one
    sending nothing. It is refused BEFORE `continue_trace` rather than by it — the library's
    parser happens to tolerate any type, but its signature says `str | None`, and a guard resting
    on undeclared tolerance is one release away from an exception inside a logging helper.

    Args:
      sink: The capturing sink.
      caplog: pytest's log capture.
      malformed: The unusable inbound value.

    Returns:
      None.

    Raises:
      None.
    """
    with caplog.at_level(logging.WARNING, logger="cpcommon.observability"):
        _run({"requestId": "REQ", "traceparent": malformed})
        observability.flush()

    assert _span_start(sink)["trace_id"] != _INBOUND_TRACE
    assert any("traceparent" in r.getMessage() for r in caplog.records), (
        f"{malformed!r} was dropped silently: {[r.getMessage() for r in caplog.records]}"
    )


def test_a_warm_container_does_not_inherit_the_previous_runs_trace(sink):
    """The stickiness this spec was sequenced behind, asserted end to end rather than assumed.

    On the pinned library an adoption is one-shot AND the reset clears it; both halves are
    needed, and this fails if either goes. The module's own record is asserted beside the span
    because they are two states that must agree — a span minting a fresh id while
    `run_traceparent` still hands out the finished run's value is the same leak, one level up.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    _run({"requestId": "REQ", "traceparent": _INBOUND})
    _run({"requestId": "REQ"})
    observability.flush()

    second = [e for e in sink.events if e["message"] == "span.start"][1]
    assert second["trace_id"] != _INBOUND_TRACE, "the warm container joined the finished run"
    assert second.get("parent_span_id") is None
    assert observability._ADOPTED.get() is None


def test_run_traceparent_returns_the_adopted_value_byte_for_byte():
    """A rebuild from the library's accessor loses the version and the sampling flags.

    `get_adopted_context()` hands back `(trace_id, parent_span_id)` and nothing else, so an
    implementation that reassembled a string would answer `-01` for this inbound `-00` — a
    sampling decision silently reversed on the way through every verb in the run.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    captured = {}

    @observability.traced("probe-verb")
    def handler(evt, context=None):
        """Captures what the verb would hand onward.

        Args:
          evt: The event.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        captured["value"] = observability.run_traceparent()

    handler({"traceparent": _INBOUND})

    assert captured["value"] == _INBOUND


def test_run_traceparent_falls_back_to_the_open_span_where_nothing_was_adopted():
    """The API is the root of the run, so its own span IS the run's traceparent.

    Without the fallback the producer would stamp `None` on every message and no run would have
    a trace to join.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    captured = {}

    @observability.traced("request")
    def handler(evt, context=None):
        """Captures the root's own traceparent.

        Args:
          evt: The event.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        captured["value"] = observability.run_traceparent()

    handler({})

    assert captured["value"] and captured["value"].startswith("00-")
    assert _INBOUND_TRACE not in captured["value"]


def test_a_field_named_fields_is_dropped_and_its_siblings_still_land(sink, caplog):
    """`fields` is the library's escape hatch, so an un-dropped one is silently reinterpreted.

    Both halves are asserted. A guard that dropped everything would satisfy the first alone.

    Args:
      sink: The capturing sink.

    Returns:
      None.

    Raises:
      None.
    """
    with caplog.at_level("WARNING"):
        observability.info("narrative", fields={"a": 1}, sibling="kept")
    observability.flush()

    landed = sink.fields_of("narrative")[0]
    assert landed.get("sibling") == "kept"
    assert "a" not in landed, "the reserved name was forwarded and unpacked over the event"
    assert any("narrative" in r.getMessage() and "fields" in r.getMessage() for r in caplog.records), (
        "no warning named the message — the warning is the ONLY signal an author gets that their "
        "field vanished, so a silent drop is barely better than the silent reinterpretation"
    )


def test_a_field_named_echo_is_dropped_before_it_can_raise(sink, caplog):
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
    with caplog.at_level("WARNING"):
        observability.info("narrative", echo=True, sibling="kept")
    observability.flush()

    landed = sink.fields_of("narrative")[0]
    assert landed.get("sibling") == "kept"
    assert "echo" not in landed
    assert any("narrative" in r.getMessage() and "echo" in r.getMessage() for r in caplog.records), (
        "no warning named the message"
    )


def test_an_emitter_that_raises_does_not_reach_the_verb(sink, monkeypatch):
    """`_emit`'s guard, covered directly rather than through a raising sink.

    A raising SINK proves nothing about this module: the library absorbs that on both paths
    before `_emit` is entered, so such a test passes with the guard deleted. What the guard is
    for is a failure raised by the library call itself — a reserved-name collision today, and
    whatever the next release makes raise. That is forced here by making the call raise.

    Args:
      sink: The capturing sink.
      monkeypatch: Used to make the library's level function raise.

    Returns:
      None.

    Raises:
      None.
    """

    def explode(message, **kwargs):
        """Stands in for a library call that raises.

        Args:
          message: Ignored.
          **kwargs: Ignored.

        Returns:
          Never returns.

        Raises:
          TypeError: Always.
        """
        raise TypeError("got multiple values for keyword argument 'echo'")

    monkeypatch.setattr(lf, "info", explode)
    observability.info("narrative", sibling="kept")

    monkeypatch.undo()
    observability.info("after the failure", sibling="kept")
    observability.flush()

    assert sink.fields_of("narrative") == [], "the exploding call somehow emitted"
    assert sink.fields_of("after the failure"), "the verb did not survive to emit again"


def test_adding_a_name_to_prohibited_fields_is_sufficient_to_prohibit_it(sink, monkeypatch):
    """`PROHIBITED_FIELDS` drives the drop, rather than reading as though it does.

    Written because the first version of this change defined the constant and hard-coded both
    names beside it: emptying it changed nothing and extending it dropped nothing, which is the
    same "reads load-bearing, is not" defect this spec exists to delete.

    Args:
      sink: The capturing sink.
      monkeypatch: Used to add a third prohibited name.

    Returns:
      None.

    Raises:
      None.
    """
    monkeypatch.setitem(observability.PROHIBITED_FIELDS, "secret", "a planted reason")
    observability.info("narrative", secret="leaked", sibling="kept")
    observability.flush()

    landed = sink.fields_of("narrative")[0]
    assert landed.get("sibling") == "kept"
    assert "secret" not in landed, "the constant does not drive the drop"


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


def _log_foundry_aliases(tree):
    """Every local name in one module that is bound to log-foundry or one of its submodules.

    The alias matters because the name a reach wears is the author's choice: this repo writes
    `import log_foundry as lf`, so `lf._lifecycle` renders with neither `log_foundry` nor a
    recognisable prefix in it. Matching on the rendered text misses exactly the spelling the
    repo actually uses.

    Args:
      tree: The parsed module.

    Returns:
      A set of local names bound to log-foundry.

    Raises:
      None.
    """
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "log_foundry":
                    aliases.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == (
            "log_foundry"
        ):
            for alias in node.names:
                aliases.add(alias.asname or alias.name)
    return aliases


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
    allowed = {
        "control-plane-common/cpcommon/observability.py",
        "conftest.py",
        "log-sweep/test_log_sweep.py",
    }
    offenders = []
    parsed = 0
    for path in sorted(_LAMBDAS.rglob("*.py")):
        relative = str(path.relative_to(_LAMBDAS))
        if "__pycache__" in str(path) or relative in allowed:
            continue
        source = path.read_text()
        parsed += 1
        if "log_foundry" not in source:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        bound = _log_foundry_aliases(tree)
        for node in ast.walk(tree):
            rendered = ast.unparse(node)
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                root = rendered.split(".", 1)[0]
                if root in bound:
                    offenders.append(f"{relative}:{node.lineno} {rendered}")
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "getattr":
                literals = [
                    a.value
                    for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)
                ]
                if any(name.startswith("_") for name in literals):
                    offenders.append(f"{relative}:{node.lineno} {ast.unparse(node)}")
    assert parsed > 300, (
        f"the walk read only {parsed} modules, so it is not reaching the tree — the population of "
        "files mentioning log_foundry is tiny BY DESIGN, so counting those proves nothing and this "
        "counts what the walk actually traversed"
    )
    assert _log_foundry_aliases(ast.parse("import log_foundry as lf\n")) == {"lf"}, (
        "the alias resolver does not resolve the aliased spelling, which is the one this repo "
        "uses and the one an offender would wear"
    )
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

    _run({"requestId": "AFTER-TEARDOWN"})
    observability.flush()

    reported = lf.get_config().sink
    received = [s for s in (before_the_fixture,) if s.events]
    assert reported is not None, "the library reports no sink at all after the teardown"
    assert not received, (
        "the teardown left SPAN-path delivery pointed at the sink configured before the fixture "
        "ran — the orphan path agrees with the report even when this is broken, so it is the "
        "span path that has to be probed"
    )
    assert getattr(reported, "events", None) is not None and any(
        e.get("message") == "span.end" for e in reported.events
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


def test_a_read_of_the_shared_sink_drains_so_an_absence_means_nothing_was_emitted(
    captured_events,
):
    """The property every absence assertion written over `captured_events` rests on.

    An event emitted with no span open is delivered synchronously; one emitted INSIDE a span is
    buffered until the worker flushes. So a helper that narrates and then gains a step stops
    delivering before the assertion that reads it, and an undrained read answers "nothing has
    been flushed yet" — green for exactly the same assertions as "nothing was emitted", with no
    way to tell the two apart.

    THE TWO HALVES ARE ONE TEST DELIBERATELY, and the spec's own acceptance criterion asks for
    something that cannot exist. It says to mutation-test the drain "against a test that asserts
    an absence"; removing a drain can only make an absence assertion MORE likely to pass, so no
    absence alone can detect it. The presence half is the half that dies when the drain is
    removed, and it is what makes the absence half mean anything.

    Args:
      captured_events: The shared capturing sink.

    Returns:
      None.

    Raises:
      None.
    """

    @observability.step("probe-step")
    def narrating_step():
        """Narrates from inside a span, so its event is buffered rather than delivered.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        observability.info("emitted inside a span")

    narrating_step()

    assert captured_events.messages("emitted inside a span"), (
        "the read did not drain the worker, so every absence assertion over this sink means "
        "'nothing has been flushed yet' rather than 'nothing was emitted'"
    )
    assert captured_events.messages("never emitted at all") == []


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


def test_the_pins_comment_still_states_every_fact_it_is_the_sole_home_of():
    """The requirements block is the only live home of seven facts, held by a test rather than care.

    The count went wrong four times in one spec — three, then five, then six, then seven — which is
    the signature of a missing mechanism rather than four oversights. Prose said the check was
    "derived"; nothing read the file. This does.

    Each fact is anchored to an identifier rather than to wording, so rewriting a sentence is free
    and deleting the fact is not. A rewrite that drops one fails here instead of silently erasing
    it from the repo — which is what would have happened to the orphan-path emit fact, whose only
    other statement was a docstring the same change rewrote.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    block = (_LAMBDAS / "control-plane-common" / "requirements.txt").read_text()
    facts = {
        "the error.stack clip": "32 KB",
        "error.message / error.module": "error.module",
        "safe by construction": "size-bounded",
        "span.end carries duration and outcome": "duration_ms",
        "the synchronous orphan emit": "SYNCHRONOUSLY",
        "the MultiSink disposition": "MultiSink",
        "the non-JSON sink disposition": "clickhouse",
    }
    missing = sorted(name for name, anchor in facts.items() if anchor not in block)
    assert not missing, (
        f"the pin's comment no longer states: {missing}. Each is stated in no other live file, so "
        "a rewrite that drops one deletes it from the repo."
    )


def _span_names(scan):
    """Every `observability.traced` and `observability.step` name in the fleet, with its site.

    Args:
      scan: The shared span-decorator scanner, which resolves the name a decorator is bound to
        rather than matching its rendered text — the difference a planted
        `from .observability import step` exposed.

    Returns:
      A `(traced, stepped)` pair of `{name: [site, …]}` mappings.

    Raises:
      None.
    """
    traced, stepped = {}, {}
    for path in sorted(_LAMBDAS.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for attribute, target in (("traced", traced), ("step", stepped)):
            for _function, name in scan(tree, attribute):
                if name is None:
                    continue
                target.setdefault(name, []).append(str(path.relative_to(_LAMBDAS)))
    return traced, stepped


#: The one collision that predates this guard, named as an ITEM rather than excused as a class.
#: `data-quality-inspect-source`'s step is called `write-manifest`, which is also the whole verb
#: `archive-write-manifest`. Both are outside the scope of the change that added this guard —
#: data-quality already had its steps and archive's verb name is years old — so the collision is
#: recorded here rather than fixed in passing. Anything else colliding is a defect.
_KNOWN_NAME_COLLISIONS = {"write-manifest"}


def test_no_step_name_collides_with_a_verbs_own_span_name(step_scan):
    """`function` carries both, so a name used for both returns a verb total and an inner step.

    An operator filtering on the span name is the whole reason a span HAS a name, and a collision
    silently merges a Lambda's total duration with an internal operation's — the two are not
    comparable and nothing in the record says they are different kinds of thing.

    Found by sweeping the fleet rather than by reading one verb: three names were corrected during
    SPEC-226 by checking each verb against its own root span, and a fourth collided with a
    DIFFERENT verb's, which that check could not see. This is the sweep, kept.

    Args:
      step_scan: The shared span-decorator scanner.

    Returns:
      None.

    Raises:
      None.
    """
    traced, stepped = _span_names(step_scan)
    assert len(traced) > 40 and len(stepped) > 15, (
        f"the scan found {len(traced)} verb names and {len(stepped)} step names, so it is not "
        "reading the fleet and an empty result would pass this guard vacuously"
    )

    collisions = {
        name: {"verb": traced[name], "step": stepped[name]}
        for name in set(traced) & set(stepped)
        if name not in _KNOWN_NAME_COLLISIONS
    }
    assert not collisions, (
        f"these span names are used for both a whole verb and an internal step: {collisions}. "
        "Name the operation, not the verb."
    )


def test_the_known_collision_still_exists_and_is_the_only_one_excused(step_scan):
    """An exemption for something already fixed is a hole nobody is watching.

    Args:
      step_scan: The shared span-decorator scanner.

    Returns:
      None.

    Raises:
      None.
    """
    traced, stepped = _span_names(step_scan)
    stale = {name for name in _KNOWN_NAME_COLLISIONS if name not in (set(traced) & set(stepped))}
    assert not stale, (
        f"{stale} is excused as a pre-existing collision and is no longer one — delete the "
        "entry so the guard covers that name again"
    )


def test_reading_a_retired_collector_does_not_flush_into_the_live_one():
    """The `is self` gate on the drain, driven rather than asserted about in a docstring.

    `flush` delivers to whatever sink the library is CONFIGURED with, not to the one being read.
    So a read of a retired collector — one a later `configure` swapped out, which every teardown
    creates — would push whatever is currently buffered into somebody else's collector, as a side
    effect of reading this one. A test that then asserted "nothing has arrived yet" would be
    measuring another test's read.

    Both sinks are the shared `_CapturingSink`, loaded the way `conftest` is elsewhere in this
    file, because the gate is that class's and a local stand-in would not have it.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "root_conftest_drain_probe", _LAMBDAS / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    retired = module._CapturingSink()
    lf.configure(service="test", version="0", env="test", sink=retired)
    live = module._CapturingSink()
    lf.configure(service="test", version="0", env="test", sink=live)

    @observability.step("buffered-step")
    def emit_inside_a_span():
        """Narrates from inside a span, so the event is buffered rather than delivered.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        observability.info("buffered until a flush")

    emit_inside_a_span()

    #: The LIVE sink's backing list, read without going through the draining property, because
    #: reading `live.events` would flush by itself and erase the difference being measured. This
    #: is the only observation that separates the two behaviours: `retired.events` is empty either
    #: way, since an ungated flush still delivers to whoever is configured, not to the reader.
    assert live._events == [], "the event was delivered before anything asked for it"

    read_from_the_retired_collector = retired.events

    assert live._events == [], (
        "reading the RETIRED collector flushed the live one's buffered events into it — a read "
        "must not have a side effect on another collector"
    )
    assert read_from_the_retired_collector == [], (
        "the retired collector received something it never emitted"
    )

    assert live.events, "the live collector never received the event, so the check above is moot"

    lf.configure(service="test", version="0", env="test", sink=module._CapturingSink())
