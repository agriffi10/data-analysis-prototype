"""No part of a bearer credential reaches a log record — including the stack of a failed span.

``log-foundry`` attaches ``traceback.format_exception`` to every failed span, and that was
examined once and ACCEPTED — for file contents, on the reasoning that the log store is
admin-only and a stack is diagnostic metadata a failed run needs. A user's ID token is a bearer
credential for as long as it lives, and that reasoning was never applied to a credential. The
library offers no way to turn the capture off, so the answer is to scrub at this boundary.

**The exposure is not automatic**, which is what makes scrubbing tractable: ``format_exception``
renders each frame's source line, not its locals, and the provider library's own messages carry
no token material. The live route is this repo's own code interpolating the token — or the
gateway event, whose headers hold it — into an exception message or a log field.

**The guard-the-guard is the important part of this file.** A sentinel that appears in no record
proves nothing if no record carries a stack at all: the router catches an authentication failure
and RETURNS a refusal, so every 401 closes its span successfully and ``error.stack`` is absent
from all of them. Asserting "the sentinel is in no byte" across those records is vacuously true.
So one test below drives a path that genuinely raises through the span, and asserts a stack was
captured — and only then that the sentinel is not in it.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import handler as api_handler
import router
from conftest import USERNAME_CLAIM, bearer, token

SENTINEL = "sentinel-9f3a2c7e-do-not-log"


def _event(method, path, headers=None, request_id="req-sentinel"):
    """One API Gateway payload-format-2.0 request."""
    return {
        "requestContext": {"http": {"method": method, "path": path}, "requestId": request_id},
        "headers": headers or {},
    }


def _sentinel_token(**over):
    """A token whose payload carries a unique, greppable marker."""
    return token(username=SENTINEL, **over)


def _every_failure_path():
    """Every way a request carrying the sentinel token can fail, as (label, headers)."""
    marked = _sentinel_token()
    return [
        ("malformed", {"authorization": f"Bearer {SENTINEL}-not-a-jwt"}),
        ("bad signature", {"authorization": f"Bearer {marked[:-6]}AAAAAA"}),
        ("wrong issuer", {"authorization": f"Bearer {_sentinel_token(iss='https://x.example')}"}),
        ("wrong audience", {"authorization": f"Bearer {_sentinel_token(aud='other')}"}),
        ("wrong token use", {"authorization": f"Bearer {_sentinel_token(token_use='access')}"}),
        ("expired", {"authorization": f"Bearer {_sentinel_token(exp=int(time.time()) - 60)}"}),
        ("no username", {"authorization": f"Bearer {token(**{USERNAME_CLAIM: None})}"}),
        ("wrong scheme", {"authorization": f"Basic {marked}"}),
    ]


def test_the_sentinel_reaches_no_byte_of_any_record(captured_events):
    """Every failure path, driven with a marked token, serialised whole and searched."""
    for _, headers in _every_failure_path():
        api_handler.handler(_event("GET", "/v1/user-directory", headers), None)

    serialised = json.dumps(captured_events.events)
    assert SENTINEL not in serialised, "a token's payload survived into a log record"

    for _, headers in _every_failure_path():
        assert headers["authorization"].split(" ")[1] not in serialised


def test_a_raising_path_DOES_capture_a_stack(captured_events, monkeypatch):
    """Guard-the-guard, and the reason this file is not self-congratulatory.

    Every refusal above is RETURNED rather than raised, so every one of those spans closes
    successfully and carries no `error` at all — which makes "the sentinel is in no stack" true
    of records that have no stack. This drives a path that genuinely raises through the span and
    asserts a stack was captured, so the assertion above is measuring something.

    The fault no longer escapes the entry point — it is converted into the envelope's
    InternalError one frame outside the span — so this asserts the recorded stack and the
    declared status together. The catch sits outside the span precisely so both remain true; a
    catch one frame in would end the span successfully and there would be no stack to scrub.
    """
    def _explode(headers):
        raise RuntimeError("verifier exploded")

    monkeypatch.setattr(router.principal, "resolve", _explode)

    response = api_handler.handler(_event("GET", "/v1/user-directory", bearer()), None)
    assert response["statusCode"] == 500, "the fault did not reach the caller as a declared code"

    ended = [event for event in captured_events.events if event["message"] == "span.end"]
    stacks = [event for event in ended if "error" in event]
    assert stacks, "no span carried an error — the sentinel assertion above would be vacuous"
    assert any("stack" in event["error"] for event in stacks), (
        "a failed span carried no error.stack, so the scrub has nothing to be a scrub OF"
    )


def test_a_raising_path_carrying_the_sentinel_still_leaks_nothing(captured_events, monkeypatch):
    """The two halves together: a real stack, and the credential absent from it."""
    def _explode(headers):
        raise RuntimeError("verifier exploded")

    monkeypatch.setattr(router.principal, "resolve", _explode)

    marked = _sentinel_token()
    api_handler.handler(
        _event("GET", "/v1/user-directory", {"authorization": f"Bearer {marked}"}), None
    )

    serialised = json.dumps(captured_events.events)
    assert "error" in serialised, "no error was captured, so this proves nothing"
    assert SENTINEL not in serialised
    assert marked not in serialised


def test_the_verifiers_own_message_carries_no_provider_text_and_no_token():
    """The reason code is a fixed literal; the provider's words go on __cause__.

    An API reads the code and never touches the cause. That split is what lets the control
    planes keep the sentence three suites pin while this boundary leaks nothing.
    """
    from cpcommon.auth import AuthError

    marked = _sentinel_token(iss="https://elsewhere.example")
    try:
        router.principal.resolve({"authorization": f"Bearer {marked}"})
    except AuthError as exc:
        assert SENTINEL not in str(exc)
        assert marked not in str(exc)
        assert "Invalid issuer" not in str(exc)
        assert "elsewhere.example" not in str(exc)
    else:
        raise AssertionError("expected the token to be refused")


def test_no_module_under_the_api_reads_the_chained_cause():
    """__cause__ is where the provider's own words are. Reading it here would undo the split."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr != "__cause__", f"{path.name} reads __cause__"


