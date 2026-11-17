"""Unit tests for the read-only name-collision report.

The common layer is added to sys.path here because `lambdas/conftest.py` does not list
shared-space-common among the layer roots it puts there.
"""

import json
import os
import sys
from datetime import UTC, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "shared-space-common"))

import name_collisions as nc
from cpcommon import clients
from fakes import FakeClientError, install, raises

import config

_EARLY = datetime(2026, 1, 1, tzinfo=UTC)
_LATE = datetime(2026, 6, 1, tzinfo=UTC)

#: Every call the report may make. Anything else on any of the four clients is a write.
_READS = {"list_objects_v2", "get_object", "list_users", "get_databases", "list_lake_formation_opt_ins"}

#: The read each failure plant breaks, by the client attribute and method it replaces.
_READ_METHODS = {
    "registry": ("_s3", "list_objects_v2"),
    "pool": ("_cognito", "list_users"),
    "glue": ("_glue", "get_databases"),
    "lakeformation": ("_lf", "list_lake_formation_opt_ins"),
}


def _record(s3, name, owner, members, status="active", ever_active=True):
    s3.store[("admin-bkt", f"shared-spaces/{name}.json")] = json.dumps(
        {
            "name": name,
            "owner": owner,
            "members": members,
            "status": status,
            **({"everActive": True} if ever_active else {}),
        }
    ).encode()


def _world():
    """A clean account: alice belongs to sales, bob has no space, and every database is its owner's."""
    s3, glue, lf, cognito = install()
    cognito.users = {"alice": {"custom:shared_space_1": "sales"}, "bob": {}}
    cognito.created = {"alice": _EARLY, "bob": _EARLY}
    _record(s3, "sales", "alice", ["alice"])
    for user in ("alice", "bob"):
        glue.databases.add(user)
        glue.create_times[user] = _LATE
    glue.seed_space_database("sales")
    glue.create_times["sales"] = _LATE
    return s3, glue, lf, cognito


def test_a_clean_account_lists_nothing_and_passes():
    _world()

    out = nc.report()

    for key in nc.DEPENDS_ON:
        assert out[key] == [], key
    assert out["failed_reads"] == [] and out["passed"] is True


def _a(s3, _glue, _lf, cognito):
    cognito.users["team_x"] = {}
    _record(s3, "team_x", "alice", ["alice"])
    return "usernames_that_are_spaces", ["team_x"]


def _b(_s3, glue, _lf, _cognito):
    glue.parameters["bob"] = {config.DATABASE_MARKER_KEY: "bob"}
    return "user_databases_marked_as_spaces", ["bob"]


def _c(_s3, _glue, _lf, cognito):
    cognito.users["bob"]["custom:shared_space_2"] = "sales"
    return "unbacked_slots", [{"username": "bob", "slot": "custom:shared_space_2", "value": "sales"}]


def _d(s3, glue, _lf, _cognito):
    _record(s3, "legacy", "alice", ["alice"])
    glue.databases.add("legacy")
    return "unmarked_space_databases", ["legacy"]


def _e(_s3, glue, _lf, _cognito):
    glue.databases.add("leftover")
    return "orphan_databases", ["leftover"]


def _f(_s3, glue, _lf, _cognito):
    glue.create_times["bob"] = datetime(2025, 1, 1, tzinfo=UTC)
    return "inherited_databases", ["bob"]


def _g(_s3, _glue, lf, _cognito):
    lf.opt_ins = [
        {"Principal": {"DataLakePrincipalIdentifier": "arn:aws:iam::1:role/portal"}},
        {"Principal": {"DataLakePrincipalIdentifier": "arn:aws:iam::1:role/portal"}},
    ]
    return "lake_formation_opt_ins", ["arn:aws:iam::1:role/portal"]


@pytest.mark.parametrize("plant", [_a, _b, _c, _d, _e, _f, _g])
def test_each_list_names_exactly_what_was_planted_and_nothing_else(plant):
    world = _world()
    key, expected = plant(*world)

    out = nc.report()

    assert out[key] == expected
    assert {k: v for k, v in out.items() if k in nc.DEPENDS_ON and v} == {key: expected}
    assert out["passed"] is (key not in nc.FAILING_LISTS)


