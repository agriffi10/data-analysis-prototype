"""Tests for the notification primitives cpcommon owns (SPEC-156 FR-002).

The sender and the failure decorator are exercised through each plane's own notify tests;
what is asserted here is the deduplication token, which two planes had copied verbatim.

Runnable under pytest or directly: python3 test_notify_cpcommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon.notify import dedup_id


def test_the_token_is_the_request_id_and_the_outcome():
    assert dedup_id("r-1", "failure") == "r-1:failure"


def test_no_request_id_falls_back_to_content_based_dedup():
    """None is the honest answer, not an invented id: an invented one would defeat the
    queue's own content-based deduplication rather than replace it."""
    assert dedup_id("", "failure") is None
    assert dedup_id(None, "failure") is None


def test_one_token_per_outcome_not_per_verb():
    """The rule SPEC-114 settled, asserted rather than described. Two paths emit the same
    failure — the verb decorator on its way out, and the notify state after the Catch, which
    cannot know which verb raised. A per-verb token would give them different ids and the
    user would get two notifications for one failure.
    """
    from_the_decorator = dedup_id("r-1", "failure")
    from_the_catch = dedup_id("r-1", "failure")

    assert from_the_decorator == from_the_catch
    assert dedup_id("r-1", "completed") != from_the_decorator


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
