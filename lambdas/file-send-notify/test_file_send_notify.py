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
import threading
import time
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file-send-common"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("COGNITO_USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")
os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")

import file_send_notify as m
import pytest
from cpcommon import budget, clients, config
from fscommon import notify, paths

_PORTAL = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portal" / "src"


@pytest.fixture
def sent(monkeypatch):
    """Every message the producer emitted, as ``(recipient, body, link)``."""
    captured = []
    monkeypatch.setattr(
        notify,
        "emit_notification",
        lambda user, message, link=None, **kw: captured.append((user, message, link)),
    )
    return captured


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    """A registry whose spaces have an owner, unless a test says otherwise."""
    monkeypatch.setattr(notify.reg, "load", lambda name, client=None: {"owner": f"{name}-owner"})


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


class _Queue:
    """Records every send the real sender makes, as the notifications queue would receive it.

    Attributes:
      calls: The keyword arguments of each ``send_message``, in order.
    """

    def __init__(self):
        """Starts with nothing sent.

        Args:
          None.

        Returns:
          None.

        Raises:
          None.
        """
        self.calls = []

    def send_message(self, **kwargs):
        """Keeps one send.

        Args:
          **kwargs: The send's arguments.

        Returns:
          A response carrying a message id.

        Raises:
          None.
        """
        self.calls.append(kwargs)
        return {"MessageId": "m"}


