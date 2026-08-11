"""The received-files link, and who hears about an outcome (SPEC-167 FR-004/FR-005).

The link is the half of this that cannot be checked by reading it: it is minted in Python and
consumed by a route rule written in TypeScript, and the two can drift silently — a link that
resolves to the recipient's space root looks like it worked. Runnable under pytest or directly:
python3 test_notify_fscommon.py.
"""

import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("COGNITO_APP_CLIENT_ID", "test-app-client")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

from fscommon import notify, paths

_PORTAL = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portal" / "src"


def test_a_user_recipients_link_lands_them_in_the_inbox():
    assert notify.received_files_link("user", "bob", "alice") == "/files?prefix=bob/shared_files/alice/"


def test_a_space_recipients_link_names_the_space_as_well():
    """Without ``?space=`` the browser resolves the personal space, and the prefix is then
    discarded for not starting with that space's root — the recipient lands somewhere else
    entirely, with no error."""
    link = notify.received_files_link("space", "finance", "alice")

    assert link == "/files?space=finance&prefix=finance/shared_files/alice/"


def test_the_prefix_is_the_FULL_key_and_the_route_rule_says_why():
    """THE TEST THAT HOLDS THE TWO LANGUAGES TOGETHER (FR-005 AC5).

    ``FilesPage`` keeps the prefix only when ``prefixParam.startsWith(target.rootPrefix)``, and
    ``rootPrefix`` is ``{name}/``. It is read out of the TSX rather than restated, so a change to
    the route's rule fails HERE — where the producer that depends on it lives — instead of
    silently sending every recipient to their space root.
    """
    route = (_PORTAL / "routes" / "FilesPage.tsx").read_text()
    rule = re.search(r"prefixParam\.startsWith\((\w+)\.rootPrefix\)", route)
    assert rule, "the route no longer gates ?prefix= on the space's rootPrefix — re-derive the link"

    for kind, name in (("user", "bob"), ("space", "finance")):
        link = notify.received_files_link(kind, name, "alice")
        prefix = link.split("prefix=", 1)[1]
        assert prefix.startswith(f"{name}/"), (
            f"a {kind} recipient's prefix {prefix!r} does not start with their own root, so the "
            f"route discards it and the link silently lands them at their space root"
        )


def test_the_link_is_the_one_the_destination_builder_writes_to():
    """Derived from the same builder as the keys, so a layout change moves both. A link into a
    folder nothing was written to is worse than no link: it looks like the send failed."""
    link = notify.received_files_link("user", "bob", "alice")
    key = paths.destination_key("bob/", "alice", "reports", "2026/q1.csv")

    assert key.startswith(link.split("prefix=", 1)[1])


def test_the_link_is_a_path_the_browsers_own_gate_accepts():
    """``isSafeInAppPath`` is the second gate and rejects anything that could resolve off this
    origin: a single leading slash, and a second character that cannot open an authority. Its
    rule is read from the TypeScript rather than restated."""
    guard = (_PORTAL / "features" / "notifications" / "notificationLink.ts").read_text()
    assert "link[0] !== '/'" in guard and "link[1] !== '/'" in guard

    for link in (
        notify.received_files_link("user", "bob", "alice"),
        notify.received_files_link("space", "finance", "alice"),
    ):
        assert link.startswith("/") and link[1] not in ("/", "\\")


@pytest.mark.parametrize(
    ("kind", "name", "sender"),
    [
        ("team", "bob", "alice"),
        ("user", "../evil", "alice"),
        ("user", "bob", "../evil"),
        ("user", "bob?x=1", "alice"),
        ("user", "", "alice"),
        ("user", "bob", ""),
        ("user", None, "alice"),
    ],
)
def test_nothing_unexpected_is_ever_interpolated_into_a_link(kind, name, sender):
    """It rejects nothing the pipeline legitimately produces — usernames and space names are
    already constrained — so this is here for the day one of those formats changes. None is the
    honest answer: the notification still says what arrived."""
    assert notify.received_files_link(kind, name, sender) is None


def test_a_send_to_yourself_still_gets_a_working_link():
    """Permitted by validate-authorize (it lands in your own inbox and conflicts naturally if
    repeated), so the link must not treat it as a special case."""
    assert notify.received_files_link("user", "alice", "alice") == "/files?prefix=alice/shared_files/alice/"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
