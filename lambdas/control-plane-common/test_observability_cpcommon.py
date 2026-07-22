"""SPEC-127 FR-003 — the cpcommon.observability bootstrap.

The failure this module exists to avoid is a cold-start crash across a whole control plane: the
cpcommon layer attaches to every verb, and a shared layer's import-time work runs before any
handler code. So the tests here are weighted toward *import* behaviour and toward "logging never
fails a verb", not toward the happy path.
"""

import functools
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import log_foundry as lf  # noqa: E402

from cpcommon import observability  # noqa: E402


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


def test_module_exposes_exactly_three_public_names():
    """FR-003: init, flush, traced — nothing else is public."""
    public = {n for n in dir(observability) if not n.startswith("_")}
    # Imported modules/objects are not the module's API; only callables it defines.
    defined = {
        n
        for n in public
        if callable(getattr(observability, n))
        and getattr(getattr(observability, n), "__module__", "") == observability.__name__
    }
    assert defined == {"init", "flush", "traced"}


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
    source = open(observability.__file__).read()
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
        return None

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
