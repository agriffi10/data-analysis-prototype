"""Unit tests for dqcommon.messages — the reason-code registry (SPEC-110 FR-007).

Runnable under pytest or directly: python3 test_messages.py.
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


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ok  {name}")
    print("all message tests passed")
