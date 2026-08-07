"""Tests for cpcommon.messages + cpcommon.errors raise-time validation (SPEC-107 FR-005)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import messages
from cpcommon.errors import TerminalError


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


# ── The whole sentence, not only its tail (SPEC-156 FR-002) ──────────────────


def test_prefix_and_body_compose_one_sentence():
    resolver = messages.register({"boom": "the widget broke."}, prefix="Couldn't fizz: ")
    assert resolver.message("boom") == "Couldn't fizz: the widget broke."


def test_a_resolver_with_no_prefix_renders_the_body_alone():
    """The default must stay the pre-SPEC-156 behaviour, because two planes resolve through
    ``body`` directly and neither wants a sentence built for them."""
    resolver = messages.register({"boom": "the widget broke."})
    assert resolver.message("boom") == "the widget broke."


def test_access_denied_short_circuits_to_a_clause_naming_no_resource():
    resolver = messages.register(
        {"boom": "the widget broke."},
        prefix='Couldn\'t fizz "{name}": ',
        access_denied="You don't have access to fizz.",
    )
    for reason in (messages.UNAUTHORIZED, messages.FORBIDDEN):
        rendered = resolver.message(reason, name="secret-thing")
        assert rendered == "You don't have access to fizz."
        assert "secret-thing" not in rendered


def test_the_access_denied_clause_is_marker_substituted_like_a_body():
    """Table-builder's verb varies per request and REACHES this clause: a create-only line
    would tell a user they can't create a table they were trying to refresh."""
    resolver = messages.register(
        {"boom": "the widget broke."},
        access_denied="You don't have access to {verb} a widget here.",
    )
    assert resolver.message(messages.FORBIDDEN, verb="refresh") == (
        "You don't have access to refresh a widget here."
    )


def test_without_an_access_denied_clause_a_denied_reason_takes_the_ordinary_path():
    resolver = messages.register({"boom": "the widget broke."}, prefix="Couldn't fizz: ")
    assert resolver.message(messages.FORBIDDEN) == (
        f"Couldn't fizz: {messages.BASE_MESSAGES[messages.FORBIDDEN]}"
    )


def test_a_domain_may_keep_a_shorter_unknown_reason_fallback():
    """Two planes fell back to "something went wrong." where the base table says
    "something went wrong. Please try again." — byte-identity is this move's criterion, so
    the difference is a parameter rather than a shrug."""
    resolver = messages.register({"boom": "the widget broke."}, fallback="something went wrong.")
    assert resolver.body("a_code_nobody_registered") == "something went wrong."


def test_an_unfilled_declared_marker_is_blanked_when_the_domain_asks_for_it():
    """A missing token must leave a sentence rather than a literal brace group on screen."""
    resolver = messages.register({"boom": "removed: {removed}."}, blank_unfilled=True)
    assert resolver.body("boom") == "removed: ."


def test_an_unfilled_marker_survives_for_a_domain_that_did_not_ask():
    """The opposite default, pinned: data-quality documents that an unfilled marker survives
    verbatim, so its emitters are forced to pass the tokens the reason takes."""
    resolver = messages.register({"boom": "removed: {removed}."})
    assert resolver.body("boom") == "removed: {removed}."


def test_marker_discovery_matches_a_camel_case_marker():
    """An earlier version of this regex matched `[a-z_]+` only, so a `{removedCount}` would
    have shipped raw — and the surrounding code is camelCase throughout."""
    resolver = messages.register({"boom": "{removedCount} gone, {plain} too."}, blank_unfilled=True)
    assert resolver.markers == frozenset({"removedCount", "plain"})


def test_template_reports_the_base_table_for_a_code_the_domain_does_not_define():
    resolver = messages.register({"boom": "the widget broke."})
    assert resolver.template("boom") == "the widget broke."
    assert resolver.template(messages.MALFORMED_EVENT) == messages.BASE_MESSAGES[messages.MALFORMED_EVENT]
    assert resolver.template("a_code_nobody_registered") == messages.BASE_MESSAGES[messages.UNEXPECTED_ERROR]


def test_a_domain_table_edited_after_registration_resolves_through_the_edit():
    """The table is held by reference, not copied — which is what lets a domain's own tests
    probe their wording without rebuilding the resolver."""
    table = {"boom": "the widget broke."}
    resolver = messages.register(table)
    table["probe"] = "a probe body."
    assert resolver.body("probe") == "a probe body."


def test_terminal_error_accepts_a_known_reason():
    err = TerminalError(messages.UNAUTHORIZED, "nope")
    assert err.reason == "unauthorized"


def test_terminal_error_rejects_an_unknown_reason_at_raise_time():
    with pytest.raises(ValueError):
        TerminalError("this_reason_was_never_registered_qqq", "detail")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