def test_two_sends_delivered_alike_are_two_notices_to_everyone_and_a_retry_is_one(monkeypatch):
    """The re-send after a conflict, once the recipient moved the first delivery, succeeds with the
    first send's sentence. The queue deduplicates per recipient on the dedup id, so each addressee's
    second notice survives only if its id names the run — and a retry of the producer must compose
    the same ids, or one run is told twice.

    The bodies are asserted identical across the two runs, which is what makes the differing keys
    evidence: nothing but the id keeps them apart. ``bob`` is both a user recipient and the owner of
    the space recipient, so his two notices share a message group and meet on their tokens.
    """
    queue = _Queue()
    monkeypatch.setattr(clients, "_sqs", queue)
    monkeypatch.setattr(clients, "_sqs_bounded", queue)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/n.fifo", raising=False)
    monkeypatch.setattr(notify.reg, "load", lambda name, client=None: {"owner": "bob"})
    recipients = [_ok(), _ok(kind="space", name="finance")]
    runs = []
    for request_id in ("run-a", "run-b", "run-a"):
        before = len(queue.calls)
        m.handler({**_summary(recipients), "requestId": request_id}, None)
        runs.append(queue.calls[before:])
    first, second, retry = ([(c["MessageGroupId"], c.get("MessageDeduplicationId")) for c in r] for r in runs)

    assert [group for group, _id in first] == ["alice", "bob", "alice", "bob"]
    assert [c["MessageBody"] for c in runs[0]] == [c["MessageBody"] for c in runs[1]]
    assert all(dedup for _group, dedup in first), "a success went out with no dedup id"
    assert len(set(first)) == len(first), "one run's notices collapse into each other"
    assert not set(first) & set(second), "two runs' notices collapse"
    assert retry == first, "a retry of one run is told twice"


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

    ``FilesPage`` keeps a ``?prefix=`` only when it starts with the resolved space's ``rootPrefix``,
    ends in ``/`` and has no segment that is empty, ``.`` or ``..``; any other prefix is discarded
    and the recipient lands at their space root, a link that looks as if it worked. The route's
    path, its ``?prefix=`` and ``?space=`` parameters, its whole gate and the segment rule
    ``isNamedPath`` applies, what ``rootPrefix`` is, how the row's derived gate reads a ``/files``
    link's space, and ``isSafeInAppPath``'s accept rule are read out of the source rather than restated:
    pinning only the gate leaves a rename of ``rootPrefix`` green while every link lands at a root.
    The file-ops plane's ``test_the_prefix_is_the_FULL_key_and_the_ROUTES_OWN_RULE_says_why`` reads
    the route's path, its ``?prefix=`` and ``?space=`` parameters, its gate, the segment rule and
    ``rootPrefix`` with the same patterns, so a change to any of them is re-derived for both links.
    Each addressee's space and root come from who they are — ``bob`` is a user and
    ``finance-owner`` receives for the space ``finance`` — never from the link, which would check
    the link against itself. A space link must name its space in ``space``, because the row's gate
    reads it from there and counts only ``personal`` as the viewer's own; a space link the gate did
    not see as shared would slip the shared-workspaces gate and land its owner in their own files.
    ``space`` still comes first, as every plane's link puts it. And the prefix must be the inbox the
    copy writes to, since a link to the space root also survives the route and shows the recipient
    nothing they were sent.
    """
    summary = _summary([_ok(), _ok(kind="space", name="finance")])

    m.handler(summary, None)

    area = (_PORTAL / "lib" / "navigation" / "areas" / "files.ts").read_text()
    assert "paths: ['/files']" in area, "the file browser's path moved — re-derive the link's path"
    route = (_PORTAL / "routes" / "FilesPage.tsx").read_text()
    assert "const prefixParam = searchParams.get('prefix') || undefined;" in route, (
        "the route no longer reads ?prefix= as it is"
    )
    assert re.search(
        r"const initialPrefix =\s*prefixParam\s*&&\s*prefixParam\.startsWith\((\w+)\.rootPrefix\)"
        r"\s*&&\s*prefixParam\.endsWith\('/'\)\s*&&\s*isNamedPath\(prefixParam\)"
        r"\s*\?\s*prefixParam\s*:\s*\1\.rootPrefix;",
        route,
    ), "the route's ?prefix= gate changed — re-derive the link"
    helpers = (_PORTAL / "features" / "file-browser" / "fileBrowser.paths.ts").read_text()
    assert re.search(
        r"export function isNamedPath\(keyOrPrefix: string\): boolean \{\s*return keyOrPrefix"
        r"\s*\.replace\(/\\/\$/, ''\)\s*\.split\('/'\)\s*\.every\(\s*\(segment\) =>\s*segment !== ''"
        r"\s*&&\s*segment !== '\.'\s*&&\s*segment !== '\.\.'\s*\);\s*\}",
        helpers,
    ), "isNamedPath's segment rule changed — re-derive what a link's prefix may contain"
    space = (_PORTAL / "features" / "file-browser" / "useFileSpace.ts").read_text()
    assert "searchParams.get('space')" in space, "the space is no longer chosen by ?space="
    assert "rootPrefix: `${username}/`" in space, "a personal space's root is no longer {username}/"
    assert "rootPrefix: `${conn.database}/`" in space, "a shared space's root is no longer {name}/"
    row = (_PORTAL / "features" / "notifications" / "NotificationRow.tsx").read_text()
    assert "useCanFollowLink()" in row, "the row no longer derives its gate from the link — re-derive the link"
    gate = (_PORTAL / "features" / "feature-flags" / "linkFlags.ts").read_text()
    assert re.search(
        r"pattern: '/files',\s*read: \(url\) => url\.searchParams\.get\('space'\),"
        r"\s*isPersonal: \(name\) => name === 'personal'",
        gate,
    ), "the gate no longer reads a /files link's space from ?space= — re-derive what a space link carries"
    guard = (_PORTAL / "features" / "notifications" / "notificationLink.ts").read_text()
    assert "link[0] !== '/'" in guard and "link[1] === '/'" in guard and "charCodeAt(0) < 0x20" in guard, (
        "isSafeInAppPath's accept rule changed"
    )

    expected = {"bob": ([], "bob/"), "finance-owner": (["finance"], "finance/")}
    received = [(user, link) for user, _m, link in sent if user != "alice"]
    assert [user for user, _l in received] == list(expected), "the recipients told are not the ones sent to"
    for user, link in received:
        spaces, root = expected[user]
        assert link is not None, f"{user}'s message lost its link"
        url = urlsplit(link)
        query = parse_qs(url.query, keep_blank_values=True)
        prefix = query.get("prefix", [""])[0]
        assert url.path == "/files", f"{link!r} does not open the file browser"
        assert query.get("space", []) == spaces, f"{link!r} does not name the space whose root is {root!r}"
        assert ("?space=" in link) == bool(spaces), f"{link!r} no longer puts space first, as every plane's link does"
        assert prefix == paths.inbox_prefix(root, "alice"), f"{prefix!r} is not the inbox the copy writes to"
        assert prefix.startswith(root), f"{prefix!r} does not start with the root the route resolves, {root!r}"
        assert prefix.endswith("/"), f"{prefix!r} does not end at a folder boundary, so the route discards it"
        assert all(part not in ("", ".", "..") for part in prefix[:-1].split("/")), (
            f"{prefix!r} has a segment that is empty or a dot, so the route discards it"
        )
        assert link[0] == "/" and link[1] not in ("/", "\\"), f"{link!r} is not a path isSafeInAppPath accepts"
        assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in link), f"{link!r} carries a control character"


def test_a_stalled_queue_holds_the_producer_for_one_deadline_not_a_cap_per_message(stalled_sends, caplog):
    """Every message of the run shares one budget: two start before its deadline and every later
    one is refused, where a budget per message would start all ten."""
    recipients = [_ok(name=f"user{i}") for i in range(5)]

    m.handler(_summary(recipients), None)

    assert stalled_sends.started == 2
    assert stalled_sends.reasons(caplog.records) == (
        ["notifications: a call ran past 0.05s"] * 2 + ["notifications ran out of time"] * 8
    )


def test_a_stalled_owner_lookup_costs_the_owners_message_and_not_the_send(monkeypatch, caplog):
    """The lookup runs after the sender was told, on the bounded client and under the producer's
    budget, which the error's label names: a budget of its own would be labelled for the lookup."""
    queue = _Queue()
    monkeypatch.setattr(clients, "_sqs", queue)
    monkeypatch.setattr(clients, "_sqs_bounded", queue)
    monkeypatch.setattr(config, "NOTIFICATIONS_QUEUE_URL", "https://sqs.test/n.fifo", raising=False)
    monkeypatch.setattr(budget, "CALL_CAP_SECONDS", 0.05)
    bounded_s3 = object()
    monkeypatch.setattr(clients, "_s3_bounded", bounded_s3)
    released = threading.Event()
    read_with = []

    def _stalled_load(name, client=None):
        read_with.append(client)
        released.wait(5)
        return {"owner": "bob"}

    monkeypatch.setattr(notify.reg, "load", _stalled_load)
    started = time.perf_counter()
    try:
        m.handler(_summary([_ok(kind="space", name="finance")]), None)
        held = time.perf_counter() - started
    finally:
        released.set()

    lookup = [r for r in caplog.records if "owner lookup failed" in r.getMessage()]
    assert [c["MessageGroupId"] for c in queue.calls] == ["alice"]
    assert read_with == [bounded_s3]
    assert [str(r.exc_info[1]) for r in lookup] == ["notifications: a call ran past 0.05s"]
    assert held < 1

