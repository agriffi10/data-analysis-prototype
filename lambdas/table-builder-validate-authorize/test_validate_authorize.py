"""Unit tests for the table-builder validate-authorize Lambda.

Pure logic, AWS stubbed: the registry read is stubbed for the shared-space cases. The actor
needs no stub — it is read out of the message's identity block, which the API stamps and this
harness builds. Asserts the validated payload shape and every terminal reason.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import validate_authorize as v
from cpcommon.errors import TerminalError
from token_shapes import JWT_SHAPED

USER_BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"


def _setup():
    """Reset patched config + stubs to a known baseline before each case."""
    v.config.USER_SPACE_BUCKET = USER_BUCKET
    v.config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    v.reg.load = lambda name: None


def _event(
    space, table_name="sales_2026", partition_keys=None, actor="alice", request_id="r1", mode=None,
    allow_removals=None,
):
    body = {
        "identity": {"actor": actor, "delegated_by": None, "assurance": "interactive"},
        "space": space,
        "tableName": table_name,
        "requestId": request_id,
    }
    if partition_keys is not None:
        body["partitionKeys"] = partition_keys
    if mode is not None:
        body["mode"] = mode
    if allow_removals is not None:
        body["allowRemovals"] = allow_removals
    return [{"body": json.dumps(body)}]


def _personal(prefix="alice/sales/2026/", database="alice", bucket=USER_BUCKET):
    return {"kind": "personal", "bucket": bucket, "prefix": prefix, "database": database}


def _shared(prefix="salesdata/2026/", database="salesdata", bucket=SHARED_BUCKET):
    return {"kind": "shared", "bucket": bucket, "prefix": prefix, "database": database}


def _expect_reason(event, reason, detail=None):
    """Asserts the refusal, and — where given — WHICH refusal.

    The detail matters more than it looks. Four of this verb's authorization branches raise
    `forbidden`, so a test asserting only the code passes when the branch it names is deleted and
    a neighbouring one catches the same request: measured, removing the actor's-own-database
    check reddened nothing at all, because the fixture also escaped the personal prefix.
    """
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        if detail is not None:
            assert detail in exc.detail, f"expected detail {detail!r}, got {exc.detail!r}"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


def test_valid_personal_request_passes():
    _setup()
    out = v.handler(_event(_personal()), None)
    assert out["actor"] == "alice"
    assert out["tableName"] == "sales_2026"
    assert out["partitionKeys"] == []
    assert out["location"] == "s3://dat-prod-user-space/alice/sales/2026/"
    assert out["space"]["prefix"] == "alice/sales/2026/"
    assert out["requestId"] == "r1"
    # The run's trace, which every later verb on this plane adopts.
    assert out["traceparent"].startswith("00-")


def test_valid_shared_member_request_passes():
    _setup()
    v.reg.load = lambda name: {"status": "active", "owner": "bob", "members": ["bob", "alice"]}
    out = v.handler(_event(_shared()), None)
    assert out["actor"] == "alice"
    assert out["space"]["database"] == "salesdata"
    assert out["location"] == "s3://dat-prod-shared-space/salesdata/2026/"


def test_valid_partitioned_request_carries_keys():
    _setup()
    keys = [
        {"name": "year", "type": "integer", "range": [2000, 2100], "digits": 4},
        {"name": "month", "type": "integer", "range": [1, 12], "digits": 2},
        {"name": "region", "type": "string", "values": ["us-east-1", "eu-west-1"]},
    ]
    out = v.handler(_event(_personal(), partition_keys=keys), None)
    assert out["partitionKeys"] == keys


def test_wrong_user_personal_is_forbidden():
    _setup()
    _expect_reason(
        _event(_personal(database="bob", prefix="bob/x/")),
        "forbidden",
        "personal database must be the actor's own",
    )


def test_out_of_space_personal_prefix_is_forbidden():
    _setup()
    _expect_reason(
        _event(_personal(prefix="bob/secret/")), "forbidden", "location escapes the personal space"
    )


def test_non_member_shared_is_forbidden():
    _setup()
    v.reg.load = lambda name: {"status": "active", "owner": "bob", "members": ["bob"]}
    _expect_reason(_event(_shared()), "forbidden", "is not an active member")


def test_bad_table_name_is_invalid_table_name():
    _setup()
    _expect_reason(_event(_personal(), table_name="Sales-2026"), "invalid_table_name")


# ── allowRemovals: the removal opt-in (SPEC-144 FR-003) ──────────────────────


def test_a_message_with_no_identity_block_is_refused():
    """Fail closed on the pre-cutover envelope: a flat token, no block, no registry read.

    The refusal must land BEFORE the registry load, or the caller's non-identity has already
    been used as an existence oracle.
    """
    _setup()
    v.reg.load = lambda name: (_ for _ in ()).throw(AssertionError("AWS CALL: registry read"))

    body = {
        "idToken": JWT_SHAPED,
        "space": "alice",
        "tableName": "sales_2026",
        "requestId": "r1",
    }
    _expect_reason([{"body": json.dumps(body)}], "unauthorized")


# ── SPEC-151 FR-007: partition-key validation is complete ───────────────────
#
# Every case below reached ddl._projection_props unvalidated and raised a bare KeyError
# or TypeError from inside infer-schema — surfacing to the user as "something went wrong"
# for a request they could simply have corrected. The refusal must name the key and be
# `invalid_partition_keys`, which is what the user-facing partition message keys on.


def test_ACCEPTED_allow_removals_false_rides_a_create_while_true_is_refused():
    """SPEC-151 FR-007 asks for this asymmetry to be PINNED, not changed. `false` is the
    browser's always-present default and is accepted; `true` on a create is a producer bug
    asking for something the mode cannot do, and is refused rather than silently dropped
    (validate_authorize._normalize_removals). If this ever starts failing, the accepted
    asymmetry changed — revisit the decision, do not delete the test."""
    _setup()
    out = v.handler(_event(_personal(), allow_removals=False), None)
    assert out is not None
    _expect_reason(_event(_personal(), allow_removals=True), "removals_flag_not_applicable")


def test_an_unhashable_partition_type_reaches_this_plane_s_own_refusal():
    """A list HASHES on the way into the membership test, so before the type check it raised
    TypeError there — reported as an unexpected error, with this plane's own reason code never
    rendered onto the execution."""
    _setup()

    _expect_reason(
        _event(_personal(), partition_keys=[{"name": "day", "type": ["date"]}]),
        "invalid_partition_keys",
        "day: invalid type ['date']",
    )
