"""SPEC-127 FR-003 — the cpcommon.observability bootstrap.

The failure this module exists to avoid is a cold-start crash across a whole control plane: the
cpcommon layer attaches to every verb, and a shared layer's import-time work runs before any
handler code. So the tests here are weighted toward *import* behaviour and toward "logging never
fails a verb", not toward the happy path.
"""

import functools
import importlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import log_foundry as lf
from cpcommon import observability


class RecordingSink:
    """Captures emitted batches so a test can assert on the events themselves."""

    def __init__(self):
        self.batches = []

    def emit(self, batch):
        self.batches.append(list(batch))

    def close(self):
        pass

    @property
    def events(self):
        return [event for batch in self.batches for event in batch]


@pytest.fixture(autouse=True)
def _reset_observability():
    """Undo `init()`'s once-per-process latch, and retire the worker + global config.

    Deliberately NOT `lf.shutdown()`. `shutdown()` is terminal — it closes the sink, joins the
    worker thread and sets a once-only flag — so calling it in teardown leaves every later test
    in this module with a dead worker that silently delivers nothing. That is the exact failure
    log-forge SPEC-013 exists to prevent, and it presents here the same way it would in a warm
    Lambda container: the first test passes, the rest see no events. Reset the module globals
    instead, which is what the library's own suite does.
    """
    observability._initialized = False
    # `importlib.reload` mutates the cached module in place and outlives the monkeypatched env
    # that motivated it, so a reload test would otherwise leave LOGS_QUEUE_URL set for every
    # later test — including tests in other files, which then build a real SQS client and pick
    # up whatever boto3 fake another suite installed. Snapshot and restore.
    saved_queue_url = observability.LOGS_QUEUE_URL
    saved_version = observability._VERSION
    yield
    observability._initialized = False
    observability.LOGS_QUEUE_URL = saved_queue_url
    observability._VERSION = saved_version

    from log_foundry import config as lf_config
    from log_foundry import decorator as lf_decorator

    worker = getattr(lf_decorator, "_worker", None)
    if worker is not None:
        worker.shutdown()
        lf_decorator._worker = None
    lf_config._config = lf_config.Config()


@pytest.fixture
def sink():
    s = RecordingSink()
    lf.configure(service="test", version="0.0.0", env="test", sink=s)
    observability._initialized = True  # pretend init() already ran, with our sink
    return s


# -- the public surface -----------------------------------------------------------------


def test_module_exposes_exactly_the_sanctioned_names():
    """SPEC-127 FR-003 + SPEC-130 FR-001/FR-004 — and nothing else is public.

    Kept as an EXACT set rather than a subset: the point of the module is that it is the only
    door to `log_foundry`, and a name that leaks onto the public surface by accident is a door
    nobody decided to open. `debug` and `critical` are absent deliberately — three levels are the
    whole vocabulary (SPEC-130 Out of Scope).
    """
    public = {n for n in dir(observability) if not n.startswith("_")}
    # Imported modules/objects are not the module's API; only callables it defines.
    defined = {
        n
        for n in public
        if callable(getattr(observability, n))
        and getattr(getattr(observability, n), "__module__", "") == observability.__name__
    }
    assert defined == {"init", "flush", "traced", "step", "stamp", "info", "warning", "error"}


# -- import safety: the cold-start failure no unit test can otherwise reach --------------


def test_import_succeeds_with_logs_queue_url_explicitly_absent(monkeypatch):
    """FR-003: written so the conftest env baseline cannot satisfy it.

    `monkeypatch.delenv` removes the variable outright rather than relying on it merely being
    unset by omission — the exact hole that hid the PR #196 layer-config break from unit tests.
    """
    monkeypatch.delenv("LOGS_QUEUE_URL", raising=False)
    assert "LOGS_QUEUE_URL" not in os.environ

    module = importlib.reload(importlib.import_module("cpcommon.observability"))
    assert module.LOGS_QUEUE_URL == ""


def test_logs_queue_url_is_read_with_environ_get_never_require():
    """FR-003: `_require` on this variable would crash every attaching verb at cold start."""
    source = Path(observability.__file__).read_text(encoding="utf-8")
    # The call form, not the bare word — the module docstring legitimately explains why
    # `config._require` is the thing being avoided.
    assert '_require("LOGS_QUEUE_URL")' not in source
    assert 'os.environ.get("LOGS_QUEUE_URL"' in source


# -- sink selection ---------------------------------------------------------------------


