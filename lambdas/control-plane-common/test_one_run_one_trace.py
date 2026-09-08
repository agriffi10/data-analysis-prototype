"""A run is ONE trace, proved by driving it rather than by reading the source.

Every per-verb test in this repo can pass while a run is still nine traces. Each verb adopts
correctly, each state machine names the key, and nothing anywhere asks whether the value that
leaves one verb is the value the next one adopts. That is the question here, and it is asked by
running the real verbs in sequence and reading the spans they emit.

**The hops are the machine's, not this file's.** Each verb's event is built by applying the REAL
ASL block — `Validated`'s `Parameters`, `TransferObjects`'s `ItemBatcher.BatchInput`,
`NotifyArchived`'s `Parameters.Payload` — to the previous state, read out of the deployed
template. A hand-written event would agree with a hand-written assertion and prove nothing about
the machine; a wrong path in the template fails here.

**The planes are named rather than chosen.** A guard against data-quality, shared-spaces or
table-builder exercises no Map hop, no field-naming state and no inline-Map nesting, and would
pass while every one of those was broken. It runs against **file-send** and **archive**, which
between them cover all four event shapes a verb can receive.

What this does NOT drive is the middle of each chain — inspect-source, build-transfer-manifest,
collect-transfer-results — which need S3 fakes and whose returns are `{**event, ...}` echoes.
Their spans are not in the counts below, and that is stated rather than implied: what is proved
is that the value survives the four SHAPES, which is where it was being lost.

Attributes:
  _IDENTITY: The identity block the API stamps, as every plane's validator reads it.
  _UUID: One request id, shared by the archive fixtures so a run is followable across them.
  _LAMBDAS: The lambdas tree, for reaching a verb's directory by name.
"""

import json
import os
import pathlib
import sys

import log_foundry as lf
import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_LAMBDAS = _HERE.parent
for _dir in (
    "control-plane-common",
    "archive-common",
    "file-send-common",
    "archive-validate-authorize",
    "archive-copy-objects",
    "archive-notify",
    "file-send-validate-authorize",
    "file-send-copy-objects",
    "file-send-notify",
    "api",
):
    sys.path.insert(0, str(_LAMBDAS / _dir))

import archive_copy_objects
import archive_notify
import archive_validate_authorize
import file_send_copy_objects
import file_send_notify
import file_send_validate_authorize
import test_state_machines_cpcommon as machines
from cpcommon import observability
from token_shapes import JWT_SHAPED

_IDENTITY = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}
_UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


