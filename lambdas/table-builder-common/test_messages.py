"""Unit tests for the table-builder notification message map.

Pure functions — no AWS. Runnable under pytest or directly: python3 test_messages.py.
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tbcommon import messages


def test_access_denied_reasons_share_one_message_and_hide_the_name():
    for reason in ("unauthorized", "forbidden"):
        msg = messages.failure_message(reason, table_name="orders", database="sales")
        assert msg == "You don't have access to create a table here."
        assert "orders" not in msg


def test_invalid_table_name_names_the_table():
    msg = messages.failure_message("invalid_table_name", table_name="Bad Name")
    assert msg == 'Couldn\'t create table "Bad Name": the name isn\'t a valid table name.'


def test_invalid_partition_keys():
    msg = messages.failure_message("invalid_partition_keys", table_name="orders")
    assert msg.startswith('Couldn\'t create table "orders": the partition keys aren\'t valid')


def test_table_exists_names_the_database():
    msg = messages.failure_message("table_exists", table_name="orders", database="sales")
    assert msg == 'Couldn\'t create table "orders": a table with that name already exists in "sales".'


def test_inspect_reasons():
    cases = {
        "no_data_files": "no supported data files were found in that folder.",
        "mixed_formats": "the folder mixes file formats - use a single format.",
        "unsupported_format": "that file format isn't supported (use Parquet, CSV, or JSON).",
        "unexpected_partitioning": "the folder is partitioned but no partition keys were provided.",
        "partition_layout_mismatch": "the partition keys don't match the folder layout (check names and order).",
    }
    for reason, tail in cases.items():
        assert messages.failure_message(reason, table_name="orders") == f'Couldn\'t create table "orders": {tail}'


def test_schema_reasons_share_the_read_message():
    for reason in ("schema_inference_failed", "unmappable_type"):
        msg = messages.failure_message(reason, table_name="orders")
        assert msg == 'Couldn\'t create table "orders": the data schema couldn\'t be read.'


def test_ddl_failure_carries_no_raw_detail():
    # SPEC-106 FR-008: the DDL-failure bodies never interpolate the raw Athena reason.
    expected = 'Couldn\'t create table "orders": creating the table failed. Please try again or contact the Administrator.'
    assert messages.failure_message("ddl_execution_failed", table_name="orders") == expected
    assert messages.failure_message("ddl_timeout", table_name="orders") == expected


def test_unknown_reason_falls_back_without_leaking_the_code():
    msg = messages.failure_message("some_new_reason", table_name="orders")
    assert "some_new_reason" not in msg
    assert msg.startswith('Couldn\'t create table "orders":')


def test_missing_table_name_uses_a_placeholder():
    assert 'your table' in messages.failure_message("no_data_files", table_name="")


def test_malformed_event_reason_has_friendly_text():
    msg = messages.failure_message("malformed_event", table_name="orders")
    assert msg == 'Couldn\'t create table "orders": the request was malformed. Please try again.'


def test_literal_brace_in_body_does_not_raise():
    """SPEC-083 FR-005: a reason body containing a literal brace must not blow up the
    placeholder substitution (it no longer uses str.format)."""
    messages._BODIES["_brace_probe"] = "weird {not_a_placeholder} body."  # test-only
    try:
        msg = messages.failure_message("_brace_probe", table_name="orders")
        assert msg == 'Couldn\'t create table "orders": weird {not_a_placeholder} body.'
    finally:
        messages._BODIES.pop("_brace_probe", None)


def test_success_message():
    assert messages.success_message("orders", "sales") == 'Table "orders" is ready to query in "sales".'


# ── The refresh vocabulary (SPEC-144 FR-009) ─────────────────────────────────

#: Every failure message this layer rendered BEFORE SPEC-144, captured verbatim — the 14
#: pre-SPEC-143 create reasons AND the 12 SPEC-143 refresh reasons, which also shipped and
#: also render today. The gate for the whole message-layer change: `mode` and `tokens` are
#: additive, so a message that moved by one character is a regression. Deliberately a
#: literal table rather than a loop over `_BODIES` — generating the expectations from the
#: thing under test would assert nothing.
_CREATE_MESSAGES = {
    "invalid_table_name": 'Couldn\'t create table "sales": the name isn\'t a valid table name.',
    "invalid_partition_keys": 'Couldn\'t create table "sales": the partition keys aren\'t valid (check names, types, and ranges).',
    "table_exists": 'Couldn\'t create table "sales": a table with that name already exists in "alice".',
    "no_data_files": 'Couldn\'t create table "sales": no supported data files were found in that folder.',
    "mixed_formats": 'Couldn\'t create table "sales": the folder mixes file formats - use a single format.',
    "unsupported_format": 'Couldn\'t create table "sales": that file format isn\'t supported (use Parquet, CSV, or JSON).',
    "unexpected_partitioning": 'Couldn\'t create table "sales": the folder is partitioned but no partition keys were provided.',
    "partition_layout_mismatch": 'Couldn\'t create table "sales": the partition keys don\'t match the folder layout (check names and order).',
    "schema_inference_failed": 'Couldn\'t create table "sales": the data schema couldn\'t be read.',
    "unmappable_type": 'Couldn\'t create table "sales": the data schema couldn\'t be read.',
    "ddl_execution_failed": 'Couldn\'t create table "sales": creating the table failed. Please try again or contact the Administrator.',
    "ddl_timeout": 'Couldn\'t create table "sales": creating the table failed. Please try again or contact the Administrator.',
    "malformed_event": 'Couldn\'t create table "sales": the request was malformed. Please try again.',
    "unexpected_error": 'Couldn\'t create table "sales": something went wrong. Please try again.',
    # Shipped by SPEC-143, rendered under the create prefix until this spec gave them a
    # mode. Pinned here so the prefix change is the ONLY thing that moved.
    "invalid_mode": 'Couldn\'t create table "sales": the request was malformed. Please try again.',
    "partition_keys_not_refreshable": 'Couldn\'t create table "sales": a refresh keeps the table\'s existing partition keys - to change them, drop the table and build it again.',
    "table_not_found": 'Couldn\'t create table "sales": no table named that exists in "alice".',
    "cannot_refresh_view": 'Couldn\'t create table "sales": a view has no data files to re-read.',
    "cannot_refresh_managed_table": 'Couldn\'t create table "sales": only tables the portal created over files in your space can be refreshed.',
    "cannot_refresh_catalog_partitioned": 'Couldn\'t create table "sales": tables with catalog-registered partitions can\'t be refreshed.',
    "cannot_refresh_location_unsupported": 'Couldn\'t create table "sales": that table\'s data location isn\'t one this portal can read.',
    "table_outside_space": 'Couldn\'t create table "sales": that table\'s data is outside the space you\'re refreshing it from.',
    "projection_not_reconstructable": 'Couldn\'t create table "sales": that table\'s partition settings can\'t be read back - drop the table and build it again to change them.',
    "definition_too_large": 'Couldn\'t create table "sales": that table has too many columns to refresh.',
    "format_changed": 'Couldn\'t create table "sales": the folder\'s file format no longer matches the table\'s - build a new table instead.',
    # Shipped by SPEC-144. They were exempt from the gate while that spec was the current one
    # and stayed exempt afterwards — which left two live bodies pinned by nothing, the exact
    # drift this table exists to stop. `columns_removed` renders its {removed} marker EMPTY
    # with no tokens, and that is the behaviour being pinned: an unfilled marker must leave a
    # sentence rather than a literal "{removed}" on the user's screen.
    "columns_removed": 'Couldn\'t create table "sales": these columns are no longer in the data and would be removed: . Nothing was changed - refresh again and confirm the removal to apply it.',
    "removals_flag_not_applicable": 'Couldn\'t create table "sales": the request was malformed. Please try again.',
    # Shipped by SPEC-149, exempt while that spec was current. SPEC-156 is the next one, so
    # it moves in — and it matters more than most: this is the spec whose SOLE acceptance
    # criterion is byte-identity, and this was the one body it could not have checked.
    "update_failed": 'Couldn\'t create table "sales": the table couldn\'t be updated. Nothing was changed. Please try again or contact the Administrator.',
    # Shipped by SPEC-157. Pinned on arrival rather than exempted: the two exemptions above each
    # left a live body checked by nothing for a whole spec, and the wording matters here — this
    # is the sentence a user sees when their refresh did NOTHING, so "nothing was changed" is
    # load-bearing and must not drift into sounding like a failure they need to act on.
    "table_changed_during_refresh": 'Couldn\'t create table "sales": the table was changed by something else while this refresh was running. Nothing was changed - refresh again to pick up both sets of changes.',
    "refresh_already_running": 'Couldn\'t create table "sales": a refresh of that table is already running. Nothing was changed - wait for it to finish, then check whether you still need to refresh again.',
}

#: Bodies whose reason moved to cpcommon's base table (SPEC-156 FR-002). They still render —
#: through `BASE_MESSAGES` — so the expectations above stay, but `_BODIES` no longer holds
#: them and the coverage guard below must not demand that it does.
_MOVED_TO_THE_BASE_TABLE = {"malformed_event", "unexpected_error"}


def test_the_gate_covers_every_body_that_shipped_before_this_spec():
    """Guards the table above against silently shrinking: a body added without an
    expectation would otherwise be pinned by nothing, which is how the 12 SPEC-143 reasons
    came to be uncovered in the first place.

    THE EXEMPTION MUST SHRINK TO ONE ENTRY EVERY TIME, and the reason is that this set is
    where the drift hides: SPEC-144's three bodies were exempted while 144 was current and
    two of them were still exempt a spec later, pinned by nothing at all. A body is new for
    exactly one spec — when the next one lands, move it into the table above.

    SPEC-156 emptied the exemption: `update_failed` was SPEC-149's and had stayed exempt
    through the one spec whose sole acceptance criterion is byte-identity.
    """
    new_in_this_spec: set[str] = set()
    uncovered = set(messages._BODIES) - set(_CREATE_MESSAGES) - new_in_this_spec

    assert not uncovered, f"bodies with no byte-for-byte expectation: {sorted(uncovered)}"
    assert not new_in_this_spec, "the exemption is empty — a new body goes straight into the table"


def test_the_gate_still_covers_the_reasons_that_moved_to_the_base_table():
    """The other direction: SPEC-156 removed two reasons from `_BODIES`, and a coverage guard
    that only walks `_BODIES` would silently stop caring about them. They still render, so
    they are still pinned."""
    for reason in _MOVED_TO_THE_BASE_TABLE:
        assert reason not in messages._BODIES, f"{reason} came back into the domain table"
        assert reason in _CREATE_MESSAGES, f"{reason} lost its byte-for-byte expectation"


def test_every_pre_existing_failure_message_is_byte_for_byte_unchanged():
    for reason, expected in _CREATE_MESSAGES.items():
        assert messages.failure_message(reason, "sales", "alice") == expected, reason


def test_a_body_with_no_token_markers_is_unaffected_by_the_tokens_channel():
    """The additive claim, asserted rather than assumed: passing tokens to a body that
    references none must render identically to passing none.

    The marker-carrying bodies are excluded BY DETECTION rather than by name, so a body that
    gains a marker later leaves this loop automatically instead of failing it — and a body
    that loses one rejoins. `columns_removed` is the only one today.

    Detection reads the resolver rather than `_BODIES` because SPEC-156 moved two reasons
    (`malformed_event`, `unexpected_error`) out of this layer's table and onto cpcommon's
    base one — a lookup in `_BODIES` alone would now KeyError on a reason that still renders.
    """
    for reason, expected in _CREATE_MESSAGES.items():
        if re.search(r"\{[^{}]*\}", messages.resolver.template(reason)):
            continue
        with_tokens = messages.failure_message(
            reason, "sales", "alice", "create", {"removed": "a, b", "unused": "x"}
        )
        assert with_tokens == expected, reason


def test_the_prefix_follows_the_mode():
    created = messages.failure_message("no_data_files", "sales", "alice", "create")
    refreshed = messages.failure_message("no_data_files", "sales", "alice", "refresh")

    assert created.startswith('Couldn\'t create table "sales":')
    assert refreshed.startswith('Couldn\'t refresh table "sales":')
    # Only the verb differs — the body is the same sentence.
    assert created.split(":", 1)[1] == refreshed.split(":", 1)[1]


def test_access_denied_is_mode_aware_too():
    """The short-circuit runs BEFORE the prefix is chosen, so it needs its own branch.

    `forbidden` is the ORDINARY outcome of refreshing from a stale schema rail — the table
    was dropped, or the space membership changed — so a create-only line would tell a user
    they can't create a table they were trying to refresh.
    """
    for reason in ("unauthorized", "forbidden"):
        assert messages.failure_message(reason, "sales", "alice", "create") == (
            "You don't have access to create a table here."
        )
        assert messages.failure_message(reason, "sales", "alice", "refresh") == (
            "You don't have access to refresh a table here."
        )


def test_columns_removed_names_the_columns_and_says_nothing_changed():
    msg = messages.failure_message(
        "columns_removed", "sales", "alice", "refresh", {"removed": "legacy_id, old_total"}
    )

    assert "legacy_id, old_total" in msg
    assert "Nothing was changed" in msg
    assert msg.startswith('Couldn\'t refresh table "sales":')


def test_an_unfilled_token_marker_renders_empty_rather_than_literally():
    """A missing token must not leave `{removed}` on screen — the body is still a sentence."""
    msg = messages.failure_message("columns_removed", "sales", "alice", "refresh")

    assert "{removed}" not in msg


def test_update_failed_says_nothing_was_changed():
    """SPEC-149. The apply is one in-place update, so a failure leaves the table exactly as
    it was — and the wording can say so plainly, which SPEC-144's could not."""
    assert "Nothing was changed" in messages.failure_message("update_failed", "sales", "alice", "refresh")