def test_unset_queue_url_configures_stdout_and_does_not_raise(monkeypatch):
    """FR-003: unset means stdout, not a crash — and local pytest gets readable NDJSON free."""
    monkeypatch.delenv("LOGS_QUEUE_URL", raising=False)
    module = importlib.reload(importlib.import_module("cpcommon.observability"))
    module._initialized = False

    module.init(service="data-quality")

    from log_foundry.sinks.stdout import StdoutSink

    assert isinstance(lf.get_config().sink, StdoutSink)


def test_set_queue_url_configures_sqs_sink_alone(monkeypatch):
    """FR-003: SQSSink ALONE — deliberately not a MultiSink with StdoutSink."""
    monkeypatch.setenv("LOGS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/1/dat-prod-logs")
    module = importlib.reload(importlib.import_module("cpcommon.observability"))
    module._initialized = False
    monkeypatch.setattr(module.clients, "sqs", lambda: object())

    module.init(service="data-quality")

    from log_foundry.sinks.sqs import SQSSink

    configured = lf.get_config().sink
    assert isinstance(configured, SQSSink)
    assert type(configured).__name__ != "MultiSink"


def test_init_stamps_service_env_and_version(sink, monkeypatch):
    """FR-003: `service` is the control plane, never the function."""
    observability._initialized = False
    monkeypatch.setattr(observability, "_VERSION", "1.4.2")
    monkeypatch.setenv("ENV_NAME", "prod")
    monkeypatch.setattr(lf, "configure", lambda **kw: captured.update(kw))
    captured = {}

    observability.init(service="data-quality")

    assert captured["service"] == "data-quality"
    assert captured["version"] == "1.4.2"
    assert captured["env"] == "prod"


def test_init_is_idempotent_within_a_process(monkeypatch):
    """FR-003: module-level init() plus a re-import under test is the ordinary case."""
    monkeypatch.delenv("LOGS_QUEUE_URL", raising=False)
    module = importlib.reload(importlib.import_module("cpcommon.observability"))
    module._initialized = False

    calls = []
    monkeypatch.setattr(lf, "configure", lambda **kw: calls.append(kw))

    module.init(service="data-quality")
    module.init(service="data-quality")

    assert len(calls) == 1


# -- flush: logging must never be the reason a verb fails -------------------------------


def test_flush_swallows_every_exception(monkeypatch, caplog):
    """FR-003: a sink that raises on emit must not propagate out of flush()."""

    def boom():
        raise RuntimeError("sink exploded")

    monkeypatch.setattr(lf, "flush", boom)

    observability.flush()  # must not raise

    assert any("flush failed" in r.message for r in caplog.records)


# -- traced -----------------------------------------------------------------------------


def test_traced_stamps_the_verb_on_every_event(sink):
    @observability.traced("inspect-source")
    def handler(event, context):
        return {"ok": True}

    handler({}, None)

    assert sink.events, "no events emitted"
    assert all(e["fields"]["verb"] == "inspect-source" for e in sink.events)


def test_traced_preserves_name_and_docstring(sink):
    """FR-003: Lambda resolves `module.handler` BY NAME."""

    @observability.traced("inspect-source")
    def handler(event, context):
        """Original docstring."""
        return

    assert handler.__name__ == "handler"
    assert handler.__doc__ == "Original docstring."
    assert functools.WRAPPER_ASSIGNMENTS  # sanity: wraps semantics are what we rely on


def test_traced_returns_the_handlers_value_unchanged(sink):
    @observability.traced("v")
    def handler(event, context):
        return {"statusCode": 200, "body": "x"}

    assert handler({}, None) == {"statusCode": 200, "body": "x"}


def test_traced_reraises_and_still_flushes_on_the_failure_path(sink, monkeypatch):
    """FR-003: the invocation whose trace is most worth having is the one that raised."""
    flushed = []
    monkeypatch.setattr(observability, "flush", lambda: flushed.append(True))

    @observability.traced("v")
    def handler(event, context):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        handler({}, None)

    assert flushed == [True]


def test_traced_span_records_the_failure(sink):
    @observability.traced("v")
    def handler(event, context):
        raise ValueError("boom")

    with pytest.raises(ValueError):
        handler({}, None)

    end = [e for e in sink.events if e["message"] == "span.end"]
    assert end and end[0]["status"] == "error"
    assert end[0]["error"]["type"] == "ValueError"


