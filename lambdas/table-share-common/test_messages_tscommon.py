"""Unit tests for tscommon.messages — the sender-facing failure wording.

Also home to the sweep that keeps a RETIRED phrase out of the fleet (SPEC-161 FR-005). The
scope of that check is all of ``lambdas/``, not this layer, but the phrase it hunts is this
plane's wording and this is the file wording lives in.

Runnable under pytest or directly: python3 test_messages_tscommon.py.
"""

import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ATHENA_WORKGROUP", "test-workgroup")

import pytest
from tscommon import config, messages

#: Any {marker} left in rendered text — the bug this file exists for.
_MARKER = re.compile(r"\{[a-zA-Z_]+\}")


@pytest.mark.parametrize("reason", sorted(messages._BODIES))
def test_no_reason_renders_with_an_unsubstituted_marker(reason):
    """THE BUG THIS CAUGHT, in review, on the way to the user's inbox.

    ``failure_message`` substitutes ONLY {tableName} — it has no **tokens mechanism (the
    dqcommon twin does, which is what a new entry was copied from). A body written with a
    {count} marker therefore shipped the literal characters "{count}" to the sender:

        Couldn't share "db.orders": a share can go to at most 50 recipients ({count} were
        given). Please share to fewer at a time.

    Parametrized over the WHOLE table so the next copied-in marker fails here rather than
    in someone's notifications.
    """
    rendered = messages.failure_message(reason, "db.orders", kind="user", name="bob", table_name="orders_copy")

    assert not _MARKER.search(rendered), f"{reason} rendered with an unsubstituted marker: {rendered}"


def test_the_only_supported_marker_is_actually_substituted():
    """The flip side: {tableName} must not survive either — a guard that only checked for
    leftovers would pass on a body that never used a marker at all."""
    rendered = messages.failure_message("conflict", "db.orders", table_name="orders_copy")

    assert "orders_copy" in rendered
    assert "{tableName}" not in rendered


def test_the_recipient_cap_message_names_the_cap():
    """A limit message that doesn't state the limit makes the user guess."""
    rendered = messages.failure_message("too_many_recipients", "db.orders")

    assert str(config.SHARE_MAX_RECIPIENTS) in rendered


def test_an_unknown_reason_falls_back_without_leaking_the_code():
    rendered = messages.failure_message("some_code_nobody_registered", "db.orders")

    assert "some_code_nobody_registered" not in rendered
    assert rendered


# ── The byte-identity gate for the move onto cpcommon (SPEC-156 FR-002) ──────
#
# Every sentence this layer rendered BEFORE the resolver move, captured by running the
# pre-move implementation rather than by reading it — so the table is evidence, not a
# transcription. The move rebuilt the whole rendering path (a prefix template, an
# access-denied template, a shared body table and a per-domain fallback), and a message
# that shifted by one character is a regression, not a tidy-up.
#
# Two rows carry the whole point of the `fallback=` parameter: `unexpected_error` resolves
# through cpcommon's base table and keeps "Please try again.", while a code nobody
# registered keeps this plane's SHORTER "something went wrong." The two were one line apart
# in the old module and are trivially easy to collapse by accident.

