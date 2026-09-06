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
from cpcommon.errors import TerminalError
from token_shapes import JWT_SHAPED

UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"

#: A DIFFERENT UUID, deliberately: SPEC-170 FR-001 requires the run's id and the archive's id to
#: be different values, so a fixture reusing one would make the rule untestable.
ARCHIVE_UUID = "b71d0f42-9c3e-4a17-b8f5-0d1e2f3a4b5c"


@pytest.fixture(autouse=True)
def _bind(monkeypatch):
    """An empty registry and a notification sink. The actor is not stubbed at all.

    It used to be, one layer BELOW ``verified_username``, so that the string-vs-dict seam that
    function asserted stayed in the path — a fixture stubbing the wrapper itself accepted any
    envelope shape, including one that failed on every real request. That hazard is gone with
    the verifier: ``trusted_actor`` is pure and reads only the identity block, so the shape
    every test here exercises is the shape production receives.
    """
    monkeypatch.setattr(authz.reg, "load", lambda name: None)
    sent = []
    monkeypatch.setattr(notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    monkeypatch.setattr(verb.notify, "emit_notification", lambda user, text, **kw: sent.append((user, text)))
    return sent


_JWT = JWT_SHAPED


def _block(actor):
    """The identity block the API stamps.

    Args:
      actor: The verified username it names.

    Returns:
      The block, with every field present.

    Raises:
      None.
    """
    return {"actor": actor, "delegated_by": None, "assurance": "interactive"}


def _event(actor="alice", identity=True, **overrides):
    body = {
        "requestId": UUID,
        "mode": "archive",
        "actor": _JWT,
        "source": {
            "space": {"kind": "personal", "name": "alice"},
            "items": [{"kind": "file", "key": "alice/reports/q1.csv"}],
        },
    }
    if identity:
        body["identity"] = _block(actor)
    body.update(overrides)
    return [{"messageId": "m-1", "body": json.dumps(body)}]


def _refused(**overrides):
    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(**overrides), None)
    return caught.value.reason


def _restore_event(actor="alice", identity=True, **overrides):
    """A restore request, whose contract is a different set of fields from an archive's."""
    body = {
        "requestId": UUID,
        "mode": "restore",
        "actor": _JWT,
        "space": {"kind": "personal", "name": "alice"},
        "archiveId": ARCHIVE_UUID,
    }
    if identity:
        body["identity"] = _block(actor)
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


def test_a_PERSONAL_source_that_is_not_the_actors_own_is_refused():
    """The other half of the source check, which had no test at all.

    Found by deleting the personal-source branch and watching this file stay green: every
    authorization negative here named a SHARED space, so the branch deciding whether alice may
    archive out of bob's prefix was asserted nowhere — on the one plane where a mistake is
    unrecoverable, since a completed archive sweeps the source.

    Every key is inside bob's root, so containment cannot refuse this first. That matters: with
    the items left at alice's default the request is refused either way, which is exactly how the
    gap stayed invisible.
    """
    refused = _refused(
        source={
            "space": {"kind": "personal", "name": "bob"},
            "items": [{"kind": "file", "key": "bob/reports/q1.csv"}],
        }
    )

    assert refused == "forbidden"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_the_block_decides_the_actor_on_both_modes_and_the_flat_field_does_not():
    """Two allowed-field sets, one per mode, and each must read the block rather than the field.

    The restore set lives in the archive layer rather than in this verb, so a change that
    touched only the local dict would pass an archive and refuse every restore. Both envelopes
    carry the flat ``actor`` holding a raw JWT, so a verb reading it would resolve a
    900-character string as a username instead of failing.
    """
    archived = verb.handler(_event(), None)
    restored = verb.handler(_restore_event(), None)

    assert archived["mode"] == "archive"
    assert restored["mode"] == "restore"
    assert archived["actor"] == {"username": "alice"}


def test_both_modes_refuse_a_message_with_no_identity_block():
    """Fail closed on the pre-cutover envelope, on each mode's own allowed-field set."""
    assert _refused(identity=False) == "unauthorized"
    assert _restore_refused(identity=False) == "unauthorized"


@pytest.mark.parametrize("kind", ["admin", "", None, 1, ["personal"]], ids=["unknown", "empty", "null", "int", "list"])
def test_the_source_space_kind_vocabulary_is_closed(kind):
    """Every unknown kind must reach the plane's own refusal, an UNHASHABLE one included.

    A frozenset membership test hashes its left operand, so a request naming a list raised
    TypeError out of the check itself — reported as an unexpected fault, with the archive
    plane's named refusal never rendered.
    """
    with pytest.raises(TerminalError) as caught:
        verb.handler(_event(source=_source(space={"kind": kind, "name": "alice"})), None)

    assert caught.value.reason == "forbidden"
    assert caught.value.detail == f"unknown source space kind {kind!r}"