def test_baggage_does_not_leak_between_invocations(sink):
    """A warm container reuses the contextvar; a leaked request_id merges unrelated runs.

    This is the failure SPEC-128 FR-002 forbids in its "never invent a correlation key" form —
    a leaked key is an invented one, and nothing about the output looks wrong.
    """
    import log_foundry as lf_mod

    @observability.traced("v")
    def handler(event, context):
        if event.get("requestId"):
            lf_mod.set_baggage(request_id=event["requestId"])

    handler({"requestId": "run-1"}, None)
    handler({}, None)  # second run sets nothing

    second_batch = sink.batches[1]
    assert all(
        "request_id" not in e["fields"] for e in second_batch
    ), "run-1's request_id leaked into a later invocation"


# -- FR-001: the guard that a future re-pin cannot quietly regress ----------------------


def test_installed_log_foundry_has_a_repeatable_flush():
    """0.2.0's only drain was terminal: shutdown() closed the sink and joined the worker, so a
    handler that called it logged nothing for the rest of that warm container's life.
    """
    assert callable(getattr(lf, "flush", None))

    delivered = RecordingSink()
    lf.configure(service="t", version="0", env="t", sink=delivered)

    @lf.trace
    def work():
        return None

    work()
    lf.flush()
    first = len(delivered.events)
    work()
    lf.flush()

    assert len(delivered.events) > first, "the second flush on the same process delivered nothing"


def test_installed_log_foundry_puts_baggage_on_the_boundary_events():
    """The 0.4.0 property (log-forge SPEC-015), and the reason the pin is 0.4.0 not 0.3.0.

    Without it, `fields.request_id` reaches `info` events but not `span.start`/`span.end` — the
    records carrying duration_ms and status. Several tests in this file would then pass
    TAUTOLOGICALLY, asserting the absence of a key that is never present. That false green is
    what this guards.
    """
    delivered = RecordingSink()
    lf.configure(service="t", version="0", env="t", sink=delivered)

    @lf.trace
    def work():
        lf.set_baggage(request_id="r1")

    work()
    lf.flush()

    end = [e for e in delivered.events if e["message"] == "span.end"]
    assert end, "no span.end emitted"
    assert end[0]["fields"].get("request_id") == "r1", (
        "installed log-foundry predates SPEC-015 — re-pin to >=0.4.0"
    )


# -- SPEC-128 FR-002: the correlation key, on BOTH entry-point shapes -------------------


def _pipe_envelope(request_id):
    """The EventBridge Pipe envelope: the raw SQS batch, body as a JSON STRING.

    Shaped like the real thing rather than `{}` deliberately — a synthetic empty payload cannot
    tell "request_id absent because there was none" from "request_id absent because we failed to
    extract it", which is exactly how this bug survived the first live probe.
    """
    return [{"messageId": "m1", "body": json.dumps({"requestId": request_id, "space": {}})}]


def test_request_id_is_stamped_from_the_step_functions_payload(sink):
    """Every verb from inspect-source onward: a plain dict with the id at the top level."""

    @observability.traced("inspect-source")
    def handler(event, context):
        return None

    handler({"requestId": "run-1"}, None)

    assert all(e["fields"].get("request_id") == "run-1" for e in sink.events)


def test_request_id_is_stamped_from_the_pipe_envelope(sink):
    """validate-authorize's event is the raw SQS ARRAY, not the state payload.

    Live regression (2026-07-23): the verb that ESTABLISHES the request was the one verb that
    could not be joined to its own run, because the extractor only looked at the top level.
    """

    @observability.traced("validate-authorize")
    def handler(event, context):
        return None

    handler(_pipe_envelope("run-2"), None)

    end = [e for e in sink.events if e["message"] == "span.end"]
    assert end, "no span.end emitted"
    assert end[0]["fields"].get("request_id") == "run-2"


def test_request_id_is_stamped_from_a_single_record_envelope(sink):
    """parse_sqs_request also accepts a bare record dict; the extractor must match it."""

    @observability.traced("validate-authorize")
    def handler(event, context):
        return None

    handler({"messageId": "m1", "body": json.dumps({"requestId": "run-3"})}, None)

    assert all(e["fields"].get("request_id") == "run-3" for e in sink.events)


def _events(sink, message, function=None):
    """Every emitted event with `message`, optionally narrowed to one span `function`."""
    return [
        e
        for e in sink.events
        if e["message"] == message and (function is None or e["function"] == function)
    ]


# -- SPEC-130 FR-002: the root span is named after the verb ------------------------------


