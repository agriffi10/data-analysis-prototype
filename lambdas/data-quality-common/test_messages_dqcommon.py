"""Unit tests for dqcommon.messages — the reason-code registry (SPEC-110 FR-007).

Runnable under pytest or directly: python3 test_messages_dqcommon.py.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpcommon import messages as cpmessages  # noqa: E402
from cpcommon.errors import TerminalError  # noqa: E402
from dqcommon import config, messages  # noqa: E402

# Every reason code the data-quality verbs raise today (SPEC-109 + SPEC-110).
INSPECT_SOURCE_REASONS = (
    messages.NO_DATA_FILES,
    messages.UNSUPPORTED_FORMAT,
    messages.MIXED_FORMATS,
    messages.TOO_MANY_FILES,
    messages.COMPRESSED_SOURCE_TOO_LARGE,
    messages.UNREADABLE_HEADER,
    messages.TOO_MANY_PARTITION_VALUES,
    messages.PARTITION_LAYOUT_MISMATCH,
)


def test_inspect_source_reasons_are_in_dqcommons_own_table():
    """Every code must be registered BY THIS DOMAIN — the guard for the whole FR.

    Asserting `_BODIES` rather than `cpmessages.is_known_reason` is the entire point.
    `is_known_reason` reads a PROCESS-GLOBAL set that every domain layer extends at
    import, and `pytest lambdas/` imports tbcommon into this same process — where it
    registers no_data_files / unsupported_format / mixed_formats. So an is_known_reason
    assertion PASSES for a code dqcommon never registered, while the deployed function
    (cpcommon + dqcommon + polars, no tbcommon) raises ValueError at the raise site. This
    test exists to fail in exactly that case; do not "simplify" it to is_known_reason.
    """
    for reason in (messages.INVALID_REQUEST, *INSPECT_SOURCE_REASONS):
        assert reason in messages._BODIES, f"{reason} is not registered in dqcommon's own table"


def test_reasons_are_valid_terminal_error_reasons():
    """Registration must make each code constructible as a TerminalError (SPEC-107 FR-005)."""
    for reason in INSPECT_SOURCE_REASONS:
        err = TerminalError(reason, "detail")
        assert err.reason == reason


def test_base_codes_are_not_redefined():
    """The resolver hard-errors on a domain re-defining a shared base code."""
    assert not set(messages._BODIES) & cpmessages.BASE_REASONS


def test_caps_are_baked_into_wording_not_left_as_tokens():
    """A message quoting a limit must quote the CONSTANT, so the two can't drift."""
    assert str(config.DQ_MAX_OBJECTS) in messages._BODIES[messages.TOO_MANY_FILES]
    assert str(config.DQ_MAX_PARTITION_VALUES) in messages._BODIES[messages.TOO_MANY_PARTITION_VALUES]
    assert "1 GB" in messages._BODIES[messages.COMPRESSED_SOURCE_TOO_LARGE]


def test_failure_message_fills_per_request_tokens():
    body = messages.failure_message(messages.UNREADABLE_HEADER, "alice/sales", object="alice/sales/a.csv")
    assert "alice/sales/a.csv" in body
    assert "{object}" not in body


def test_failure_message_tolerates_braces_in_a_key():
    """str.replace, never str.format — a literal brace in an S3 key must not raise."""
    body = messages.failure_message(messages.UNREADABLE_HEADER, object="alice/od{d}/a.csv")
    assert "alice/od{d}/a.csv" in body


def test_compressed_message_says_decompress_or_split_not_too_big():
    """The same data uncompressed passes, so 'the file is too big' would be a lie."""
    body = messages.failure_message(messages.COMPRESSED_SOURCE_TOO_LARGE, object="alice/s/big.csv.gz")
    assert "decompress" in body.lower()
    assert "split" in body.lower()
    assert "big.csv.gz" in body


def test_unsupported_format_carries_no_convert_first_guidance():
    """Excel is unsupported everywhere; a converter can't help, so don't send them there."""
    body = messages.failure_message(messages.UNSUPPORTED_FORMAT)
    assert "convert" not in body.lower()


def test_access_denied_reasons_leak_no_path():
    body = messages.failure_message(messages.FORBIDDEN, "alice/secret-folder")
    assert "secret-folder" not in body


def test_unknown_reason_falls_back_without_leaking_the_code():
    body = messages.failure_message("no_such_reason_code")
    assert "no_such_reason_code" not in body