class _Sink:
    """Keeps every event so the run's spans can be read back.

    Attributes:
      events: Every event log-foundry delivered, in order.
    """

    def __init__(self):
        """Starts empty.

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
          batch: The events being delivered.

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

    def spans(self):
        """Every span-open event the run emitted.

        Args:
          None.

        Returns:
          A list of `span.start` events.

        Raises:
          None.
        """
        return [e for e in self.events if e.get("message") == "span.start"]


@pytest.fixture
def sink(monkeypatch):
    """Points log-foundry at a capturing sink and stubs every boundary the verbs touch.

    Args:
      monkeypatch: pytest's patcher.

    Yields:
      The capturing sink.

    Raises:
      None.
    """
    collector = _Sink()
    lf.configure(service="test", version="0", env="test", sink=collector)
    # Per-INVOCATION in production, so nothing clears it between tests; without this a driver
    # inherits the previous test's adopted trace and its assertions stop meaning what they say.
    observability._reset_context()
    monkeypatch.setattr(archive_validate_authorize.authz.reg, "load", lambda name: None)
    for module in (archive_validate_authorize, archive_notify, file_send_notify):
        monkeypatch.setattr(
            module.notify, "emit_notification", lambda *a, **kw: None, raising=False
        )
    monkeypatch.setattr(file_send_validate_authorize.reg, "load", lambda name: None)
    monkeypatch.setattr(
        file_send_validate_authorize.cognito, "user_exists", lambda name: True
    )
    yield collector
    lf.configure(service="test", version="0", env="test", sink=_Sink())


def _asl(plane):
    """The deployed template for one plane.

    Args:
      plane: The plane's module name.

    Returns:
      The parsed state machine.

    Raises:
      None.
    """
    path = next(
        p for p in machines._TEMPLATES if os.path.basename(os.path.dirname(p)) == plane
    )
    return machines._load(path)


def _state(plane, name):
    """One state out of a plane's deployed template, by qualified name.

    Args:
      plane: The plane's module name.
      name: The state's qualified name.

    Returns:
      The state.

    Raises:
      KeyError: If the machine holds no such state, which is itself the defect.
    """
    for qualified, state in machines._states(_asl(plane)):
        if qualified == name:
            return state
    raise KeyError(f"{plane} has no state {name!r}")


def _resolve(path, state):
    """Reads one `$.a.b` JSONPath out of a state.

    Args:
      path: The reference path.
      state: The state to read from.

    Returns:
      The value, or None where the path is absent — which is what makes an ABSENT key visible as
      a null rather than a KeyError, so a test asserting the value catches it.

    Raises:
      None.
    """
    if path == "$":
        return state
    value = state
    for segment in path.removeprefix("$.").split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(segment)
    return value


def _apply(block, state):
    """Builds one state's output from an ASL payload template, the way Step Functions does.

    Only the shapes these ten states and six Maps actually use: a `"x.$": "$.path"` reference and
    a literal. Anything else is refused loudly rather than silently ignored, because a template
    growing an intrinsic while this quietly dropped it is how the guard would go vacuous.

    Args:
      block: The `Parameters`, `Payload` or `BatchInput` template.
      state: The state it is evaluated against.

    Returns:
      The built payload.

    Raises:
      AssertionError: On a template shape this interpreter does not implement.
    """
    built = {}
    for key, value in block.items():
        if key.endswith(".$"):
            assert isinstance(value, str) and value.startswith("$"), (
                f"{key} holds {value!r}, which this interpreter does not evaluate — teach it, or "
                "the guard silently stops modelling the machine"
            )
            built[key.removesuffix(".$")] = _resolve(value, state)
        else:
            built[key] = value
    return built


def _api_message():
    """Mints the run's traceparent the way the API does, and returns the message body it sends.

    `build_message` inside a `@traced("request")` span IS the API's producer path — the span that
    stamps the value and the function that writes it are both the real ones. The HTTP handler is
    not driven here because it needs the API's own environment fixtures, and what it would add
    over this is routing rather than tracing; `test_enqueue_routes.py` drives it for all eleven
    routes against a real span.

    Starting anywhere else would follow a traceparent this test invented rather than the one a
    run actually begins with, which is the whole point of the assertion downstream.

    Args:
      None.

    Returns:
      The message body, as the plane's validate-authorize receives it.

    Raises:
      None.
    """
    from types import SimpleNamespace

    from apicommon import contract
    from apicommon import enqueue as enqueue_module
    from cpcommon.auth import Principal

    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "fileSend.enqueue")
    ctx = SimpleNamespace(principal=Principal(username="alice", claims={}))
    payload = {
        "requestId": "req-1",
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/q1.csv"}],
        },
        "recipients": [{"kind": "user", "name": "bob"}],
    }
    built = {}

    @observability.traced("request")
    def _mint(_event, context=None):
        """Builds the message inside the API's own span.

        Args:
          _event: Unused; `traced` reads it for a traceparent and there is none at the root.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        built["message"] = enqueue_module.build_message(route, ctx, payload)

    _mint({})
    assert built["message"].get("traceparent"), "the API minted no traceparent to follow"
    return built["message"]


def _minted_traceparent():
    """One traceparent minted inside a root span, the way the API mints a run's.

    `run_traceparent()` called with no span open returns None — or, on a warm process, whatever
    the PREVIOUS invocation adopted, because `_ADOPTED` is a ContextVar cleared per invocation
    rather than per test. Reading it that way made archive's driver assert something different
    depending on which order pytest selected the tests in, and pass either way.

    Args:
      None.

    Returns:
      A W3C traceparent belonging to a span that really opened.

    Raises:
      None.
    """
    minted = {}

    @observability.traced("request")
    def _root(_event, context=None):
        """Reads the root span's own traceparent.

        Args:
          _event: Unused.
          context: Unused.

        Returns:
          None.

        Raises:
          None.
        """
        minted["value"] = observability.run_traceparent()

    _root({})
    return minted["value"]