def test_the_removed_rebuild_reasons_are_gone_from_the_code_not_merely_unused():
    """SPEC-149 FR-007. A reason nobody raises but everybody can still find is worse than one
    that was deleted: the next reader treats it as a state the system can reach.

    Scoped to `lambdas/` and `infra/` — the SPEC-144 spec and delivery docs are the historical
    record of a mechanism that really did ship, and must keep saying so.

    The needles are ASSEMBLED rather than written out, so this file does not become the one
    hit its own grep reports.
    """
    import pathlib

    needles = [stem + "_failed" for stem in ("drop", "recreate")]
    root = pathlib.Path(__file__).resolve().parent.parent.parent
    offenders = []
    for tree in ("lambdas", "infra"):
        for path in (root / tree).rglob("*"):
            if path.suffix not in (".py", ".tf", ".tftpl", ".json") or "__pycache__" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            if any(needle in text for needle in needles):
                offenders.append(str(path.relative_to(root)))

    assert not offenders, f"SPEC-144's removed reason codes still present in: {offenders}"


def test_success_message_still_defaults_to_the_created_wording():
    assert messages.success_message("sales", "alice") == 'Table "sales" is ready to query in "alice".'


def test_the_unchanged_outcome_reads_differently_from_a_refresh_that_changed_something():
    """FR-002 AC4 — a refresh that found nothing must not look like one that did work, or a
    user concludes the button is broken."""
    unchanged = messages.success_message("sales", "alice", "unchanged")
    refreshed = messages.success_message("sales", "alice", "refreshed", added=1)

    assert "no schema changes were found" in unchanged
    assert unchanged != refreshed