_SENDER_MESSAGES = {
    "a_code_nobody_registered": 'Couldn\'t share "db.orders": something went wrong.',
    "conflict": 'Couldn\'t share "db.orders": a table named "orders_copy" already exists there.',
    "copy_failed": 'Couldn\'t share "db.orders": copying the data failed.',
    "definition_unreadable": 'Couldn\'t share "db.orders": we couldn\'t read the table\'s own definition, so no table was created. Please try again or contact the Administrator.',
    "create_failed": 'Couldn\'t share "db.orders": creating the table failed. Please try again or contact the Administrator.',
    "create_timeout": 'Couldn\'t share "db.orders": creating the table failed. Please try again or contact the Administrator.',
    "forbidden": "You don't have access to share that table.",
    "invalid_recipients": 'Couldn\'t share "db.orders": the recipient list is malformed.',
    "invalid_table_name": 'Couldn\'t share "db.orders": the result name isn\'t a valid table name.',
    "no_recipients": 'Couldn\'t share "db.orders": no recipients were given.',
    "transfer_results_unreadable": 'Couldn\'t share "db.orders": we couldn\'t confirm the copy finished, so the share was stopped. Please try again or contact the Administrator.',
    "source_catalog_partitioned": 'Couldn\'t share "db.orders": tables with catalog-registered partitions can\'t be shared (yet).',
    "source_definition_too_large": 'Couldn\'t share "db.orders": that table has too many columns (or too much column detail) to share. Please share a narrower table.',
    "share_timed_out": 'Couldn\'t share "db.orders": the share ran for too long and was stopped. Some recipients may have received part of the data. Please contact the Administrator before trying again.',
    "source_empty": 'Couldn\'t share "db.orders": the source table has no data files.',
    "source_object_too_large": 'Couldn\'t share "db.orders": one of that table\'s data files is too large to copy. Please contact the Administrator.',
    "too_many_transfer_items": 'Couldn\'t share "db.orders": that\'s too many files to copy to that many recipients at once. Please share to fewer recipients, or share a smaller table.',
    "transfer_too_large": 'Couldn\'t share "db.orders": that\'s too much data to copy to that many recipients at once. Please share to fewer recipients, or share a smaller table.',
    "source_is_view": 'Couldn\'t share "db.orders": views can\'t be shared - only tables with data files.',
    "source_location_unsupported": 'Couldn\'t share "db.orders": the source table\'s data location isn\'t supported.',
    "source_not_external": 'Couldn\'t share "db.orders": only base external tables can be shared.',
    "source_not_found": 'Couldn\'t share "db.orders": the source table doesn\'t exist.',
    "source_not_readable": 'Couldn\'t share "db.orders": the source table couldn\'t be read.',
    "source_too_large": 'Couldn\'t share "db.orders": the source table is too large to share.',
    "target_not_readable": 'Couldn\'t share "db.orders": the recipient\'s database couldn\'t be checked.',
    "too_many_recipients": 'Couldn\'t share "db.orders": a share can go to at most 50 recipients at a time. Please share to fewer.',
    "unauthorized": "You don't have access to share that table.",
    "unexpected_error": 'Couldn\'t share "db.orders": something went wrong. Please try again.',
    "unknown_space": 'Couldn\'t share "db.orders": there is no shared space with that name.',
    "unknown_target": 'Couldn\'t share "db.orders": that recipient isn\'t a valid target.',
    "unknown_user": 'Couldn\'t share "db.orders": there is no user with that name.',
}

#: The per-recipient shape of the same sentence — the clause the prefix template grows when
#: a recipient is bound. Four representative reasons, including the access-denied one, which
#: must NOT name the recipient it was denied for.
_PER_RECIPIENT_MESSAGES = {
    "conflict": 'Couldn\'t share "db.orders" to user "bob": a table named "orders_copy" already exists there.',
    "unknown_user": 'Couldn\'t share "db.orders" to user "bob": there is no user with that name.',
    "unexpected_error": 'Couldn\'t share "db.orders" to user "bob": something went wrong. Please try again.',
    "forbidden": "You don't have access to share that table.",
}


def test_the_gate_covers_every_body_this_layer_declares():
    """Guards the table above against silently shrinking — a body added without an
    expectation would be pinned by nothing at all."""
    uncovered = set(messages._BODIES) - set(_SENDER_MESSAGES)

    assert not uncovered, f"bodies with no byte-for-byte expectation: {sorted(uncovered)}"


@pytest.mark.parametrize("reason", sorted(_SENDER_MESSAGES))
def test_every_sender_message_is_byte_for_byte_unchanged(reason):
    assert messages.failure_message(reason, "db.orders", table_name="orders_copy") == _SENDER_MESSAGES[reason]


@pytest.mark.parametrize("reason", sorted(_PER_RECIPIENT_MESSAGES))
def test_every_per_recipient_message_is_byte_for_byte_unchanged(reason):
    rendered = messages.failure_message(
        reason, "db.orders", kind="user", name="bob", table_name="orders_copy"
    )

    assert rendered == _PER_RECIPIENT_MESSAGES[reason]


def test_the_only_marker_bearing_body_renders_with_no_result_table_name():
    """The gate table always supplies a table name, so the `{tableName}` → "" path it leaves
    uncovered is asserted here. A whole-request failure has no result name yet."""
    assert messages.failure_message("conflict", "db.orders") == (
        'Couldn\'t share "db.orders": a table named "" already exists there.'
    )


def test_a_base_code_this_plane_never_declared_now_reads_what_it_means():
    """SPEC-156 FR-002's ONE enumerated difference, and it was found by rendering every
    reason under every argument combination against both implementations — not by eye.

    `malformed_event` is a cpcommon base code table-share never declared. Before the move it
    fell to this layer's unknown-code fallback and read "something went wrong."; it resolves
    through the base table now and reads what it means. Nobody has seen either wording: this
    plane's only `parse_sqs_request` call raises `unauthorized`, and no other site in the
    tree raises `malformed_event` under a table-share verb. Pinned so a plane that starts
    raising it knows which sentence ships, rather than rediscovering this in an inbox.
    """
    rendered = messages.failure_message("malformed_event", "db.orders")

    assert rendered == 'Couldn\'t share "db.orders": the request was malformed. Please try again.'