def test_traced_names_the_root_span_after_the_verb(sink):
    """Without `name=`, log-foundry falls back to `fn.__qualname__` — and EVERY Lambda entry
    point in this repo is named `handler`, so every root span in the fleet read the same.
    """

    @observability.traced("inspect-source")
    def handler(event, context):
        return None

    handler({}, None)

    boundaries = _events(sink, "span.start") + _events(sink, "span.end")
    assert boundaries, "no boundary events emitted"
    assert all(e["function"] == "inspect-source" for e in boundaries)
    assert not any(e["function"] == "handler" for e in sink.events)


def test_the_verb_field_survives_the_rename(sink):
    """FR-002: the rename is a discontinuity in a store retained forever, and `fields.verb` is
    what lets one query span the cutover. A rename that dropped the field would silently split
    every existing query's results at the deploy boundary.
    """

    @observability.traced("inspect-source")
    def handler(event, context):
        return None

    handler({}, None)

    start = _events(sink, "span.start")
    assert start and start[0]["fields"]["verb"] == "inspect-source"


# -- SPEC-130 FR-003: `verb` is baggage, so children inherit it -------------------------


def test_child_span_inherits_both_verb_and_request_id(sink):
    """The whole reason `verb` moved off `lf.trace(defaults=...)`.

    A span *default* applies to that span's own events and nothing nested inside it, so with the
    old shape a step event carried `request_id` (baggage) but not the verb — joinable to its run
    and unattributable to the verb that produced it.
    """

    @observability.step("probe-columns")
    def probe():
        return None

    @observability.traced("inspect-source")
    def handler(event, context):
        probe()

    handler({"requestId": "run-1"}, None)

    child = _events(sink, "span.start", function="probe-columns")
    assert child, "no child span emitted"
    assert child[0]["fields"]["verb"] == "inspect-source"
    assert child[0]["fields"]["request_id"] == "run-1"


def test_verb_is_stamped_after_the_baggage_reset(sink):
    """Order matters and is not obvious: `_reset_baggage` clears the WHOLE mapping.

    Stamped before the reset, the verb is wiped before the span opens and no event carries it —
    which is what `test_traced_names_the_root_span_after_the_verb`'s sibling assertion above
    would catch, but only indirectly. Asserted here directly against call order.
    """
    calls = []
    observability_reset = observability._reset_baggage
    observability_stamp = observability._stamp_verb

    def reset():
        calls.append("reset")
        observability_reset()

    def stamp(verb):
        calls.append("verb")
        observability_stamp(verb)

    observability._reset_baggage = reset
    observability._stamp_verb = stamp
    try:

        @observability.traced("v")
        def handler(event, context):
            return None

        handler({}, None)
    finally:
        observability._reset_baggage = observability_reset
        observability._stamp_verb = observability_stamp

    assert calls == ["reset", "verb"]


def test_verb_is_not_a_span_default(sink):
    """FR-003: `defaults={"verb": ...}` is REMOVED, not duplicated.

    Left in place alongside the baggage, the module would keep working and the defect it was
    removed to fix would be invisible — the root span would still carry the verb from the
    default, so only a child span would reveal which mechanism was actually doing the work.
    """
    source = Path(observability.__file__).read_text(encoding="utf-8")
    assert 'defaults={"verb"' not in source


def test_a_failing_set_baggage_warns_rather_than_failing_the_verb(monkeypatch, caplog, sink):
    def boom(**kv):
        raise RuntimeError("baggage exploded")

    monkeypatch.setattr(lf, "set_baggage", boom)

    @observability.traced("v")
    def handler(event, context):
        return {"ok": True}

    assert handler({}, None) == {"ok": True}
    assert any("could not stamp verb" in r.message for r in caplog.records)


# -- SPEC-130 FR-001: emitters that cannot fail a verb ----------------------------------


def test_emitter_attaches_its_event_to_the_enclosing_span(sink):
    """Same trace AND same span as the handler's own boundary events, inheriting both fields."""

    @observability.traced("inspect-source")
    def handler(event, context):
        observability.info("listed source", objects=142, format="csv")

    handler({"requestId": "run-1"}, None)

    start = _events(sink, "span.start")[0]
    emitted = _events(sink, "listed source")
    assert emitted, "the event never reached the sink"
    event = emitted[0]
    assert event["trace_id"] == start["trace_id"]
    assert event["span_id"] == start["span_id"]
    assert event["fields"]["verb"] == "inspect-source"
    assert event["fields"]["request_id"] == "run-1"
    assert event["fields"]["objects"] == 142
    assert event["level"] == "INFO"


