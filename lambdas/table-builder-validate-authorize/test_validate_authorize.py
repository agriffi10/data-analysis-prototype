"""Unit tests for the table-builder validate-authorize Lambda.

Pure logic, AWS stubbed: auth.verified_username is stubbed for the authorization and
validation cases, the registry read for the shared-space cases. Asserts the validated
payload shape and every terminal reason. Runnable under pytest or directly:
python3 test_validate_authorize.py.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "table-builder-common"))

import validate_authorize as v
from cpcommon import clients, config
from cpcommon.errors import TerminalError, TransientError


class _FakeClientError(Exception):
    """A botocore-SHAPED error carrying ``.response["Error"]["Code"]`` — what the verb's
    transient classifier actually reads (a code-in-the-message exception would be a no-op)."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": code}}

# Capture the REAL verified_username before any test patches the shared module attr.
_REAL_VERIFIED = v.auth.verified_username


class _FakeSqs:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def _arm_notifications():
    config.NOTIFICATIONS_QUEUE_URL = "https://sqs.test/dat-prod-notifications-requests.fifo"
    fake = _FakeSqs()
    clients._sqs = fake
    return fake

USER_BUCKET = "dat-prod-user-space"
SHARED_BUCKET = "dat-prod-shared-space"


def _setup():
    """Reset patched config + stubs to a known baseline before each case."""
    v.config.USER_SPACE_BUCKET = USER_BUCKET
    v.config.SHARED_SPACE_BUCKET = SHARED_BUCKET
    v.auth.verified_username = lambda token: "alice"
    v.reg.load = lambda name: None


def _event(
    space, table_name="sales_2026", partition_keys=None, token="tok", request_id="r1", mode=None,
    allow_removals=None,
):
    body = {"idToken": token, "space": space, "tableName": table_name, "requestId": request_id}
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


def _expect_reason(event, reason):
    try:
        v.handler(event, None)
    except TerminalError as exc:
        assert exc.reason == reason, f"expected {reason!r}, got {exc.reason!r} ({exc.detail})"
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


def test_notifies_actor_on_forbidden():
    _setup()
    q = _arm_notifications()
    try:
        v.handler(_event(_personal(database="bob", prefix="bob/x/")), None)
    except TerminalError:
        pass
    assert len(q.calls) == 1
    assert q.calls[0]["MessageGroupId"] == "alice"  # the verified actor
    assert q.calls[0]["MessageDeduplicationId"] == "r1:validate"
    body = json.loads(q.calls[0]["MessageBody"])
    assert body == {
        "action": "create",
        "username": "alice",
        "message": "You don't have access to create a table here.",
    }


def test_notifies_actor_on_invalid_table_name():
    _setup()
    q = _arm_notifications()
    try:
        v.handler(_event(_personal(), table_name="Sales-2026"), None)
    except TerminalError:
        pass
    body = json.loads(q.calls[0]["MessageBody"])
    assert body["message"] == 'Couldn\'t create table "Sales-2026": the name isn\'t a valid table name.'


def test_no_notification_when_unauthorized_no_actor():
    _setup()
    # Token verify fails BEFORE the actor is known — there's no recipient to notify.
    def _raise(token):
        raise TerminalError("unauthorized", "expired")

    v.auth.verified_username = _raise
    q = _arm_notifications()
    try:
        v.handler(_event(_personal()), None)
    except TerminalError:
        pass
    assert q.calls == []


def test_no_notification_on_success():
    _setup()
    q = _arm_notifications()
    v.handler(_event(_personal()), None)
    assert q.calls == []


def test_transient_registry_error_is_raised_as_TransientError():
    """The registry read (S3 GetObject) can throttle. It must reach the SFN as
    TransientError — the name ValidateAuthorize's Retry list now recognizes — not a bare
    ClientError that would permanently fail the request."""
    _setup()
    v.reg.load = lambda name: (_ for _ in ()).throw(_FakeClientError("SlowDown"))
    try:
        v.handler(_event(_shared()), None)
    except TransientError:
        return
    except TerminalError:
        raise AssertionError("a throttle must not be terminalized")
    raise AssertionError("expected TransientError from a throttled registry read")