# ── The exhaustive raise-site walk (SPEC-114 FR-002) ─────────────────────────
#
# Everything above pins WORDING. This walks the arc's actual source and pins that no raise
# site can name a reason this domain never registered, and that no message promising to
# name a file or a count can ship without the token to fill it. Both failures are invisible
# in a unit test of the verb: the first raises ValueError only on the deployed function
# (see the docstring on test_inspect_source_reasons_are_in_dqcommons_own_table), and the
# second renders "{count} found" to a user while every assertion still passes.

import ast  # noqa: E402
import re  # noqa: E402

_ARC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
_MARKER = re.compile(r"\{(\w+)\}")


def _verb_sources():
    """Every non-test data-quality module, as (path, parsed AST)."""
    for entry in sorted(os.listdir(_ARC)):
        if not entry.startswith("data-quality-"):
            continue
        folder = os.path.join(_ARC, entry)
        if not os.path.isdir(folder):
            continue
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if not name.endswith(".py") or name.startswith("test_"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    yield path, ast.parse(handle.read())


def _reason_of(node):
    """The reason code a `messages.CONST` / literal AST node denotes, or None."""
    if isinstance(node, ast.Attribute) and node.attr.isupper():
        return getattr(messages, node.attr, None)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _raise_sites():
    """Every (path, reason, token_keys) the arc can produce.

    Covers BOTH shapes: a direct `TerminalError(reason, ...)` and the typed terminal
    `cpcommon.events` raises via `reason=` (FR-002 names these explicitly — a malformed
    envelope is a terminal like any other).
    """
    for path, tree in _verb_sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            tokens = set()
            for kw in node.keywords:
                if kw.arg == "tokens" and isinstance(kw.value, ast.Dict):
                    tokens = {k.value for k in kw.value.keys if isinstance(k, ast.Constant)}
            if name == "TerminalError" and node.args:
                reason = _reason_of(node.args[0])
                if reason:
                    yield path, reason, tokens
                continue
            for kw in node.keywords:
                if kw.arg == "reason":
                    reason = _reason_of(kw.value)
                    if reason:
                        yield path, reason, tokens


def test_every_raise_site_in_the_arc_names_a_registered_reason():
    """A missing code is not a vague message — it is a ValueError at the raise site, in
    production, on the failure it exists for. Asserted against dqcommon's OWN table plus
    the cpcommon base codes; never `is_known_reason` (see the note at the top of this file).
    """
    sites = list(_raise_sites())
    assert sites, "found no raise sites — the walker is broken, not the code"
    valid = set(messages._BODIES) | set(cpmessages.BASE_REASONS)
    for path, reason, _tokens in sites:
        assert reason in valid, f"{os.path.basename(path)} raises unregistered reason {reason!r}"


def test_every_message_marker_is_filled_by_every_site_that_can_raise_it():
    """A body promising to name the file/count/key must be raised WITH that token.

    This is what makes FR-002's per-code criteria ("names the file", "names the column
    count") hold at the raise site rather than only in a hand-written message test.
    """
    for path, reason, tokens in _raise_sites():
        needed = set(_MARKER.findall(messages._BODIES.get(reason, "")))
        missing = needed - tokens
        assert not missing, (
            f"{os.path.basename(path)} raises {reason!r} without token(s) {sorted(missing)} — "
            f"the message would render them literally"
        )


def test_no_message_body_leaves_a_marker_the_arc_never_supplies():
    """The mirror: a marker no raise site fills is dead wording that would reach a user."""
    supplied = {}
    for _path, reason, tokens in _raise_sites():
        supplied.setdefault(reason, set()).update(tokens)
    for reason, body in messages._BODIES.items():
        markers = set(_MARKER.findall(body))
        if not markers:
            continue
        assert reason in supplied, f"{reason!r} has markers {sorted(markers)} but is never raised"
        assert not markers - supplied[reason], (
            f"{reason!r} has marker(s) {sorted(markers - supplied[reason])} no raise site fills"
        )


def test_every_handler_in_the_arc_notifies_on_failure():
    """FR-003: an unexpected crash in ANY verb must still reach the user. A new verb that
    forgets the decorator is a silent failure, which is the thing this arc exists to end."""
    undecorated = []
    for path, tree in _verb_sources():
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != "handler":
                continue
            names = [
                d.func.attr if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) else ""
                for d in node.decorator_list
            ]
            # notify-failure is the exception and must stay one: it is the LAST state on the
            # failure path, so a decorator emitting there would be notifying about a failure
            # to notify. Its own no-raise guarantee is pinned in its test module instead.
            if "notifies_on_failure" not in names and "notify_failure" not in os.path.basename(path):
                undecorated.append(os.path.basename(path))
    assert not undecorated, f"handler(s) missing @notifies_on_failure: {undecorated}"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all message tests passed")
