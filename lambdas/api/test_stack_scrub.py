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
from conftest import USERNAME_CLAIM, token

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
