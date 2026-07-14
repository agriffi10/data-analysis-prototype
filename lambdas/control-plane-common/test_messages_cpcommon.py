"""Tests for cpcommon.messages + cpcommon.errors raise-time validation (SPEC-107 FR-005)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest  # noqa: E402

from cpcommon import messages  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402


def test_base_codes_are_known():
    for code in (messages.UNAUTHORIZED, messages.FORBIDDEN, messages.MALFORMED_EVENT, messages.UNEXPECTED_ERROR):
        assert messages.is_known_reason(code)


def test_unregistered_code_is_not_known():
    assert messages.is_known_reason("definitely_not_a_registered_reason_zzz") is False


def test_register_builds_a_resolver_and_marks_codes_known():
    resolver = messages.register({"widget_broke": "the widget broke."})
    assert messages.is_known_reason("widget_broke")
    assert resolver.body("widget_broke") == "the widget broke."


def test_resolver_falls_back_to_unexpected_without_leaking_the_code():
    resolver = messages.register({"some_reason": "a thing happened."})
    msg = resolver.body("a_code_not_in_this_resolver")
    assert "a_code_not_in_this_resolver" not in msg
    assert msg == messages.BASE_MESSAGES[messages.UNEXPECTED_ERROR]


def test_resolver_substitutes_named_tokens_with_str_replace():
    resolver = messages.register({"named": 'exists in "{database}".'})
    assert resolver.body("named", database="sales") == 'exists in "sales".'


def test_resolver_literal_brace_in_value_does_not_raise():
    # A table/db name containing a brace must not blow up substitution (never str.format).
    resolver = messages.register({"braced": 'name is "{name}".'})
    assert resolver.body("braced", name="weird{x}name") == 'name is "weird{x}name".'


def test_register_rejects_redefining_a_base_code():
    with pytest.raises(ValueError):
        messages.register({messages.UNAUTHORIZED: "different wording"})


def test_two_domains_may_register_the_same_code_without_colliding():
    # tbcommon and tscommon both define invalid_table_name with different wording — the
    # per-domain resolvers keep them separate; only the code's validity is global.
    a = messages.register({"shared_code_probe": "domain A wording."})
    b = messages.register({"shared_code_probe": "domain B wording."})
    assert a.body("shared_code_probe") == "domain A wording."
    assert b.body("shared_code_probe") == "domain B wording."


def test_terminal_error_accepts_a_known_reason():
    err = TerminalError(messages.UNAUTHORIZED, "nope")
    assert err.reason == "unauthorized"


def test_terminal_error_rejects_an_unknown_reason_at_raise_time():
    with pytest.raises(ValueError):
        TerminalError("this_reason_was_never_registered_qqq", "detail")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