def _drive_file_send():
    """Drives a file-send run through the four event shapes, hop by hop.

    Args:
      None. The `sink` fixture installs the capturing sink; this only drives verbs.

    Returns:
      The number of verbs driven.

    Raises:
      None.
    """
    message = _api_message()

    validated = file_send_validate_authorize.handler([{"body": json.dumps(message)}], None)
    after_validated = _apply(_state("file-send", "Validated")["Parameters"], validated)

    batch = _state("file-send", "TransferObjects")["ItemBatcher"]["BatchInput"]
    file_send_copy_objects.handler(
        {"BatchInput": _apply(batch, after_validated), "Items": []}, None
    )

    summary = _apply(
        _state("file-send", "ShapeSummary")["Parameters"],
        {**after_validated, "itemNames": [], "objectCount": 0, "outcomes": []},
    )
    file_send_notify.handler(summary, None)
    return 4


def _drive_archive():
    """Drives an archive run through the state payload, a Map batch and a Task payload.

    Args:
      None. The `sink` fixture installs the capturing sink; this only drives verbs.

    Returns:
      The number of verbs driven.

    Raises:
      None.
    """
    root = _minted_traceparent()
    body = {
        "requestId": _UUID,
        "mode": "archive",
        "actor": JWT_SHAPED,
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/reports/q1.csv"}],
        },
        "identity": _IDENTITY,
        "traceparent": root,
    }
    assert root and root.startswith("00-"), "archive was driven with no run to join"
    validated = archive_validate_authorize.handler([{"body": json.dumps(body)}], None)
    after_validated = _apply(_state("archive", "Validated")["Parameters"], validated)

    batch = _state("archive", "TransferObjects")["ItemBatcher"]["BatchInput"]
    archive_copy_objects.handler(
        {"BatchInput": _apply(batch, after_validated), "Items": []}, None
    )

    payload = _state("archive", "NotifyArchived")["Parameters"]["Payload"]
    archive_notify.handler(
        _apply(payload, {**after_validated, "objectCount": 0, "totalBytes": 0}), None
    )
    return 3


@pytest.mark.parametrize(
    "plane,drive",
    [("file-send", _drive_file_send), ("archive", _drive_archive)],
    ids=["file-send", "archive"],
)
def test_a_run_is_one_trace_end_to_end(sink, plane, drive):
    """The headline guard: every span a run emits carries ONE trace id.

    The two preconditions are asserted FIRST and deliberately. An assertion that every span in a
    set shares a trace id is trivially true of a set with one span in it, and vacuously true of
    an empty one — so a harness that silently stopped driving verbs would read as a passing
    guard. The count and the distinct-verb count are what make the third assertion mean
    something.
    """
    driven = drive()
    observability.flush()

    spans = sink.spans()
    verbs = {e.get("fields", {}).get("verb") for e in spans}
    traces = {e["trace_id"] for e in spans}

    assert len(spans) >= driven, (
        f"{plane} drove {driven} verbs and emitted {len(spans)} spans, so the run was not "
        "followed to the end"
    )
    assert len(verbs) > 1, f"{plane} contributed one verb ({verbs}), which joins nothing"
    assert len(traces) == 1, (
        f"{plane} is {len(traces)} traces, not one: "
        + json.dumps(
            sorted(
                {
                    (e.get("fields", {}).get("verb"), e["trace_id"])
                    for e in spans
                }
            )
        )
    )