def test_non_transient_registry_error_propagates_unchanged():
    """AccessDenied is deterministic — mapping it to TransientError would waste retries."""
    _setup()
    v.reg.load = lambda name: (_ for _ in ()).throw(_FakeClientError("AccessDenied"))
    try:
        v.handler(_event(_shared()), None)
    except TransientError:
        raise AssertionError("a deterministic fault must NOT become TransientError")
    except _FakeClientError as err:
        assert err.response["Error"]["Code"] == "AccessDenied"
        return
    raise AssertionError("expected the original ClientError to propagate")


# ── mode: the create/refresh branch selector (SPEC-143 FR-001 / FR-002) ──────


def test_an_envelope_with_no_mode_is_byte_for_byte_the_shipped_create():
    """FR-001 AC2 — the additive-by-construction claim, asserted rather than asserted-to.

    Every producer shipped before SPEC-143 sends SPEC-067's envelope, which has no `mode`
    at all. This compares the WHOLE validated payload against an explicit `mode: "create"`
    request, so a defaulting bug cannot hide in a field the other mode tests don't read.
    """
    _setup()
    implicit = v.handler(_event(_personal()), None)
    explicit = v.handler(_event(_personal(), mode="create"), None)

    assert implicit == explicit
    assert implicit["mode"] == "create"
    # The SPEC-067 threaded state, pinned as a key set, so a future field cannot arrive on
    # this payload without a downstream state being taught to read it. `mode` (SPEC-143)
    # and `allowRemovals` (SPEC-144) are the only additions.
    assert set(implicit) - {"mode", "allowRemovals"} == {
        "actor", "space", "tableName", "partitionKeys", "location", "requestId",
    }


def test_a_refresh_is_authorized_exactly_like_a_create():
    _setup()
    out = v.handler(_event(_personal(), mode="refresh"), None)

    assert out["mode"] == "refresh"
    assert out["actor"] == "alice"
    # validate-authorize still emits the request's own location; load-table-definition
    # overwrites it from the catalog (FR-002 AC4).
    assert out["location"] == "s3://dat-prod-user-space/alice/sales/2026/"
    assert out["partitionKeys"] == []


def test_an_unknown_mode_is_a_typed_terminal_not_a_silent_create():
    """FR-001 AC3. The Choice's Default is create, so an unvalidated unknown mode would
    quietly build a new table when the user asked to refresh an existing one.

    Case-variants and a trailing space are in the list deliberately: the check is exact
    equality, not a normalize-then-compare, so "Refresh" is a typo the user must see
    rather than a spelling the system quietly accepts.
    """
    _setup()
    for mode in ("", "Refresh", "REFRESH", "update", "create ", 1, True, [], {}):
        _expect_reason(_event(_personal(), mode=mode), "invalid_mode")


def test_a_refresh_carrying_partition_keys_is_refused():
    """FR-002 AC1 — accepting them would be offering to CHANGE them, which the arc forbids."""
    _setup()
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100]}]
    _expect_reason(
        _event(_personal(), partition_keys=keys, mode="refresh"), "partition_keys_not_refreshable"
    )


def test_a_refresh_without_partition_keys_emits_an_empty_list():
    _setup()
    for keys in (None, []):
        out = v.handler(_event(_personal(), partition_keys=keys, mode="refresh"), None)

        assert out["partitionKeys"] == []


def test_a_refresh_outside_the_actors_space_still_raises_the_existing_forbidden():
    """FR-002 AC3 — _authorize_space is UNCHANGED and runs identically for both modes.

    The catalog is not the authorization boundary: the prefix the producer believes the
    table points at is authorized here, before anything reads Glue.
    """
    _setup()
    _expect_reason(_event(_personal(prefix="bob/secret/"), mode="refresh"), "forbidden")


