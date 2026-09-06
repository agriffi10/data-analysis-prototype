"""The two roster normalisers, and the opposite directions they are safe in.

``roster`` collapses an unreadable roster into an empty one and ``roster_is_readable`` reports
whether it was readable at all. The pair exists because the collapse has a polarity: a refusal
keyed on the actor NOT being a member fails closed on an empty roster, and one keyed on the actor
BEING a member fails open on the very same value. Both directions live in this plane, so both are
pinned here rather than at the sites, which is where a copy would drift.

``roster`` is also asserted directly against a record that is not a dict. No caller can hand it
one today — every call site checks the record first — so that arm of the guard is reachable only
from here, and without this file it would be a promise the docstring makes and nothing keeps.
"""

import membership
import pytest


@pytest.mark.parametrize(
    "record",
    [
        {"members": "alice,bob"},
        {"members": {"alice": "active"}},
        {"members": 42},
        {"members": None},
        {},
    ],
    ids=["string", "dict", "scalar", "null", "absent"],
)
def test_a_roster_that_is_not_a_list_reads_as_empty_and_as_unreadable(record):
    """Both normalisers agree on every shape a bare ``in`` would have degraded against."""
    assert membership.roster(record) == []
    assert membership.roster_is_readable(record) is False


@pytest.mark.parametrize("record", [None, "finance", ["alice"], 0], ids=str)
def test_a_record_that_is_not_a_dict_reads_as_empty_rather_than_raising(record):
    """The arm no call site can reach, which is exactly why it is asserted here."""
    assert membership.roster(record) == []
    assert membership.roster_is_readable(record) is False


def test_a_list_roster_is_returned_as_it_stands_and_reads_as_readable():
    """The positive control: both normalisers have to distinguish a good roster from a bad one."""
    record = {"members": ["alice", "bob"]}

    assert membership.roster(record) == ["alice", "bob"]
    assert membership.roster_is_readable(record) is True


def test_an_empty_list_roster_is_readable_even_though_it_names_nobody():
    """The distinction the pair exists for: an emptied space is readable, a malformed one is not.

    A space whose roster has been deliberately emptied carries ``[]``, and a caller that refuses
    a MEMBER must let that through — it knows nobody is a member. Collapsing the two would make
    an emptied space indistinguishable from a corrupt one and refuse a legitimate teardown.
    """
    assert membership.roster({"members": []}) == []
    assert membership.roster_is_readable({"members": []}) is True