def test_the_refreshed_message_names_the_counts_and_pluralises():
    one = messages.success_message("sales", "alice", "refreshed", added=1)
    many = messages.success_message("sales", "alice", "refreshed", added=2, retyped=1, removed=3)

    assert "1 column added" in one
    assert "2 columns added" in many and "1 column retyped" in many and "3 columns removed" in many


def test_a_refresh_that_changed_something_uncounted_still_reads_as_a_sentence():
    """Defensive: the counts come from a diff, and a caller that passes none must not
    produce 'was refreshed in "alice": .'"""
    assert messages.success_message("sales", "alice", "refreshed") == (
        'Table "sales" was refreshed in "alice": schema updated.'
    )


def test_every_marker_any_body_declares_is_discovered():
    """The discovery regex decides what gets blanked when a token is absent, and a marker
    it misses is rendered LITERALLY to a user. An earlier version matched `[a-z_]+` only —
    so a `{removedCount}` would have shipped raw, and the surrounding code is camelCase
    throughout. Asserted against the wording rather than against the pattern.

    SPEC-156 widened discovery from the bodies to the bodies PLUS the prefix and
    access-denied templates, so the containment is one-way now: every body marker must be
    discovered, and the prefix's own two must be as well.
    """
    import re

    declared = set(re.findall(r"\{([^{}]*)\}", " ".join(messages._BODIES.values())))

    assert declared, "the discovery found no markers at all — the pattern has gone stale"
    assert declared <= set(messages._MARKERS), sorted(declared - set(messages._MARKERS))
    assert {"verb", "name"} <= set(messages._MARKERS), "the prefix's markers went undiscovered"