def test_a_refused_reservation_named_for_a_user_is_information_not_a_collision():
    s3, _glue, _lf, cognito = _world()
    cognito.users["carol"] = {}
    _record(s3, "carol", "alice", ["alice"], status="failed", ever_active=False)

    out = nc.report()

    assert out["refused_reservations_named_for_users"] == ["carol"]
    assert out["usernames_that_are_spaces"] == []
    assert out["passed"] is True


def test_an_unbacked_slot_is_one_no_roster_including_the_user_stands_behind():
    s3, _glue, _lf, cognito = _world()
    cognito.users["bob"].update({"custom:shared_space_1": "ghost", "custom:shared_space_3": "gone"})
    _record(s3, "ops", "bob", ["bob"])
    cognito.users["bob"]["custom:shared_space_2"] = "ops"

    out = nc.report()

    assert out["unbacked_slots"] == [
        {"username": "bob", "slot": "custom:shared_space_1", "value": "ghost"},
        {"username": "bob", "slot": "custom:shared_space_3", "value": "gone"},
    ]


@pytest.mark.parametrize("read", sorted(_READ_METHODS))
def test_a_failed_read_fails_the_run_and_is_never_an_empty_list(monkeypatch, read):
    _world()
    holder, method = _READ_METHODS[read]

    def broken(**kwargs):
        raise FakeClientError("AccessDeniedException")

    monkeypatch.setattr(getattr(clients, holder), method, broken)

    out = nc.report()

    assert out["failed_reads"] == [read]
    assert out["passed"] is False
    for key, reads in nc.DEPENDS_ON.items():
        assert (out[key] is None) is (read in reads), key


class _Recording:
    """Wraps a fake client and records the name of every method called on it."""

    def __init__(self, inner):
        self._inner = inner
        self.called = []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name == "exceptions" or not callable(attr):
            return attr

        def call(*args, **kwargs):
            self.called.append(name)
            return attr(*args, **kwargs)

        return call


def test_the_report_makes_no_write_call_to_any_service():
    world = _world()
    for plant in (_a, _b, _c, _d, _e, _f, _g):
        plant(*world)
    recorders = {}
    for holder in ("_s3", "_cognito", "_glue", "_lf"):
        recorders[holder] = _Recording(getattr(clients, holder))
        setattr(clients, holder, recorders[holder])

    nc.report()

    called = {name for recorder in recorders.values() for name in recorder.called}
    assert called and called <= _READS, called - _READS


def test_the_handler_reads_nothing_without_a_request_id():
    _world()
    recorder = _Recording(clients._s3)
    clients._s3 = recorder

    raises(lambda: nc.handler({}, None), ValueError, "requestId")

    assert recorder.called == []
    assert nc.handler({"requestId": "gha-1"}, None)["passed"] is True


def test_a_refused_reservation_does_not_back_a_slot_its_creator_wrote_for_themselves():
    """A refused create leaves a failed record whose roster is its creator. Read as backing, it
    would hide the slot a user wrote naming someone else's database, once they asked for a space
    of that name."""
    s3, _glue, _lf, cognito = _world()
    cognito.users["bob"]["custom:shared_space_1"] = "alice"
    _record(s3, "alice", "bob", ["bob"], status="failed", ever_active=False)

    out = nc.report()

    assert out["unbacked_slots"] == [{"username": "bob", "slot": "custom:shared_space_1", "value": "alice"}]
    assert out["refused_reservations_named_for_users"] == ["alice"]
    assert out["unmarked_space_databases"] == []
    assert out["passed"] is False


def test_a_space_that_was_ever_active_is_real_even_failed_and_unmarked():
    s3, glue, _lf, cognito = _world()
    cognito.users["old_team"] = {}
    _record(s3, "old_team", "alice", ["alice"], status="failed", ever_active=True)
    glue.databases.add("old_team")

    out = nc.report()

    assert out["usernames_that_are_spaces"] == ["old_team"]
    assert out["refused_reservations_named_for_users"] == []
    assert out["passed"] is False


def test_the_run_record_carries_counts_and_never_a_name(monkeypatch):
    world = _world()
    for plant in (_a, _b, _c, _d, _e, _f, _g):
        plant(*world)
    records = []
    monkeypatch.setattr(nc.observability, "info", lambda message, **fields: records.append(fields))

    nc.report()

    (fields,) = records
    for key in nc.DEPENDS_ON:
        assert isinstance(fields[key], int), (key, fields[key])
    assert set(fields) == {*nc.DEPENDS_ON, "passed", "failed_reads"}
