"""The authorizer's roster reads, pinned against a ``members`` that is not a list.

``actor in members`` is a membership test only while ``members`` is a list. Against a string
Python matches substrings and against a dict it matches keys, so a record carrying
``"members": "alice,bob"`` would answer True for ``ali`` and for ``lic``. Three questions in this
module are decided that way — leaving a space, acknowledging membership, and naming the target of
an ownership transfer — and all three fail OPEN: each is written as a refusal of a non-member, so
a substring that satisfies the ``in`` skips the refusal and the action proceeds.

Nothing writes a roster that shape today; this plane is the registry's only writer and always
writes a list. What makes it worth pinning is that a membership test which reads as one and
behaves as a prefix match is indistinguishable from a correct one at the call site.

Every refusal below is paired with a list-shaped positive control naming the SAME actor, so an
authorizer tightened into refusing everybody would not satisfy them.
"""

import auth
import pytest

_OWNER = "owner_of_space"


def _record(members, **overrides):
    """Builds a live registry record carrying the given roster.

    Args:
      members: The value to store under ``members``, list-shaped or not.
      **overrides: Record fields to replace.

    Returns:
      The record.

    Raises:
      None.
    """
    return {"status": "active", "owner": _OWNER, "members": members, **overrides}


@pytest.mark.parametrize("action", ["leave", "acknowledge_membership"])
def test_a_string_roster_does_not_admit_a_substring_of_itself(action):
    """Both member-only actions refuse a name that is merely a substring of the roster."""
    record = _record("alice,bob")

    with pytest.raises(auth.AuthorizationError):
        auth.authorize(action, "finance", "ali", record)


@pytest.mark.parametrize("action", ["leave", "acknowledge_membership"])
def test_a_list_roster_still_admits_its_own_members(action):
    """The positive control: the tightening refuses the wrong shape, not the right one."""
    assert auth.authorize(action, "finance", "alice", _record(["alice", "bob"])) is None


@pytest.mark.parametrize("action", ["leave", "acknowledge_membership"])
def test_a_well_formed_roster_still_refuses_somebody_who_is_not_on_it(action):
    """The membership test itself, which every case above leaves free to be deleted.

    Each refusal here is asserted against a MALFORMED roster, so an authorizer that had stopped
    comparing the actor at all — testing only that the roster is non-empty — would satisfy every
    one of them. This is the case that names a stranger against a roster of exactly the right
    shape, so the comparison has to survive for the file to pass.
    """
    with pytest.raises(auth.AuthorizationError):
        auth.authorize(action, "finance", "mallory", _record(["alice", "bob"]))


@pytest.mark.parametrize(
    "members", ["alice", {"alice": "active"}, 42], ids=["string", "dict", "scalar"]
)
def test_no_roster_shape_but_a_list_admits_a_member_action(members):
    """The member-only actions get the dict and scalar shapes too, not just the string."""
    with pytest.raises(auth.AuthorizationError):
        auth.authorize("leave", "finance", "alice", _record(members))


def test_a_transfer_target_that_is_only_a_substring_of_the_roster_is_refused():
    """Ownership is the costliest thing this module hands out, so it gets its own case."""
    record = _record("alice,bob")

    assert auth.transfer_refusal(_OWNER, "finance", "ali", record)[0] == "TransferTargetNotMember"
    assert auth.transfer_refusal(_OWNER, "finance", "alice", record)[0] == "TransferTargetNotMember"


def test_a_transfer_to_a_real_member_still_proceeds():
    """The positive control for the transfer path, including a member who has not acknowledged."""
    record = _record(["alice", "bob"])

    assert auth.transfer_refusal(_OWNER, "finance", "alice", record) is None
    assert auth.transfer_refusal(_OWNER, "finance", "bob", record) is None


@pytest.mark.parametrize("members", ["alice", {"alice": "active"}, 42], ids=["string", "dict", "scalar"])
def test_no_roster_shape_but_a_list_admits_anybody(members):
    """A dict roster matches its keys and a scalar raises out of a bare ``in``; both refuse now.

    The CODE is asserted, not merely that something was refused: the neighbouring conditions in
    this function return their own codes for a record that is emptied or not active, and a bare
    "it refused" would pass against a predicate that had started taking one of those instead.
    """
    refusal = auth.transfer_refusal(_OWNER, "finance", "alice", _record(members))

    assert refusal[0] == "TransferTargetNotMember"


@pytest.mark.parametrize("registry", ["finance", ["alice"], 0], ids=str)
def test_a_record_that_is_not_a_dict_refuses_rather_than_raising(registry):
    """A malformed control object is an unknown space, not an ``AttributeError`` mid-decision."""
    assert auth.transfer_refusal(_OWNER, "finance", "alice", registry)[0] == "TransferSpaceUnknown"
    assert auth.member_refusal(_OWNER, "finance", "add_members", ["x"], registry)[0] == "MemberSpaceUnknown"
    with pytest.raises(auth.AuthorizationError):
        auth.authorize("leave", "finance", "alice", registry)
