"""Choosing the wording by the operation, on the path where everything else has already failed.

Every other plane has one verb and so one prefix. This one serves three, and the emitters run
where the request may be malformed enough that its operation is missing or the wrong type — so the
lookup has to be defensive without being silent.
"""

import json
import os
import pathlib
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "control-plane-common"))

os.environ.setdefault("USER_SPACE_BUCKET", "user-bkt")
os.environ.setdefault("SHARED_SPACE_BUCKET", "shared-bkt")
os.environ.setdefault("ADMIN_BUCKET", "admin-bkt")

from cpcommon.errors import TerminalError
from focommon import config, notify


@pytest.fixture(autouse=True)
def sent(monkeypatch):
    log = []
    monkeypatch.setattr(
        notify, "emit_notification", lambda user, text, *a, **kw: log.append((user, text, kw))
    )
    return log


def _pipe(operation="delete"):
    return [{"body": json.dumps({"requestId": "r", "actor": "tok", "operation": operation})}]


def test_the_operation_is_read_from_the_running_event():
    assert notify.operation_of({"operation": "move"}) == "move"


def test_the_operation_is_recovered_from_the_PIPE_BATCH_when_the_event_lost_it():
    """The pre-identity failure path carries the original request under `raw` and nowhere else —
    the recorded failure has no `operation` of its own, so without this every early failure would
    be worded as a copy."""
    assert notify.operation_of({"raw": _pipe("delete")}) == "delete"


@pytest.mark.parametrize(
    "event",
    [None, "string", {}, {"operation": 3}, {"raw": "not-a-list"}, {"raw": []}, {"raw": [{"body": "{"}]}],
)
def test_an_unrecoverable_operation_is_None_rather_than_a_raise(event):
    """These emitters run on the failure path. Raising here would replace a friendly sentence with
    an unhandled error on the one path whose whole job is reporting a failure."""
    assert notify.operation_of(event) is None


def test_each_operation_gets_its_own_sentence(sent):
    for operation in ("copy", "move", "delete"):
        notify.emit_failure(
            {"actor": {"username": "alice"}, "operation": operation},
            TerminalError("marker_not_deletable", "operator text"),
            "validate",
        )

    assert [text.split(":")[0] for _, text, _ in sent] == [
        "Couldn't copy that",
        "Couldn't move that",
        "Couldn't delete that",
    ]


def test_the_operator_DETAIL_never_reaches_the_user(sent):
    """A detail can quote a folder name the actor supplied and exists for the logs and the Step
    Functions record. Tokens are the opposite channel — values a raise site provides precisely
    because a body names a marker for them."""
    notify.emit_failure(
        {"actor": {"username": "alice"}, "operation": "copy"},
        TerminalError("marker_not_deletable", "alice/secret-project/DO_NOT_DELETE.txt"),
        "validate",
    )

    assert "secret-project" not in sent[0][1]


def test_a_token_DOES_reach_the_user_where_a_body_names_one(sent):
    notify.emit_failure(
        {"actor": {"username": "alice"}, "operation": "copy"},
        TerminalError("colliding_item_names", "x.csv", tokens={"itemName": "x.csv"}),
        "validate",
    )

    assert '"x.csv"' in sent[0][1]


def test_an_unexpected_exception_gets_the_generic_sentence_and_leaks_nothing(sent):
    """The path the acquire verb's decorator takes, and the one nothing else exercised."""
    notify.emit_unexpected({"actor": {"username": "alice"}, "operation": "move"}, "acquire-lock")

    assert sent[0][0] == "alice"
    assert sent[0][1].startswith("Couldn't move that: ")
    assert "Traceback" not in sent[0][1] and "Error" not in sent[0][1]


def test_a_failure_with_no_bound_actor_is_a_no_op_rather_than_a_lost_message(sent):
    """The body's own actor field is attacker-controlled; notifying it would let anyone deliver
    text to any inbox."""
    notify.emit_unexpected({"operation": "copy"}, "validate")

    assert sent == [] or sent[0][0] == ""


# ── The run's one message: its wording, its link and its payload ──────────────────────────


_PORTAL = pathlib.Path(__file__).resolve().parents[2] / "apps" / "portal" / "src"


def _summary(operation="move", destination_prefix="finance/reports/", items=None):
    return {
        "operation": operation,
        "source": {"kind": "personal", "name": "alice"},
        "destination": (
            {"kind": "shared", "name": "finance", "prefix": destination_prefix}
            if destination_prefix
            else {"kind": None, "name": None, "prefix": None}
        ),
        "items": items
        if items is not None
        else [
            {"itemKey": "alice/reports/", "kind": "folder", "targetName": "archive-2026"},
            {"itemKey": "alice/q1.csv", "kind": "file", "targetName": None},
        ],
    }