@pytest.mark.parametrize(
    ("emit", "level"),
    [
        (lambda: observability.info("m"), "INFO"),
        (lambda: observability.warning("m"), "WARNING"),
        (lambda: observability.error("m"), "ERROR"),
    ],
)
def test_each_level_emits_at_its_own_level(sink, emit, level):
    @observability.traced("v")
    def handler(event, context):
        emit()

    handler({}, None)

    assert [e["level"] for e in _events(sink, "m")] == [level]


def test_an_emitter_with_no_span_open_emits_a_standalone_span(sink):
    """log-foundry FR-004: an orphan is not dropped, it becomes a one-event span.

    Worth asserting rather than assuming, because this is the path a unit test calling a helper
    directly takes — and a silently dropped orphan would make every such test tautologically
    green.
    """
    observability.info("orphan", n=1)

    emitted = _events(sink, "orphan")
    assert emitted, "the orphan event was dropped"
    assert emitted[0]["parent_span_id"] is None
    assert emitted[0]["fields"]["n"] == 1


class RaisingSink:
    """A sink whose `emit` fails, for the invariant: logging never fails a verb."""

    def emit(self, batch):
        raise RuntimeError("sink exploded")

    def close(self):
        pass


@pytest.fixture
def raising_sink():
    lf.configure(service="test", version="0.0.0", env="test", sink=RaisingSink())
    observability._initialized = True


@pytest.mark.parametrize("name", ["info", "warning", "error"])
def test_an_emitter_does_not_propagate_a_sink_failure(raising_sink, caplog, name):
    """The ORPHAN path is the one that matters here, and it is why this is parametrized on the
    emitters rather than run inside a span: with a span open the batch goes to the background
    worker, which absorbs sink failures itself, so a span-path test would pass even with the
    module's own guard deleted. With no span open the emitter calls `sink.emit` SYNCHRONOUSLY,
    in the middle of business logic — this test fails if the guard is removed.
    """

    def business_logic():
        getattr(observability, name)("something happened", key="value")
        return "the caller's own value"

    assert business_logic() == "the caller's own value"
    assert any("dropped" in r.message for r in caplog.records), (
        "the failure was swallowed silently — indistinguishable from a working emitter"
    )


# -- SPEC-130 FR-004: step() ------------------------------------------------------------


def test_step_emits_a_child_span_with_duration_and_status(sink):
    @observability.step("append-day")
    def append_day():
        return "written"

    assert append_day() == "written"
    lf.flush()

    end = _events(sink, "span.end", function="append-day")
    assert end, "no child span.end emitted"
    assert end[0]["status"] == "ok"
    assert isinstance(end[0]["duration_ms"], float)


def test_step_is_parented_to_the_handler_span(sink):
    @observability.step("probe-columns")
    def probe():
        return None

    @observability.traced("inspect-source")
    def handler(event, context):
        probe()

    handler({}, None)

    parent = _events(sink, "span.start", function="inspect-source")[0]
    child = _events(sink, "span.start", function="probe-columns")[0]
    assert child["trace_id"] == parent["trace_id"]
    assert child["parent_span_id"] == parent["span_id"]
    assert child["span_id"] != parent["span_id"]


def test_a_failing_step_closes_both_spans_and_re_raises_the_SAME_exception(sink):
    """Identity, not type. A wrapper that caught and re-raised a NEW exception of the same class
    would satisfy a `pytest.raises(ValueError)` assertion while destroying the traceback, the
    `__cause__` chain, and — for a TerminalError — everything `notifies_on_failure` reads.
    """
    original = ValueError("boom")

    @observability.step("probe-columns")
    def probe():
        raise original

    @observability.traced("inspect-source")
    def handler(event, context):
        probe()

    with pytest.raises(ValueError) as caught:
        handler({}, None)

    assert caught.value is original

    child_end = _events(sink, "span.end", function="probe-columns")
    parent_end = _events(sink, "span.end", function="inspect-source")
    assert child_end and child_end[0]["status"] == "error"
    assert child_end[0]["error"]["type"] == "ValueError"
    assert parent_end and parent_end[0]["status"] == "error"


