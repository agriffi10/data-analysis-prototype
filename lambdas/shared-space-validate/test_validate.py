"""Unit tests for the validate-authorize Lambda.

The actor needs no stub: it is read out of the identity block the API stamps, which this
harness builds. Every envelope still carries the advisory flat ``actor`` the producer writes,
set to a DIFFERENT user, so each case also asserts the block wins over the field beside it.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import auth
import validate as v
from fakes import install, raises

_PENDING_KEY = ("user-bkt", "alice/user_settings/shared-connections.json")


def _event(action="create", space="sales", actor="alice", members=None, identity=True):
    body = {
        "schemaVersion": 1,
        "requestId": "r1",
        "action": action,
        "actor": "spoofed",
        "space": space,
    }
    if identity:
        body["identity"] = {
            "actor": actor,
            "delegated_by": None,
            "assurance": "interactive",
        }
    if members is not None:
        body["payload"] = {"members": members}
    return [{"body": json.dumps(body)}]


def _seed_reg(s3, name="sales", owner="alice", members=("alice", "bob")):
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {"name": name, "owner": owner, "members": list(members), "status": "active"}
    ).encode()


def test_validate_create_emits_context_with_the_blocks_actor():
    install()
    ctx = v.handler(_event("create", "sales", actor="alice"), None)
    assert ctx == {
        "action": "create",
        "actor": "alice",
        "space": "sales",
        "payload": {},
        "registry": None,
        "requestId": "r1",
    }


def test_validate_rejects_non_owner_before_context():
    s3, *_ = install()
    _seed_reg(s3, members=["alice"])
    raises(
        lambda: v.handler(_event("delete", "sales", actor="mallory"), None),
        auth.AuthorizationError,
        "owner-only",
    )


def test_validate_refuses_a_message_with_no_identity_block():
    """Fail closed on the pre-cutover envelope, in this plane's own exception type.

    The old test here proved a forged TOKEN was refused, which cannot fail once no token is
    read — so it is re-expressed rather than deleted. The envelope this builds is exactly the
    one a message enqueued before the flip carries: a flat ``actor`` naming somebody, and no
    block. It must be refused, and the refusal must not fall back to that name.
    """
    install()
    raises(
        lambda: v.handler(_event("create", identity=False), None),
        auth.AuthorizationError,
        "identity block",
    )


# Intent recording: the durable pending cache entry + start notification (create/delete).


if __name__ == "__main__":
    fns = [v_ for k, v_ in sorted(globals().items()) if k.startswith("test_") and callable(v_)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} validate tests passed.")
    sys.exit(0)