def _records(*pairs):
    return [
        {"itemKey": key, "label": key.rstrip("/").rsplit("/", 1)[-1], "outcome": outcome, **extra}
        for key, outcome, extra in pairs
    ]


def test_a_run_that_landed_something_links_to_the_DESTINATION():
    link = notify.outcome_link(
        _summary(), _records(("alice/reports/", "moved", {}), ("alice/q1.csv", "conflict", {}))
    )

    assert link == "/files?space=finance&prefix=finance/reports/"


def test_a_run_that_landed_NOTHING_links_to_the_source_where_the_items_still_are():
    """One message per run means one link, so the rule is about the run rather than an item. A
    destination nothing reached is the one place the user has no reason to look."""
    link = notify.outcome_link(_summary(), _records(("alice/reports/", "conflict", {})))

    assert link == "/files?prefix=alice/"


def test_a_duplicate_counts_as_LANDED_because_its_objects_are_at_the_destination():
    """It is neither a success nor a failure, and the destination is exactly where the user has to
    look to choose which of the two copies to keep."""
    link = notify.outcome_link(_summary(), _records(("alice/reports/", "duplicate", {})))

    assert link == "/files?space=finance&prefix=finance/reports/"


def test_a_delete_links_to_the_folder_its_items_SHARED_rather_than_to_an_item():
    summary = _summary(
        operation="delete",
        destination_prefix=None,
        items=[{"itemKey": "alice/x/y/", "kind": "folder"}, {"itemKey": "alice/x/z.csv", "kind": "file"}],
    )

    assert notify.outcome_link(summary, _records(("alice/x/y/", "deleted", {}))) == "/files?prefix=alice/x/"


def test_a_SINGLE_item_delete_links_to_the_items_PARENT_and_not_to_the_item():
    """The hole a longest-common-prefix over the KEYS has, and it only shows with one item: the
    prefix is then the item itself, which links the user into the folder that was just removed —
    an empty listing where a folder used to be."""
    summary = _summary(
        operation="delete", destination_prefix=None, items=[{"itemKey": "alice/only/", "kind": "folder"}]
    )

    assert notify.outcome_link(summary, _records(("alice/only/", "deleted", {}))) == "/files?prefix=alice/"


def test_a_common_prefix_that_names_no_folder_is_cut_back_to_one():
    """Two siblings named ``report-a`` and ``report-b`` share ``report-``, which is not a folder."""
    summary = _summary(
        operation="delete",
        destination_prefix=None,
        items=[{"itemKey": "alice/report-a", "kind": "file"}, {"itemKey": "alice/report-b", "kind": "file"}],
    )

    assert notify.outcome_link(summary, _records(("alice/report-a", "deleted", {}))) == "/files?prefix=alice/"


def test_a_prefix_outside_the_space_root_falls_back_to_the_root_rather_than_being_sent():
    """The route keeps a ``?prefix=`` only when it starts with the resolved space's root, so a
    prefix from anywhere else is discarded and the user lands at their root with no idea why.
    Falling back deliberately gives them the root the route would have given them anyway."""
    summary = _summary(destination_prefix="somewhere-else/out/")

    assert notify.outcome_link(summary, _records(("alice/reports/", "moved", {}))) == (
        "/files?space=finance&prefix=finance/"
    )


def test_an_unrecognised_space_name_mints_NOTHING():
    """The honest answer: the notification still says what happened, it just carries no link."""
    summary = _summary()
    summary["destination"]["name"] = "../evil"

    assert notify.outcome_link(summary, _records(("alice/reports/", "moved", {}))) is None


def test_the_prefix_is_PERCENT_ENCODED_because_a_key_is_not_a_constrained_name():
    """Unlike the neighbouring planes' links, this prefix is an arbitrary user-controlled key. An
    unencoded ``?``, ``#`` or ``&`` in it truncates the link into one that resolves elsewhere."""
    summary = _summary(destination_prefix="finance/we ird?&#/")
    link = notify.outcome_link(summary, _records(("alice/reports/", "moved", {})))
    sent_prefix = link.split("prefix=", 1)[1]

    assert sent_prefix == "finance/we%20ird%3F%26%23/"
    assert unquote(sent_prefix) == "finance/we ird?&#/", "the browser cannot recover the real key"