def test_no_module_interpolates_the_event_the_headers_or_a_token():
    """The live exposure route: this repo's own code putting a credential into a message.

    Formatted strings and `raise` arguments are swept together because they are the same
    mistake — a value that reads as internal being rendered into text that travels.
    """
    import ast
    import pathlib

    forbidden = {"event", "headers", "token", "id_token", "authorization", "credential"}
    root = pathlib.Path(__file__).resolve().parent

    for path in sorted(root.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # An f-string, a %-format, a .format() call and a raise argument are the same
            # mistake wearing four hats: a value that reads as internal being rendered into
            # text that travels. Sweeping only the first would have let the other three past.
            rendered = (
                isinstance(node, ast.JoinedStr)
                or (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod))
                or (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "format"
                )
                or isinstance(node, ast.Raise)
            )
            if not rendered:
                continue
            for part in ast.walk(node):
                if isinstance(part, ast.Name):
                    assert part.id not in forbidden, (
                        f"{path.name} renders {part.id!r} into text that travels"
                    )
                if isinstance(part, ast.Attribute):
                    assert part.attr not in forbidden, (
                        f"{path.name} renders .{part.attr} into text that travels"
                    )


def test_the_handler_passes_the_stack_ceiling_at_its_real_call_site():
    """The assertion the test below CANNOT make, and the reason both exist.

    Its first version called `observability.init(..., max_stack_bytes=...)` itself and then
    asserted on what it had just passed — so editing `handler.py` to drop the argument left the
    whole suite green. What that proved was a property of the logging layer, which is worth
    keeping; what it claimed was that this function sets the ceiling, which it never checked.

    So this reads the call `handler.py` actually makes.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(api_handler))
    init_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "init"
    ]
    assert init_calls, "handler.py no longer configures structured logging at all"
    assert any(
        keyword.arg == "max_stack_bytes" for call in init_calls for keyword in call.keywords
    ), (
        "handler.py configures logging without a stack ceiling, so a failed span attaches the "
        "library's default — this API handles a bearer credential and does not inherit that"
    )


def test_a_named_ceiling_is_applied_rather_than_stamped_as_a_field(monkeypatch):
    """A ceiling, not a control — and a reader must not mistake it for the scrub.

    Passed through **defaults it would be stamped on every event as a FIELD named
    max_stack_bytes and would bound nothing at all, which is a change that looks correct in a
    diff and does nothing. This pins the logging layer's half; the test above pins the caller's.
    """
    from cpcommon import observability

    captured = {}

    def _configure(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.lf, "configure", _configure)
    monkeypatch.setattr(observability, "_initialized", False)

    observability.init(service="api", max_stack_bytes=api_handler.MAX_STACK_BYTES)

    assert captured["max_stack_bytes"] == api_handler.MAX_STACK_BYTES
    assert "max_stack_bytes" not in captured["defaults"], (
        "the ceiling was passed as a default, so it is a FIELD on every event and bounds nothing"
    )


def test_the_control_planes_still_inherit_the_librarys_ceiling(monkeypatch):
    """The other seven planes must be untouched by the API's choice."""
    from cpcommon import observability

    captured = {}

    def _configure(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(observability.lf, "configure", _configure)
    monkeypatch.setattr(observability, "_initialized", False)

    observability.init(service="data-quality")

    assert captured["max_stack_bytes"] is None