def test_a_create_at_the_space_root_is_refused_in_both_space_kinds():
    """A table's LOCATION is read recursively, so a build at the root sweeps in every
    app-managed folder the space keeps there and SUCCEEDS while doing it. The refusal is the
    only thing standing between a user and a table whose rows are the portal's bookkeeping.

    Both kinds, because the root is derived differently in each: the actor's own name in the
    user-space bucket, the space's name in the shared one.
    """
    _setup()
    _expect_reason(_event(_personal(prefix="alice/")), "location_is_space_root")
    v.reg.load = lambda name: {"status": "active", "owner": "bob", "members": ["bob", "alice"]}
    _expect_reason(_event(_shared(prefix="salesdata/")), "location_is_space_root")


def test_the_root_refusal_survives_an_unnormalised_prefix():
    """The check runs on the NORMALISED prefix, after `_normalize_prefix`, so a producer
    sending `/alice` or `alice` is refused on the same rule rather than slipping past a
    string comparison the request happened not to match."""
    _setup()
    for raw in ("alice", "/alice/", " alice/ "):
        _expect_reason(_event(_personal(prefix=raw)), "location_is_space_root")


def test_a_folder_one_level_below_the_root_is_still_allowed():
    """The rule is the root ITSELF, not "shallow" — the shortest real folder still builds."""
    _setup()
    out = v.handler(_event(_personal(prefix="alice/sales/")), None)
    assert out["location"] == f"s3://{USER_BUCKET}/alice/sales/"


def test_a_refresh_at_the_space_root_is_NOT_refused():
    """Creates only. A refresh re-derives an existing table's columns from the location that
    table already has, so refusing one would strand any root table already in a catalog with
    no way to repair it — and a refresh chooses no new location to be wrong about."""
    _setup()
    out = v.handler(_event(_personal(prefix="alice/"), mode="refresh"), None)
    assert out["mode"] == "refresh"
    assert out["location"] == f"s3://{USER_BUCKET}/alice/"


def test_create_partition_key_validation_is_untouched_by_the_mode_branch():
    """FR-002 AC5 — pins that the refresh rule was added BESIDE the create rule, not
    woven into it. Same reason code, same message, for a create with and without an
    explicit mode."""
    _setup()
    bad = [{"name": "year", "type": "integer"}]  # integer with no range

    reasons = []
    for mode in (None, "create"):
        try:
            v.handler(_event(_personal(), partition_keys=bad, mode=mode), None)
        except TerminalError as err:
            reasons.append((err.reason, err.detail))

    assert reasons == [("invalid_partition_keys", "year: range must be [min, max]")] * 2


def test_mode_is_narrated_so_a_log_reader_can_tell_the_branches_apart():
    """Two branches through one service name are only separable if the field is emitted."""
    _setup()
    events = []
    # Restored explicitly: conftest's snapshot fixture covers config/clients/registry/auth,
    # NOT observability, so an unrestored patch here would follow into every later test.
    v.observability.info = lambda message, **fields: events.append((message, fields))
    v.handler(_event(_personal(), mode="refresh"), None)

    assert events[0][1]["mode"] == "refresh"


# ── allowRemovals: the removal opt-in (SPEC-144 FR-003) ──────────────────────


def test_allow_removals_defaults_to_false_and_is_always_a_boolean():
    _setup()
    for mode in (None, "create", "refresh"):
        out = v.handler(_event(_personal(), mode=mode), None)

        assert out["allowRemovals"] is False


def test_a_refresh_can_opt_into_removals():
    _setup()
    out = v.handler(_event(_personal(), mode="refresh", allow_removals=True), None)

    assert out["allowRemovals"] is True


def test_opting_into_removals_on_a_create_is_refused():
    """A create has nothing to remove, so the flag is a producer bug. Refused rather than
    ignored: dropping it silently would let a future caller believe removals were opted
    into when nothing read the field."""
    _setup()
    for mode in (None, "create"):
        _expect_reason(
            _event(_personal(), mode=mode, allow_removals=True), "removals_flag_not_applicable"
        )