def test_a_shared_space_link_names_its_space_where_the_rows_derived_gate_reads_it():
    """FR-004 AC4's gating is verified and cited rather than built, and this is the half that
    verification has to cover. ``NotificationRow`` derives its gate from the link, and for a
    ``/files`` link the gate reads the space from the ``space`` parameter and counts only
    ``personal`` as the viewer's own. A shared-space link that did not name its space there would
    pass as personal, and the shared-workspaces gate would never fire: the route would not read the
    space, resolve the personal one, discard a prefix that does not start with it, and land the user
    in their own files. ``space`` still comes first, as every plane's link puts it.
    """
    row = (_PORTAL / "features" / "notifications" / "NotificationRow.tsx").read_text()
    assert "useCanFollowLink()" in row, "the row no longer derives its gate from the link — re-derive the link"
    gate = (_PORTAL / "features" / "feature-flags" / "linkFlags.ts").read_text()
    assert re.search(
        r"pattern: '/files',\s*read: \(url\) => url\.searchParams\.get\('space'\),"
        r"\s*isPersonal: \(name\) => name === 'personal'",
        gate,
    ), "the gate no longer reads a /files link's space from ?space= — re-derive what a space link carries"

    link = notify.outcome_link(_summary(), _records(("alice/reports/", "moved", {})))
    query = parse_qs(urlsplit(link).query)
    assert query.get("space", [""])[0] not in ("", "personal"), "a shared-space link the gate would read as personal"
    assert "?space=" in link, "a shared-space link that no longer puts space first, as every plane's link does"


def test_the_prefix_is_the_FULL_key_and_the_ROUTES_OWN_RULE_says_why():
    """THE TEST THAT HOLDS THE TWO LANGUAGES TOGETHER (FR-004 AC5).

    The link is minted in Python and honoured by a TypeScript route rule, and nothing offline
    connects the two. Everything the route decides with is read out of the source rather than
    restated: its path, its ``?prefix=`` and ``?space=`` parameters, its gate and the segment rule
    ``isNamedPath`` applies, and what ``rootPrefix`` actually is — pinning only the gate leaves a
    rename of that value passing every assertion here while every link silently lands at a space
    root. The gate and the segment rule are each pinned whole, because a clause added to either
    refuses links this test would still call good; the file-send plane's
    ``test_a_recipients_link_is_the_FULL_key_and_the_ROUTES_OWN_RULE_says_why`` reads all of these
    with the same patterns. Each run's space and root come from where its result is — the
    destination when anything landed, the source when nothing did — never from the link, which
    would check the link against itself and pass one that names the wrong space.
    """
    app = (_PORTAL / "App.tsx").read_text()
    assert 'path="/files"' in app, "the file browser's route moved — re-derive the link's path"
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

    expected = {"moved": (["finance"], "finance/"), "conflict": ([], "alice/")}
    for outcome, (spaces, root) in expected.items():
        link = notify.outcome_link(_summary(), _records(("alice/reports/", outcome, {})))
        assert link is not None, f"a run whose item was {outcome!r} lost its link"
        url = urlsplit(link)
        query = parse_qs(url.query, keep_blank_values=True)
        prefix = query.get("prefix", [""])[0]
        assert url.path == "/files", f"{link!r} does not open the file browser"
        assert query.get("space", []) == spaces, f"{link!r} does not name the space whose root is {root!r}"
        assert prefix.startswith(root), f"{prefix!r} does not start with the root the route resolves, {root!r}"
        assert prefix.endswith("/"), f"{prefix!r} does not end at a folder boundary, so the route discards it"
        assert all(part not in ("", ".", "..") for part in prefix[:-1].split("/")), (
            f"{prefix!r} has a segment that is empty or a dot, so the route discards it"
        )


def test_the_link_is_a_path_the_browsers_own_gate_accepts():
    """``isSafeInAppPath`` is the second gate and rejects anything that could resolve off this
    origin. Its rule is read from the TypeScript rather than restated."""
    guard = (_PORTAL / "features" / "notifications" / "notificationLink.ts").read_text()
    assert "link[0] !== '/'" in guard and "link[1] === '/'" in guard and "charCodeAt(0) < 0x20" in guard

    link = notify.outcome_link(_summary(), _records(("alice/reports/", "moved", {})))
    assert link.startswith("/") and link[1] not in ("/", "\\")
    assert not any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in link)


