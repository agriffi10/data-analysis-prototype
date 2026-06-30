"""Unit tests for the table-builder validate-authorize Lambda (SPEC-067).

Pure logic, AWS stubbed: ``auth.verified_username`` is stubbed for the authorization /
validation cases (token verification itself is the proven shared-space code), and the
registry read is stubbed for the shared-space cases. Asserts the validated payload
shape and every terminal ``reason`` (with no side effects). Runnable under pytest OR
directly: ``python3 test_validate_authorize.py``.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import validate_authorize as v  # noqa: E402
from tbcommon.errors import TerminalError  # noqa: E402

# Capture the REAL verified_username before any test patches the shared module attr.
_REAL_VERIFIED = v.auth.verified_username

USER_BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"


def _setup():
    """Reset patched config + stubs to a known baseline before each case."""
    v.config.USER_SPACE_BUCKET = USER_BUCKET
    v.config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    v.auth.verified_username = lambda token: "alice"
    v.reg.load = lambda name: None


def _event(space, table_name="sales_2026", partition_keys=None, token="tok", request_id="r1"):
    body = {"idToken": token, "space": space, "tableName": table_name, "requestId": request_id}
    if partition_keys is not None:
        body["partitionKeys"] = partition_keys
    return [{"body": json.dumps(body)}]


def _personal(prefix="alice/sales/2026/", database="alice", bucket=USER_BUCKET):
    return {"kind": "personal", "bucket": bucket, "prefix": prefix, "database": database}


def _shared(prefix="salesdata/2026/", database="salesdata", bucket=SHARED_BUCKET):
    return {"kind": "shared", "bucket": bucket, "prefix": prefix, "database": database}


def _expect_reason(event, reason):
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
        return
    raise AssertionError(f"expected TerminalError({reason!r}), but handler succeeded")


# ── Happy paths ──────────────────────────────────────────────────────────────

def test_valid_personal_request_passes():
    _setup()
    out = v.handler(_event(_personal()), None)
    assert out["actor"] == "alice"
    assert out["tableName"] == "sales_2026"
    assert out["partitionKeys"] == []
    assert out["location"] == "s3://dat-prod-user-space/alice/sales/2026/"
    assert out["space"]["prefix"] == "alice/sales/2026/"
    assert out["requestId"] == "r1"


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


def test_prefix_is_normalized_with_trailing_slash():
    _setup()
    out = v.handler(_event(_personal(prefix="alice/sales/2026")), None)
    assert out["space"]["prefix"] == "alice/sales/2026/"
    assert out["location"] == "s3://dat-prod-user-space/alice/sales/2026/"


# ── Authorization failures (forbidden) ───────────────────────────────────────

def test_wrong_user_personal_is_forbidden():
    _setup()
    _expect_reason(_event(_personal(database="bob", prefix="bob/x/")), "forbidden")


def test_personal_wrong_bucket_is_forbidden():
    _setup()
    _expect_reason(_event(_personal(bucket="some-other-bucket")), "forbidden")


def test_out_of_space_personal_prefix_is_forbidden():
    _setup()
    _expect_reason(_event(_personal(prefix="bob/secret/")), "forbidden")


def test_non_member_shared_is_forbidden():
    _setup()
    v.reg.load = lambda name: {"status": "active", "owner": "bob", "members": ["bob"]}
    _expect_reason(_event(_shared()), "forbidden")


def test_inactive_shared_space_is_forbidden():
    _setup()
    v.reg.load = lambda name: {"status": "provisioning", "owner": "alice", "members": ["alice"]}
    _expect_reason(_event(_shared()), "forbidden")


def test_unknown_shared_space_is_forbidden():
    _setup()
    v.reg.load = lambda name: None
    _expect_reason(_event(_shared()), "forbidden")


def test_unknown_space_kind_is_forbidden():
    _setup()
    _expect_reason(_event({"kind": "team", "bucket": USER_BUCKET, "prefix": "alice/", "database": "alice"}), "forbidden")


# ── Name + partition-key validation ──────────────────────────────────────────

def test_bad_table_name_is_invalid_table_name():
    _setup()
    _expect_reason(_event(_personal(), table_name="Sales-2026"), "invalid_table_name")


def test_missing_table_name_is_invalid_table_name():
    _setup()
    _expect_reason(_event(_personal(), table_name=None), "invalid_table_name")


def test_partition_key_bad_name_is_invalid():
    _setup()
    keys = [{"name": "Year", "type": "integer", "range": [2000, 2100]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_partition_key_unknown_type_is_invalid():
    _setup()
    keys = [{"name": "year", "type": "float", "range": [2000, 2100]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_partition_key_missing_range_is_invalid():
    _setup()
    keys = [{"name": "year", "type": "integer"}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_partition_key_string_needs_values():
    _setup()
    keys = [{"name": "region", "type": "string", "values": []}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_partition_key_duplicate_name_is_invalid():
    _setup()
    keys = [
        {"name": "year", "type": "integer", "range": [2000, 2100]},
        {"name": "year", "type": "integer", "range": [2000, 2100]},
    ]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


# ── Token failures (unauthorized) ────────────────────────────────────────────

def test_missing_token_is_unauthorized():
    _setup()
    # Use the REAL verified_username — an empty token short-circuits before any JWKS call.
    v.auth.verified_username = _REAL_VERIFIED
    _expect_reason(_event(_personal(), token=""), "unauthorized")


def test_token_verification_failure_is_unauthorized():
    _setup()

    def _raise(token):
        raise TerminalError("unauthorized", "token verification failed: expired")

    v.auth.verified_username = _raise
    _expect_reason(_event(_personal()), "unauthorized")


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
