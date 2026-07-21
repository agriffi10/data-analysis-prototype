"""Unit tests for tscommon.messages — the sender-facing failure wording.

Runnable under pytest or directly: python3 test_messages_tscommon.py.
"""

import os
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

import pytest  # noqa: E402

from tscommon import config, messages  # noqa: E402

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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