def test_a_planes_notification_link_gets_NO_registry_row_and_the_registry_says_so():
    """FR-004 AC4 again: the flag gating is verified and CITED, not built. The row derives its gate
    from the link — the route's flag from the registry's nav rows, which carry ``/files`` — and the
    registry records the decision that a row per producer would grow one row per future plane."""
    registry = (_PORTAL / "features" / "feature-flags" / "gatedSurfaces.ts").read_text()

    assert "a row per producer would grow one row per" in registry
    assert "{name: 'Files', kind: 'nav', path: '/files'}" in registry
    row = (_PORTAL / "features" / "notifications" / "NotificationRow.tsx").read_text()
    assert "useCanFollowLink()" in row
    gate = (_PORTAL / "features" / "feature-flags" / "linkFlags.ts").read_text()
    assert "for (const [path, flag] of NAV_PATH_FLAGS)" in gate


# ── The payload ───────────────────────────────────────────────────────────────────────────


def test_the_request_id_rides_on_EVERY_payload_including_a_clean_runs():
    """A reader settles its in-flight record by matching it, and a clean run has nothing to
    re-submit — so scoping the field to what a re-submit needs would leave successful operations
    unsettled and a per-space gate held until the machine's ceiling."""
    payload = notify.outcome_payload(_summary(), _records(("alice/reports/", "moved", {})), "r-1")

    assert payload["requestId"] == "r-1"
    assert "conflicts" not in payload


def test_the_payload_carries_what_a_RE_SUBMIT_needs_and_the_source_space_is_part_of_it():
    """The source is not derivable from an absolute key, and ``kind`` and ``targetName`` are
    required by the request contract — a rename's target name has no other source at all."""
    payload = notify.outcome_payload(
        _summary(), _records(("alice/reports/", "conflict", {"sample": ["reports/x"], "more": True})), "r-1"
    )

    assert payload["operation"] == "move"
    assert payload["source"] == {"kind": "personal", "name": "alice"}
    assert payload["destination"] == {"kind": "shared", "name": "finance", "prefix": "finance/reports/"}
    assert payload["conflicts"] == [
        {
            "itemKey": "alice/reports/",
            "kind": "folder",
            "targetName": "archive-2026",
            "sample": ["reports/x"],
            "more": True,
        }
    ]


def test_a_delete_carries_no_destination_block_at_all():
    summary = _summary(operation="delete", destination_prefix=None)

    assert "destination" not in notify.outcome_payload(summary, _records(), "r-1")


def test_the_conflicted_items_are_bounded_by_COUNT_at_ordinary_key_lengths():
    records = _records(*[(f"alice/f{i}.csv", "conflict", {}) for i in range(10)])
    summary = _summary(items=[{"itemKey": f"alice/f{i}.csv", "kind": "file"} for i in range(10)])
    payload = notify.outcome_payload(summary, records, "r-1")

    assert len(payload["conflicts"]) == config.FILE_OPS_NOTIFIED_CONFLICTS
    assert payload["more"] is True, "a bounded list a reader could mistake for the whole one"


def test_the_conflicted_items_are_bounded_by_BYTES_when_the_keys_are_pathological():
    """The bound a count cannot express. One conflicted item is a couple of hundred bytes at
    ordinary key lengths and roughly twelve thousand at this plane's caps, so a run whose keys are
    at S3's own limit carries FEWER than the count allows — or none at all — and says so."""
    key = "\x01" * 1024
    records = _records(*[(key + str(i), "conflict", {"sample": ["s" * 120] * 3}) for i in range(3)])
    summary = _summary(items=[{"itemKey": key + str(i), "kind": "folder"} for i in range(3)])
    payload = notify.outcome_payload(summary, records, "r-1")

    assert len(payload.get("conflicts", [])) < config.FILE_OPS_NOTIFIED_CONFLICTS
    assert payload["more"] is True
    # That this bounded payload is one the WRITER accepts is asserted where the two numbers are
    # compared — test_config_focommon reads the writer's ceiling back out of the Lambda. A second
    # reader of that constant here would be a second place for it to fall out of step.


# ── The emit ──────────────────────────────────────────────────────────────────────────────


def test_one_message_per_run_and_one_dedup_token_for_it(sent):
    """Not one per outcome. A selection at the item cap would otherwise flood an inbox capped at
    200 rows — and the per-outcome rule belongs to the planes that emit one message per outcome."""
    notify.emit_outcomes(
        {
            "requestId": "r-1",
            "actor": {"username": "alice"},
            "summary": _summary(),
            "outcomes": _records(("alice/reports/", "moved", {}), ("alice/q1.csv", "conflict", {})),
        }
    )

    assert len(sent) == 1
    user, message, kwargs = sent[0]
    assert user == "alice"
    assert kwargs["dedup_id"] == "r-1:outcomes"
    assert message.startswith("Moved 1 of 2 items to \"reports\".")
    assert kwargs["payload"]["requestId"] == "r-1"
    assert kwargs["link"] == "/files?space=finance&prefix=finance/reports/"


