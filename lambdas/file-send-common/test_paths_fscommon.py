"""Containment is the one place on this plane where a bug is a cross-tenant read.

FR-003 requires the rule to be TWO rules with a test each, because either alone leaves a hole.
These are those tests at the module level; the verb's own suite exercises the same rules
through the real handler.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

from cpcommon.errors import TerminalError
from fscommon import paths


def _refused(root, key):
    with pytest.raises(TerminalError) as caught:
        paths.assert_inside_root(root, key)
    return caught.value.reason


# ── Rule (a): the trailing-slash-normalised root ─────────────────────────────


def test_a_key_inside_the_root_passes():
    assert paths.assert_inside_root("alice/", "alice/reports/q1.csv") == "alice/reports/q1.csv"


def test_a_root_without_its_trailing_slash_is_normalised():
    assert paths.assert_inside_root("alice", "alice/q1.csv") == "alice/q1.csv"


def test_a_sibling_prefix_is_refused():
    """THE alice2/ CASE. A raw `key.startswith("alice")` accepts this, and nothing about the
    two usernames has to be related for one to be a prefix of the other."""
    assert _refused("alice", "alice2/secrets.csv") == "forbidden"


def test_a_sibling_prefix_is_refused_even_when_the_root_carries_its_slash():
    assert _refused("alice/", "alice2/secrets.csv") == "forbidden"


def test_an_unrelated_key_is_refused():
    assert _refused("alice/", "bob/secrets.csv") == "forbidden"


def test_an_empty_root_refuses_rather_than_matching_everything():
    """The dangerous degenerate case: an empty prefix makes every key in the bucket "inside"
    it, so this fails closed rather than normalising to ""."""
    assert _refused("", "bob/secrets.csv") == "forbidden"
    assert _refused("/", "bob/secrets.csv") == "forbidden"


# ── Rule (b): dot segments ───────────────────────────────────────────────────


def test_a_parent_segment_is_refused_despite_starting_with_the_root():
    """`"alice/../bob/secrets.csv".startswith("alice/")` is True. Normalisation does nothing
    about dot segments, which is why this is a separate rule and not a nicety."""
    assert _refused("alice/", "alice/../bob/secrets.csv") == "forbidden"


def test_a_current_segment_is_refused():
    assert _refused("alice/", "alice/./q1.csv") == "forbidden"


def test_a_trailing_parent_segment_is_refused():
    assert _refused("alice/", "alice/reports/..") == "forbidden"


@pytest.mark.parametrize("name", ["..hidden.csv", "q1..csv", "...", "a.b.c"])
def test_a_dot_inside_a_name_is_not_a_dot_segment(name):
    """The rule is about SEGMENTS, and getting that wrong would refuse ordinary user files.
    `...` is a legal S3 object name and is not `..`."""
    key = f"alice/{name}"

    assert paths.assert_inside_root("alice/", key) == key


def test_has_dot_segment_is_exposed_and_agrees():
    assert paths.has_dot_segment("alice/../bob") is True
    assert paths.has_dot_segment("alice/..hidden") is False


# ── Shape ────────────────────────────────────────────────────────────────────


def test_a_missing_key_is_refused():
    assert _refused("alice/", "") == "forbidden"
    assert _refused("alice/", None) == "forbidden"