def test_a_non_boolean_allow_removals_is_refused_rather_than_coerced():
    """`"false"` and `0` are the shapes a hand-crafted or mistyped producer sends, and
    truthiness would read `"false"` as opting IN — the wrong way round on the one flag
    that authorises data loss."""
    _setup()
    for flag in ("true", "false", 1, 0, [], {}):
        _expect_reason(
            _event(_personal(), mode="refresh", allow_removals=flag), "removals_flag_not_applicable"
        )


def test_the_opt_in_is_narrated():
    _setup()
    events = []
    v.observability.info = lambda message, **fields: events.append((message, fields))
    v.handler(_event(_personal(), mode="refresh", allow_removals=True), None)

    assert events[0][1]["allow_removals"] is True


def test_validate_authorize_state_retries_TransientError():
    """Pin the infra half: ValidateAuthorize's Retry must name TransientError, and its
    Catch must still route to ValidateFailureSeed (not disturbed by this change)."""
    import re

    tftpl = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "infra", "modules", "table-builder", "state-machine.asl.json.tftpl",
    )
    with open(tftpl) as fh:
        asl = json.loads(re.sub(r"\$\{[^}]+\}", "ARN", fh.read()))
    state = asl["States"]["ValidateAuthorize"]
    named = [e for r in state["Retry"] for e in r["ErrorEquals"]]
    assert "TransientError" in named, f"ValidateAuthorize Retry must name TransientError; got {named}"
    assert state["Catch"][0]["Next"] == "ValidateFailureSeed"


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


# ── SPEC-151 FR-007: partition-key validation is complete ───────────────────
#
# Every case below reached ddl._projection_props unvalidated and raised a bare KeyError
# or TypeError from inside infer-schema — surfacing to the user as "something went wrong"
# for a request they could simply have corrected. The refusal must name the key and be
# `invalid_partition_keys`, which is what the user-facing partition message keys on.


def test_a_date_key_without_a_format_is_invalid_not_a_bare_keyerror():
    """ddl._projection_props does key["format"] unguarded."""
    _setup()
    keys = [{"name": "sale_date", "type": "date", "range": ["2020-01-01", "2030-01-01"]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_a_date_key_with_a_blank_format_is_invalid():
    _setup()
    keys = [{"name": "sale_date", "type": "date", "range": ["2020-01-01", "2030-01-01"], "format": "   "}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_a_non_string_enum_value_is_invalid_not_a_bare_typeerror():
    """",".join over a non-string raises TypeError inside the renderer."""
    _setup()
    keys = [{"name": "region", "type": "string", "values": ["eu", 7]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_a_non_scalar_range_bound_is_invalid():
    _setup()
    keys = [{"name": "year", "type": "integer", "range": [2000, {"nope": 1}]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_a_boolean_range_bound_is_invalid():
    """bool IS an int in Python, so True would sail through an isinstance(int) check and
    render as the string "True" into a projection range."""
    _setup()
    keys = [{"name": "year", "type": "integer", "range": [True, 2100]}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_non_integer_digits_is_invalid():
    _setup()
    keys = [{"name": "year", "type": "integer", "range": [2000, 2100], "digits": "4"}]
    _expect_reason(_event(_personal(), partition_keys=keys), "invalid_partition_keys")


def test_a_fully_specified_date_key_is_accepted():
    """The negative cases above must not have made a legitimate key unusable."""
    _setup()
    keys = [
        {
            "name": "sale_date",
            "type": "date",
            "range": ["2020-01-01", "2030-01-01"],
            "format": "yyyy-MM-dd",
            "interval": 1,
            "intervalUnit": "DAYS",
        }
    ]
    out = v.handler(_event(_personal(), partition_keys=keys), None)
    assert out["partitionKeys"] == keys


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