def test_a_token_cannot_shadow_the_database():
    """Tokens come from a raise site and the database from this layer's own caller; the
    trusted value must win, not the payload."""
    msg = messages.failure_message(
        "table_exists", "sales", "alice", "create", {"database": "SPOOFED"}
    )

    assert "alice" in msg and "SPOOFED" not in msg


def test_removed_tokens_caps_the_display_and_keeps_the_names_exact():
    tokens = messages.removed_tokens(["a", "b"])

    assert tokens["removed"] == "a, b"
    assert json.loads(tokens["removedNames"]) == ["a", "b"]

    many = messages.removed_tokens([f"c{i}" for i in range(25)])
    assert many["removed"].endswith(", and 5 more")
    assert len(json.loads(many["removedNames"])) == messages.MAX_NAMED_COLUMNS


def test_removed_tokens_survives_a_name_containing_the_display_separator():
    """The reason the link reads `removedNames` rather than re-splitting `removed`: a
    column literally called `a, b` is indistinguishable from two columns once joined."""
    tokens = messages.removed_tokens(["a, b"])

    assert json.loads(tokens["removedNames"]) == ["a, b"]


def test_every_new_reason_is_a_registered_terminal_reason():
    """A body nobody registered is a body TerminalError refuses to raise — the failure
    lands as a ValueError inside the constructor, not as the reason it names."""
    from cpcommon import messages as cpmessages

    for reason in ("columns_removed", "update_failed", "removals_flag_not_applicable"):
        assert cpmessages.is_known_reason(reason), reason


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