def test_a_whole_request_FAILURE_also_carries_its_request_id(sent):
    """Same argument, one path over: a run that failed before it reached the producer settles
    nothing otherwise, and a reader's in-flight record for it is held until its own expiry.

    This proves the emitter forwards an id it is handed, and nothing more. The validator builds
    the emitter's event by hand, so whether that event names the id is asserted by driving the
    validator's handler, in its own suite — this test stayed green while every refusal the
    validator sent in production carried no id at all.
    """
    notify.emit_failure(
        {"requestId": "r-2", "actor": {"username": "alice"}, "operation": "move"},
        TerminalError("no_items", "nothing selected"),
        "validate-authorize",
    )

    assert sent[0][2]["payload"] == {"requestId": "r-2"}


@pytest.mark.parametrize(
    "event",
    [{"requestId": "r"}, {"requestId": None, "raw": _pipe()}, _pipe()],
    ids=["the-running-state", "a-recorded-failure-whose-seed-nulled-it", "the-pipe-batch-itself"],
)
def test_the_request_id_is_found_in_every_shape_a_failure_arrives_in(event):
    """The failure terminal is handed the second shape and the timeout door the third, and
    reading only a top-level key answered None on both — which are the failures no outcome
    producer will ever settle instead."""
    assert notify.request_payload(event) == {"requestId": "r"}
    assert notify.request_payload({"requestId": None, "raw": [{"body": "{"}]}) is None


def test_a_delete_whose_items_share_no_folder_falls_back_to_the_space_root():
    """Unreachable through the front door, which refuses a key outside the source root — so the
    fallback is what stops a hand-crafted envelope minting a link to nowhere rather than a case the
    plane produces."""
    for items in ([], [{"itemKey": "no-slash-at-all", "kind": "file"}]):
        summary = _summary(operation="delete", destination_prefix=None, items=items)

        assert notify.outcome_link(summary, _records()) == "/files?prefix=alice/"


def test_a_destination_prefix_with_no_final_segment_still_produces_a_message(sent):
    """Every emit on this path is best-effort: the run has already happened, so a prefix that lost
    its shape must cost the sentence its folder name and nothing more."""
    summary = _summary(destination_prefix="/")
    notify.emit_outcomes(
        {
            "requestId": "r-9",
            "actor": {"username": "alice"},
            "summary": summary,
            "outcomes": _records(("alice/reports/", "moved", {})),
        }
    )

    assert sent[0][1] == "Moved 1 item."


def test_the_EMITTED_payload_never_exceeds_the_budget_it_was_probed_against():
    """The flag is set after the loop, so a probe that omitted it would let every payload carrying
    a dropped conflict finish a few bytes over the budget it had just been checked against."""
    records = _records(*[(f"alice/{'f' * 200}{i}.csv", "conflict", {"sample": ["s" * 120] * 3}) for i in range(9)])
    summary = _summary(items=[{"itemKey": f"alice/{'f' * 200}{i}.csv", "kind": "file"} for i in range(9)])
    payload = notify.outcome_payload(summary, records, "r-1")

    assert payload["more"] is True, "this case is only meaningful when something was dropped"
    assert len(json.dumps(payload).encode()) <= config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES


def test_a_destination_prefix_no_legal_KEY_could_sit_under_is_not_carried():
    """The head's one unbounded term, and the failure it causes is the worst available: nothing
    validates a prefix's LENGTH on the way in, so a hand-crafted envelope would push the payload
    past the writer's ceiling and lose the WHOLE message — on the queue whose dead-letter queue is
    deliberately undrained, after the data had already moved.

    A prefix longer than S3's own key limit cannot produce a legal destination key, so the run it
    describes copied nothing and a re-submit of it would be meaningless.
    """
    summary = _summary(destination_prefix="finance/" + "p" * (config.FILE_OPS_NOTIFIED_PREFIX_BYTES + 1))
    payload = notify.outcome_payload(summary, _records(("alice/reports/", "conflict", {})), "r-1")

    assert "destination" not in payload
    assert payload["requestId"] == "r-1", "the request id rides whatever else does not"

    within = _summary(destination_prefix="finance/" + "p" * 100)
    assert "destination" in notify.outcome_payload(within, _records(), "r-1")
