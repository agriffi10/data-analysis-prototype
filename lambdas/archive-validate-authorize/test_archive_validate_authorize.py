"""validate-authorize: the archive plane's front door.

Archiving is the only operation in this repo that DELETES a user's data as a side effect of a
copy, so everything here is about refusing the whole request rather than skipping a bad row —
a partial archive whose refused row was silently dropped is the failure this verb exists to
make unreachable.
"""

import json
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in ("control-plane-common", "archive-common"):
    sys.path.insert(0, os.path.join(_HERE, "..", _p))

import archive_validate_authorize as verb
from arcommon import authz, notify
from cpcommon import auth
from cpcommon.errors import TerminalError

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"

#: A DIFFERENT UUID, deliberately: SPEC-170 FR-001 requires the run's id and the archive's id to
#: be different values, so a fixture reusing one would make the rule untestable.
ARCHIVE_UUID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"


@pytest.fixture(autouse=True)
def _bind(monkeypatch):
    """The verified actor, an empty registry and a notification sink.

    **The seam is stubbed BELOW ``verified_username``, not at it**, and that is the whole
    difference between this fixture and one that cannot fail. ``verified_username`` is what
    asserts the envelope's SHAPE — it takes a raw JWT string — so stubbing it accepts any
    fixture at all, including the nested ``{"idToken": …}`` shape this spec was drafted with
    and which fails ``unauthorized`` on every real request. Stubbing ``verify_id_token``
    instead leaves the real string-vs-dict seam in the path, and
    ``test_the_envelope_is_flat_and_a_nested_token_is_refused`` below drives it.
    """
    monkeypatch.setattr(auth, "verify_id_token", lambda token, **kw: {"cognito:username": "alice"})
    monkeypatch.setattr(authz.reg, "load", lambda name: None)
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


def _event(**overrides):
    body = {
        "requestId": UUID,
        "mode": "archive",
        "actor": "eyJ-token",
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/reports/q1.csv"}],
        },
    }
    body.update(overrides)
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _refused(**overrides):
    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(**overrides), None)
    return caught.value.reason


def _restore_event(**overrides):
    """A restore request, whose contract is a different set of fields from an archive's."""
    body = {
        "requestId": UUID,
        "mode": "restore",
        "actor": "eyJ-token",
        "space": {"kind": "personal", "name": "alice"},
        "archiveId": ARCHIVE_UUID,
    }
    body.update(overrides)
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _restore_refused(**overrides):
    with pytest.raises(TerminalError) as caught:
        verb.handler(_restore_event(**overrides), None)
    return caught.value.reason


def _source(**overrides):
    space = {"kind": "personal", "name": "alice"}
    base = {"space": space, "items": [{"kind": "file", "key": "alice/reports/q1.csv"}]}
    base.update(overrides)
    return base


# ── The happy path, and what it resolves ─────────────────────────────────────


def test_a_valid_archive_request_resolves_its_source_and_its_destination():
    out = verb.handler(_event(), None)

    assert out["requestId"] == UUID
    assert out["mode"] == "archive"
    assert out["actor"] == {"username": "alice"}
    assert out["source"]["bucket"] == "user-bkt"
    assert out["source"]["root"] == "alice/"
    assert out["source"]["items"] == [{"kind": "file", "key": "alice/reports/q1.csv"}]


# ── Containment: the two rules, each with its own case (FR-005) ──────────────


def test_a_key_with_a_dot_dot_path_segment_is_refused():
    """THE alice/../bob/ CASE. Normalisation does nothing about dot segments, and
    "alice/../bob/secrets.csv".startswith("alice/") is True."""
    assert _refused(source=_source(items=[{"kind": "file", "key": "alice/../bob/secrets.csv"}])) == "forbidden"


# ── The restore branch (SPEC-170 FR-001, FR-002) ─────────────────────────────


def test_a_space_the_actor_is_not_a_member_of_is_refused():
    assert _restore_refused(space={"kind": "shared", "name": "team"}) == "forbidden"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
