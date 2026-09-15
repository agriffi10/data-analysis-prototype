"""Unit tests for the file-send notify Lambda (SPEC-167 FR-004/FR-005).

Who is told what, and who is NOT told: the three ways an outcome producer goes wrong are telling
the wrong person, telling somebody twice, and failing a delivered send because a message did not
go out. A fourth is a link that looks as if it worked and lands the recipient somewhere else.

Attributes:
  _PORTAL: The browser's source tree, whose route rules the link has to survive.
"""

import os
import pathlib
import re
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_notify as m
import pytest
from fscommon import notify, paths

_PORTAL = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portal" / "src"


@pytest.fixture
def sent(monkeypatch):
    """Every message the producer emitted, as ``(recipient, body, link)``."""
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, dedup_id=None, link=None: captured.append((user, message, link)),
    )
    return captured


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    """A registry whose spaces have an owner, unless a test says otherwise."""
    monkeypatch.setattr(notify.reg, "load", lambda name: {"owner": f"{name}-owner"})


def _ok(kind="user", name="bob"):
    return {"kind": kind, "name": name, "status": "ok", "reason": "", "detail": "", "failedItems": 0}


def _failed(reason, kind="user", name="carol", detail="", failed_items=0):
    return {
        "kind": kind,
        "name": name,
        "status": "failed",
        "reason": reason,
        "detail": detail,
        "failedItems": failed_items,
    }


def _summary(recipients, sender="alice", item_names=("reports", "notes.txt"), objects=301):
    return {
        "requestId": "req-1",
        "sender": sender,
        "itemNames": list(item_names),
        "objectCount": objects,
        "recipients": recipients,
    }


def test_a_delivered_send_tells_the_sender_and_the_recipient(sent):
    m.handler(_summary([_ok()]), None)

    assert [user for user, _m, _l in sent] == ["alice", "bob"]


def test_a_failed_recipient_is_told_NOTHING(sent):
    """They have no part in the send, nothing to do about it, and being told would leak that the
    sender tried. FR-005: a recipient failure notifies the sender only."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    assert [user for user, _m, _l in sent] == ["alice"]


def test_a_conflict_names_the_recipient_AND_the_colliding_item(sent):
    """FR-004. The item name is the one piece of context the sender can act on — and it survives
    as a FIELD from the guard, which is why that verb returns its refusals rather than raising."""
    m.handler(_summary([_failed("conflict", detail="reports")]), None)

    body = sent[0][1]
    assert 'user "carol"' in body
    assert '"reports"' in body


def test_a_recipients_link_is_the_FULL_key_and_the_ROUTES_OWN_RULE_says_why(sent):
    """The link is minted in Python by ``fscommon.notify.received_files_link`` and honoured by
    TypeScript, and nothing else offline connects the two languages.

    ``FilesPage`` keeps a ``?prefix=`` only when it starts with the resolved space's ``rootPrefix``
    and ends in ``/``; any other prefix is discarded and the recipient lands at their space root, a
    link that looks as if it worked. The route's path, its ``?prefix=`` and ``?space=`` parameters,
    its whole gate, what ``rootPrefix`` is, the literal ``NotificationRow`` gates a space link on,
    and ``isSafeInAppPath``'s accept rule are read out of the source rather than restated: pinning
    only the gate leaves a rename of ``rootPrefix`` green while every link lands at a root. Each
    addressee's space and root come from who they are — ``bob`` is a user and ``finance-owner``
    receives for the space ``finance`` — never from the link, which would check the link against
    itself. ``?space=`` must come first, because the row tests for that literal and a space link
    that slips the shared-workspaces gate lands its owner in their own files. And the prefix must be
    the inbox the copy writes to, since a link to the space root also survives the route and shows
    the recipient nothing they were sent.
    """
    summary = _summary([_ok(), _ok(kind="space", name="finance")])

    m.handler(summary, None)

    app = (_PORTAL / "App.tsx").read_text()
    assert 'path="/files"' in app, "the file browser's route moved — re-derive the link's path"
    route = (_PORTAL / "routes" / "FilesPage.tsx").read_text()
    assert "const prefixParam = searchParams.get('prefix')" in route, "the route no longer reads ?prefix="
    assert re.search(
        r"const initialPrefix =\s*prefixParam\s*&&\s*prefixParam\.startsWith\((\w+)\.rootPrefix\)"
        r"\s*&&\s*prefixParam\.endsWith\('/'\)\s*\?\s*prefixParam\s*:\s*\1\.rootPrefix;",
        route,
    ), "the route's ?prefix= gate changed — re-derive the link"
    space = (_PORTAL / "features" / "file-browser" / "useFileSpace.ts").read_text()
    assert "searchParams.get('space')" in space, "the space is no longer chosen by ?space="
    assert "rootPrefix: `${username}/`" in space, "a personal space's root is no longer {username}/"
    assert "rootPrefix: `${conn.database}/`" in space, "a shared space's root is no longer {name}/"
    row = (_PORTAL / "features" / "notifications" / "NotificationRow.tsx").read_text()
    assert "'?space='" in row, "the row no longer gates a space link on that literal — re-derive the mint order"
    guard = (_PORTAL / "features" / "notifications" / "notificationLink.ts").read_text()
    assert "link[0] !== '/'" in guard and "link[1] !== '/'" in guard, "isSafeInAppPath's accept rule changed"

    expected = {"bob": ([], "bob/"), "finance-owner": (["finance"], "finance/")}
    received = [(user, link) for user, _m, link in sent if user != "alice"]
    assert [user for user, _l in received] == list(expected), "the recipients told are not the ones sent to"
    for user, link in received:
        spaces, root = expected[user]
        assert link is not None, f"{user}'s message lost its link"
        url = urlsplit(link)
        query = parse_qs(url.query)
        prefix = query.get("prefix", [""])[0]
        assert url.path == "/files", f"{link!r} does not open the file browser"
        assert query.get("space", []) == spaces, f"{link!r} does not name the space whose root is {root!r}"
        assert ("?space=" in link) == bool(spaces), f"{link!r} slips the row's shared-workspaces gate"
        assert prefix == paths.inbox_prefix(root, "alice"), f"{prefix!r} is not the inbox the copy writes to"
        assert prefix.startswith(root), f"{prefix!r} does not start with the root the route resolves, {root!r}"
        assert prefix.endswith("/"), f"{prefix!r} does not end at a folder boundary, so the route discards it"
        assert link[0] == "/" and link[1] not in ("/", "\\"), f"{link!r} is not a path isSafeInAppPath accepts"