def test_every_span_of_a_driven_run_carries_the_request_id(sink):
    """`request_id` stays the join key for anything outside the trace, so it travels too.

    Both planes supply one. table-share is the fleet's exception and cannot be driven into this
    assertion, so it is asserted STATICALLY below rather than left to a harness that never
    reaches it — an exception whose population is empty is dead code that can neither widen nor
    narrow.
    """
    _drive_file_send()
    observability.flush()

    # The API's own span is excluded, and for a reason rather than to make this pass: its
    # correlation key is the GATEWAY's request id, stamped by the router from
    # `requestContext.requestId` and never from the body — that is what stops a caller naming
    # this service's key. `_api_message` drives the producer, not the router, so no gateway id
    # exists here. `test_enqueue_routes.py` holds that half against the real handler.
    plane_spans = [e for e in sink.spans() if e.get("fields", {}).get("verb") != "request"]

    assert plane_spans, "no plane spans, so this proves nothing"
    without = [
        e.get("fields", {}).get("verb")
        for e in plane_spans
        if not e.get("fields", {}).get("request_id")
    ]

    assert not without, f"{without} emitted a span with no request id"


@pytest.mark.parametrize(
    "plane,module,dropped",
    [
        ("file-send", "file-send-collect-transfer-results", ("guardResults", "source")),
        ("table-share", "table-share-collect-transfer-results", ("guardResults",)),
    ],
    ids=["file-send", "table-share"],
)
def test_the_two_verbs_that_filter_their_echo_keep_the_runs_trace(plane, module, dropped):
    """Every threaded read downstream of these two rests on an echo nothing pinned.

    Most verbs return `{**event, ...}` and cannot drop a key they were not told about. These two
    return `{**{k: v for k, v in event.items() if k not in (...)}, ...}` — an explicit exclusion
    set, and a key added to it disappears from every state after them. Measured before this test
    existed: adding `"traceparent"` to file-send's set left the ENTIRE `pytest lambdas/` run
    green while `ShapeSummary` downstream would read `$.traceparent` off a state that no longer
    had one, which is an uncatchable `States.Runtime`.

    Read out of the source rather than driven, and the reason is worth stating: driving them
    needs a Map Run export in S3 and a plan reader, and what is being asserted is a property of
    the EXCLUSION SET, which is a literal. The set is read from the module and checked against
    what the plane is allowed to drop.
    """
    source = (_LAMBDAS / module).glob("*.py")
    text = "".join(
        f.read_text(encoding="utf-8") for f in source if not f.name.startswith("test_")
    )

    assert "event.items()" in text, (
        f"{module} no longer filters its echo, so this guard is watching the wrong mechanism"
    )
    excluded = {
        name
        for name in ("traceparent", "requestId", *dropped)
        if f'"{name}"' in text.split("event.items()")[1].split("}")[0]
    }

    assert "traceparent" not in excluded, (
        f"{plane}'s collector drops the traceparent from its echo, so every state after it reads "
        "`$.traceparent` off a state that does not have one"
    )
    assert excluded == set(dropped), (
        f"{plane}'s collector now drops {sorted(excluded)}; it is allowed to drop "
        f"{sorted(dropped)}, and anything else is a key some later state may still read"
    )


def test_table_shares_map_children_are_the_one_exception_and_it_cannot_widen():
    """The exception is a property of table-share's contract, so it is read off the contract.

    table-share's validator returns no `requestId` and no state downstream of it holds one, so
    its Map children have nothing to carry. Asserted in both directions: the plane really does
    supply none, and every OTHER plane with a Distributed Map really does — otherwise the
    exception would quietly become the rule.
    """
    validator = _LAMBDAS / "table-share-validate-authorize" / "table_share_validate_authorize.py"

    assert validator.exists(), "table-share's validator moved, so this reads nothing"
    source = validator.read_text(encoding="utf-8")
    assert '"requestId"' not in source, (
        "table-share's validator now returns a requestId, so the exception below is stale and "
        "its Map children should carry one"
    )

    for plane in ("archive", "file-ops", "file-send", "table-share"):
        for name, state in machines._states(_asl(plane)):
            batch = (state.get("ItemBatcher") or {}).get("BatchInput")
            if not batch:
                continue
            carries = "requestId.$" in batch
            assert carries == (plane != "table-share"), (
                f"{plane}:{name} is on the wrong side of the one exception"
            )