# ── The tokens mechanism this layer lacked (SPEC-156 FR-002) ─────────────────


def test_a_raise_sites_tokens_reach_the_body():
    """The gap this FR closed: `TerminalError` has always carried tokens and this layer
    discarded them, so a body needing a value had to bake it into its literal."""
    messages._BODIES["_token_probe"] = "the widget {thing} broke."  # test-only
    try:
        rendered = messages.failure_message("_token_probe", "db.orders", tokens={"thing": "gizmo"})
        assert rendered == 'Couldn\'t share "db.orders": the widget gizmo broke.'
    finally:
        messages._BODIES.pop("_token_probe", None)


def test_the_recipient_cap_comes_from_the_constant_that_enforces_it():
    """The cap is a token now, but a TRUSTED one: it is filled from `config` by this layer,
    so it cannot drift from the value the validate verb checks and a raise site cannot
    misstate it to the user."""
    assert "{max}" in messages._BODIES["too_many_recipients"]

    rendered = messages.failure_message("too_many_recipients", "db.orders", tokens={"max": "9999"})

    assert str(config.SHARE_MAX_RECIPIENTS) in rendered
    assert "9999" not in rendered


def test_a_token_cannot_shadow_the_result_table_name():
    """Same rule one marker over: the table name comes from this layer's caller, the tokens
    from a raise site, and the trusted value must win."""
    rendered = messages.failure_message(
        "conflict", "db.orders", table_name="orders_copy", tokens={"tableName": "SPOOFED"}
    )

    assert "orders_copy" in rendered
    assert "SPOOFED" not in rendered


# ── the retired refusal phrasing (SPEC-161 FR-005) ──────────────────────────

#: Every ``.py`` under ``lambdas/``, this file excluded — its own patterns would match. The
#: exclusion is by resolved PATH, not by basename: a same-named file elsewhere in the tree
#: would otherwise be exempted silently, which is the shape of a guard that stops guarding.
_SELF = pathlib.Path(__file__).resolve()
_FLEET_SOURCES = [
    p
    for p in sorted(_SELF.parent.parent.rglob("*.py"))
    if p != _SELF and "__pycache__" not in p.parts
]

#: Phrasings retired by SPEC-161, as case-insensitive patterns. Both said a share above the
#: caps was "too large for v1" with S3 Batch Operations as the deferred escape hatch. Neither
#: describes anything true since SPEC-160: the copy IS a Distributed Map, and Batch Ops was
#: rejected on the API rather than deferred. They are operator-facing — both rode as a
#: TerminalError DETAIL, which emit_failure deliberately does not forward to the user — and
#: the cost of leaving them was an operator reading a failed run and going to look for a
#: scale path that does not exist.
_RETIRED = (
    re.compile(r"batch\s*operations", re.IGNORECASE),
    re.compile(r"batch\s*ops", re.IGNORECASE),
    re.compile(r"too\s+large\s+for\s+v1", re.IGNORECASE),
)


def test_the_fleet_sweep_found_the_files():
    """Guards the guard: a glob that matches nothing makes the check below vacuous."""
    assert len(_FLEET_SOURCES) >= 100, f"only found {len(_FLEET_SOURCES)} Python files"


@pytest.mark.parametrize("pattern", _RETIRED, ids=lambda p: p.pattern)
def test_the_retired_refusal_phrasing_is_gone_from_the_fleet(pattern):
    """NO EXISTING TEST ASSERTED THE OLD WORDING, which is why this one has to exist.

    The suites assert ``exc.reason`` and the user-facing sentence, and neither ever carried
    the phrase — so deleting it broke nothing, and re-adding it would break nothing either.
    A grep is the only thing standing between a stale detail and the next operator.
    """
    offenders = [
        f"{path.relative_to(path.parent.parent)}:{text.count(chr(10), 0, match.start()) + 1}"
        for path in _FLEET_SOURCES
        for text in [path.read_text()]
        for match in pattern.finditer(text)
    ]

    assert not offenders, (
        f"the retired /{pattern.pattern}/ phrasing is back — S3 Batch Operations was REJECTED "
        f"on the API by SPEC-160, not deferred, and the copy is a Distributed Map: {offenders}"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
