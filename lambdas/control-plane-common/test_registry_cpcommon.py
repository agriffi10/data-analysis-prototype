"""The registry's authorization predicates, pinned against a roster that is not a list.

``actor in members`` is only a membership test while ``members`` is a list. Against a string
Python matches substrings and against a dict it matches keys, so a record carrying
``"members": "alice,bob"`` would answer True for ``alice``, for ``bob``, and also for ``ali``
and ``lic`` — the same call, reading as a roster check and behaving as a substring match. Every
control plane that reaches a shared space decides it through this one function and never looks
at the record itself, which is why the type is asserted here rather than trusted from the JSON.
The planes are not counted here; ``test_space_reachability_predicates.py`` derives them.

Every refusal below is paired with a list-shaped positive control naming the SAME actor. A
predicate that had been tightened into always answering False would satisfy the refusals on its
own; only the control tells the two apart.

The owner lookup a share's notice needs is read under a budget, and its tests close the file.
"""

import json
import threading

import pytest
from cpcommon import budget, clients
from cpcommon import registry as reg


def _active(**fields):
    """Builds a live registry record carrying the given fields.

    Args:
      **fields: Record fields to set alongside the active status.

    Returns:
      The record.

    Raises:
      None.
    """
    return {"status": "active", "owner": "owner_of_space", **fields}


def test_a_string_roster_authorizes_neither_its_own_value_nor_a_substring_of_it():
    """The measured degradation: a comma-joined roster would admit members and fragments alike."""
    record = _active(members="alice,bob")

    assert reg.is_active_member(record, "alice") is False
    assert reg.is_active_member(record, "bob") is False
    assert reg.is_active_member(record, "ali") is False
    assert reg.is_active_member(record, "lic") is False


@pytest.mark.parametrize(
    "members",
    [
        "alice",
        {"alice": "active"},
        42,
    ],
    ids=["bare_string", "dict_keyed_by_member", "not_a_container"],
)
def test_a_roster_that_is_not_a_list_authorizes_nobody(members):
    """Every non-list shape ``json.loads`` can put here, and each fails differently.

    A single-name string and a dict keyed by the member both answer True to a bare ``in``; a
    scalar raises ``TypeError`` out of it. A row is only worth its place if it behaves
    differently before the check than after, which is why a dict that merely fails to contain
    the actor is not among them.
    """
    assert reg.is_active_member(_active(members=members), "alice") is False


def test_a_space_that_is_not_active_authorizes_its_own_members():
    """The other half of the predicate, which no suite in the fleet pinned before this one.

    Two planes' authorizers document their refusal of a still-provisioning space as coming from
    here, so a tightening that dropped the status test for a plain ``isinstance`` check would
    take that refusal away from both of them and redden nothing.
    """
    roster = ["alice"]

    assert reg.is_active_member({"status": "provisioning", "members": roster}, "alice") is False
    assert reg.is_active_member({"status": "deleting", "members": roster}, "alice") is False
    assert reg.is_active_member({"status": "failed", "members": roster}, "alice") is False
    assert reg.may_receive_share({"status": "deleting", "owner": "alice"}) is False


def test_a_list_roster_still_authorizes_exactly_its_members():
    """The positive control: the tightening refuses the wrong shape, not the right one."""
    record = _active(members=["alice", "bob"])

    assert reg.is_active_member(record, "alice") is True
    assert reg.is_active_member(record, "bob") is True
    assert reg.is_active_member(record, "ali") is False
    assert reg.is_active_member(record, "carol") is False


def test_an_owner_that_is_not_a_string_is_not_an_owner():
    """``may_receive_share`` tested the owner's truthiness, which a dict or a list satisfies."""
    roster = ["alice"]

    assert reg.may_receive_share(_active(owner={"username": "alice"}, members=roster)) is False
    assert reg.may_receive_share(_active(owner=["alice"], members=roster)) is False
    assert reg.may_receive_share(_active(owner="", members=roster)) is False
    assert reg.may_receive_share(_active(owner="alice", members=roster)) is True


@pytest.mark.parametrize("record", [None, "shared-space", ["alice"], 0], ids=str)
def test_a_record_that_is_not_a_dict_answers_false_rather_than_raising(record):
    """The status is read before the roster is, so a non-dict record never reaches a ``.get``."""
    assert reg.is_active_member(record, "alice") is False
    assert reg.may_receive_share(record) is False


class _NoSuchKey(Exception):
    """The missing-object error an S3 client names on its ``exceptions`` attribute."""


class _Body:
    """An object body that arrives at once, or not until the test lets it."""

    def __init__(self, data, released=None):
        self.data = data
        self.released = released

    def read(self):
        if self.released is not None:
            self.released.wait(5)
        return self.data


class _S3:
    """An admin bucket holding registry records, which answers a GET at once."""

    exceptions = type("exceptions", (), {"NoSuchKey": _NoSuchKey})

    def __init__(self, records, released=None):
        self.records = records
        self.released = released

    def get_object(self, Bucket, Key):
        name = Key.removeprefix("shared-spaces/").removesuffix(".json")
        if name not in self.records:
            raise _NoSuchKey(Key)
        return {"Body": _Body(json.dumps(self.records[name]).encode(), self.released)}


class _Refusing:
    """The default client, which the owner lookup must never reach."""

    def __getattr__(self, name):
        raise AssertionError(f"the owner lookup called {name} on the default client")


@pytest.mark.parametrize(
    ("records", "owner"),
    [({"finance": _active(owner="bob")}, "bob"), ({}, "")],
    ids=["registered", "unregistered"],
)
def test_the_owner_lookup_reads_on_the_bounded_client(monkeypatch, records, owner):
    monkeypatch.setattr(clients, "_s3", _Refusing())
    monkeypatch.setattr(clients, "_s3_bounded", _S3(records))

    assert reg.owner_of("finance", budget.Budget(5, "the owner lookup")) == owner


def test_an_owner_lookup_whose_body_never_arrives_is_abandoned_at_the_cap(monkeypatch):
    """The body streams after the GET returns, so a lookup that capped only the GET would still
    wait out a stalled read of it."""
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    released = threading.Event()
    monkeypatch.setattr(clients, "_s3_bounded", _S3({"finance": _active(owner="bob")}, released))

    try:
        with pytest.raises(TimeoutError, match="ran past"):
            reg.owner_of("finance", budget.Budget(5, "the owner lookup"))
    finally:
        released.set()


def test_the_owner_lookups_client_is_built_on_the_callers_thread(monkeypatch):
    """Only the read goes to the worker: built there, a cold container would spend the cap
    importing boto3, and two workers still running could build from the default session at once."""
    built_on = []

    def _build():
        built_on.append(threading.current_thread())
        return _S3({"finance": _active(owner="bob")})

    monkeypatch.setattr(clients, "s3_bounded", _build)

    assert reg.owner_of("finance", budget.Budget(5, "the owner lookup")) == "bob"
    assert built_on == [threading.current_thread()]