def test_a_TerminalError_through_a_step_is_unchanged_and_still_notifies(sink):
    """The failure mode that would matter most: `@traced` sits OUTERMOST, above
    `@notifies_on_failure`, so anything a step did to an exception on the way up would reach the
    user as a wrong (or missing) notification rather than as a broken trace.
    """
    from cpcommon import messages, notify
    from cpcommon.errors import TerminalError

    notified = []

    @observability.step("probe-columns")
    def probe():
        raise TerminalError(
            messages.MALFORMED_EVENT, detail="operator-only text", tokens={"object": "a.csv"}
        )

    @observability.traced("inspect-source")
    @notify.notifies_on_failure(
        "inspect-source",
        emit_unexpected=lambda event, step: None,
        emit_terminal=lambda event, err, step: notified.append(err),
    )
    def handler(event, context):
        probe()

    with pytest.raises(TerminalError) as caught:
        handler({}, None)

    assert notified == [caught.value], "notifies_on_failure never saw the TerminalError"
    assert caught.value.tokens == {"object": "a.csv"}
    assert caught.value.detail == "operator-only text"
    assert caught.value.reason == messages.MALFORMED_EVENT


def test_a_step_called_with_no_handler_span_starts_its_own_root_trace(sink):
    """A unit test calling an instrumented helper directly must not raise — and the events it
    produces must still be recorded rather than dropped for want of a parent.
    """

    @observability.step("append-day")
    def append_day():
        return None

    append_day()
    lf.flush()

    start = _events(sink, "span.start", function="append-day")
    assert start and start[0]["parent_span_id"] is None


def test_a_step_does_not_fail_the_decorated_function_when_the_sink_raises(raising_sink):
    @observability.step("append-day")
    def append_day():
        return "written"

    assert append_day() == "written"
    lf.flush()


# -- SPEC-130 FR-006: the narrative never reaches the console ---------------------------


@pytest.mark.parametrize("name", ["info", "warning", "error"])
def test_emitters_never_forward_echo(monkeypatch, name):
    """The wrappers pass it False unconditionally, so no call site can turn it on."""
    captured = {}
    monkeypatch.setattr(lf, name, lambda message, **kw: captured.update(kw))

    getattr(observability, name)("m", objects=1)

    assert captured["echo"] is False


def test_echo_passed_as_a_field_is_dropped_and_warned(sink, caplog):
    """An unusually quiet mistake: `**fields` swallows the keyword, so the call neither fails
    nor echoes — it silently emits a field named `echo`, and nothing in the output says the
    author expected a console line. Dropping it silently would be the same class of failure.
    """

    @observability.traced("v")
    def handler(event, context):
        # Keyword spelled via ** so this file does not match the repo-wide grep in
        # test_the_console_echo_is_used_nowhere_in_the_lambdas_tree.
        observability.info("appended", **{"echo": True}, events=12)  # noqa: PIE804

    handler({}, None)

    emitted = _events(sink, "appended")
    assert emitted, "the event was lost along with the bad field"
    assert "echo" not in emitted[0]["fields"]
    assert emitted[0]["fields"]["events"] == 12
    assert any("`echo` is prohibited" in r.message for r in caplog.records)


def test_the_console_echo_is_used_nowhere_in_the_lambdas_tree():
    """Repo-wide rather than only the instrumented planes, so it cannot rot as SPEC-134 → 137
    instrument the rest of the fleet.

    The needle is BUILT rather than written literally — a test that greps for a string it
    contains itself is a test that can only ever fail.
    """
    import re

    needle = re.compile("echo" + r"\s*=\s*True")
    lambdas_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    offenders = []
    for dirpath, dirnames, filenames in os.walk(lambdas_root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            with open(path, encoding="utf-8") as handle:
                if needle.search(handle.read()):
                    offenders.append(os.path.relpath(path, lambdas_root))

    assert offenders == [], f"console echo is prohibited (SPEC-130 FR-006): {offenders}"


@pytest.mark.parametrize(
    ("event", "why"),
    [
        ({}, "empty state payload"),
        ([], "empty SQS batch"),
        ([{"messageId": "m1", "body": "not json at all"}], "unparseable body"),
        ([{"messageId": "m1", "body": json.dumps({"space": {}})}], "body carries no requestId"),
        ([{"messageId": "m1"}], "record has no body"),
        ("a string", "not an envelope at all"),
        (None, "no event"),
    ],
)
def test_no_usable_id_leaves_request_id_absent_and_never_raises(sink, event, why):
    """Absent, never defaulted: a fabricated correlation key merges unrelated runs."""

    @observability.traced("notify-failure")
    def handler(event, context):
        return None

    handler(event, None)  # must not raise

    assert all("request_id" not in e["fields"] for e in sink.events), why
