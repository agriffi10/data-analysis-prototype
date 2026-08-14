"""Unit tests for the acknowledge-membership verb (SPEC-073)."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import acknowledge_membership as ack
from auth import AuthorizationError
from fakes import install, raises


def _seed(s3, name="sales", members=("alice", "bob"), acknowledged=None):
    """Seed a registry (+ owner cache) for space ``name``; owner = members[0].

    ``acknowledged=None`` writes NO acknowledged field (a legacy, pre-073 record);
    pass a list to seed a post-073 record with explicit join status.
    """
    owner = members[0]
    record = {"name": name, "owner": owner, "members": list(members), "status": "active", "createdAt": "t0"}
    if acknowledged is not None:
        record["acknowledged"] = list(acknowledged)
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(record).encode()
    s3.store[("user-bkt", f"{owner}/user_settings/shared-connections.json")] = json.dumps(
        {"version": 1, "connections": [{"name": name, "role": "owner", "status": "active"}]}
    ).encode()


def _owner_members(s3, owner="alice"):
    cache = json.loads(s3.store[("user-bkt", f"{owner}/user_settings/shared-connections.json")])
    return cache["connections"][0]["members"]


def _member_roster(s3, member):
    """Read one MEMBER's own cached roster for the first space in their cache."""
    cache = json.loads(s3.store[("user-bkt", f"{member}/user_settings/shared-connections.json")])
    return cache["connections"][0]["members"]


def test_acknowledge_flips_pending_member_to_active():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=[])  # bob was added as pending
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is True
    reg2 = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    assert reg2["acknowledged"] == ["bob"]
    assert reg2["members"] == ["alice", "bob"]  # membership unchanged
    assert _owner_members(s3) == [
        {"username": "alice", "status": "active"},  # owner always active
        {"username": "bob", "status": "active"},
    ]


def test_acknowledge_fans_the_promotion_out_to_every_member_cache():
    """SPEC-186 FR-008: the roster is the only member-facing view of who is in a space.

    Writing the owner's projection alone left every member's copy — the acknowledging member's
    included — frozen at the status held when they were added, so a member read ``Pending`` about
    themselves beside a connections row saying ``Active``, and Refresh could not reconcile it.
    Reverting `_fan_out_roster` to `write_owner_projection` reddens this.
    """
    s3, _glue, _lf, _cognito = install()
    _seed(s3, members=("alice", "bob", "carol"), acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    ack.acknowledge_membership("sales", "bob", "req-a", reg)

    promoted = [
        {"username": "alice", "status": "active"},
        {"username": "bob", "status": "active"},
        {"username": "carol", "status": "pending"},
    ]
    assert _owner_members(s3) == promoted
    # Bob's OWN copy: the surface that contradicted itself.
    assert _member_roster(s3, "bob") == promoted
    # And every other member's, so the roster is one answer rather than one per reader.
    assert _member_roster(s3, "carol") == promoted


def test_acknowledge_survives_a_cache_failure_because_the_registry_already_committed():
    """SPEC-186 FR-008 AC4. The registry write is the consistency point.

    A raise here would fail the run, and the retry would find the member already acknowledged,
    no-op, and never write the caches at all — turning a recoverable stale roster into a
    permanent one.
    """
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])

    def explode(*_args, **_kwargs):
        raise RuntimeError("cache unavailable")

    original = ack.cache.write_roster_to_all
    ack.cache.write_roster_to_all = explode
    try:
        out = ack.acknowledge_membership("sales", "bob", "req-a", reg)
    finally:
        ack.cache.write_roster_to_all = original

    assert out["activated"] is True
    assert json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])["acknowledged"] == ["bob"]


def test_acknowledge_idempotent_when_already_active():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=["bob"])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    before = s3.store[("user-bkt", "alice/user_settings/shared-connections.json")]

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is False
    # No spurious projection write (FR-003).
    assert s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] == before


def test_acknowledge_legacy_member_is_noop():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=None)  # pre-073 record: members are all-active by back-compat
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    before = s3.store[("user-bkt", "alice/user_settings/shared-connections.json")]

    out = ack.acknowledge_membership("sales", "bob", "req-a", reg)

    assert out["activated"] is False
    assert s3.store[("user-bkt", "alice/user_settings/shared-connections.json")] == before


def test_acknowledge_rejects_owner():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    raises(
        lambda: ack.acknowledge_membership("sales", "alice", "req-a", reg),
        AuthorizationError,
        "owner does not acknowledge",
    )


def test_acknowledge_noop_for_non_member():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = ack.acknowledge_membership("sales", "carol", "req-a", reg)
    assert out["activated"] is False


def test_handler_uses_validated_context():
    s3, _glue, _lf, _cognito = install()
    _seed(s3, acknowledged=[])
    reg = json.loads(s3.store[("admin-bkt", "shared-spaces/sales.json")])
    out = ack.handler({"space": "sales", "actor": "bob", "requestId": "req-a", "registry": reg}, None)
    assert out["activated"] is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"All {len(fns)} acknowledge-membership tests passed.")
    sys.exit(0)
