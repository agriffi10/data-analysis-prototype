"""The two request-shape caps, each COMPUTED against the budget that sizes it.

A cap written as a literal and asserted equal to itself proves nothing — it certifies the number
against no quantity at all, and the wrong-quantity mistake is the one this fleet keeps making. So
each test below names the unit it measures, builds the worst request the cap allows, and checks it
against the real limit with the margin stated.

The chain the byte cap is measured against, which an obvious model gets wrong in two places:

  browser selection -> SQS body -> the Pipe wraps that body as an ESCAPED JSON STRING
  -> StartExecution's 256 KB -> validate-authorize's output state

The escaping is not a rounding error: every quote the selection already spent two bytes on costs
four inside the record, so a quote-heavy selection arrives at twice its measured size. And this
plane's state carries a term file-send's does not — one outcome record per selected item, riding
beside the request from the first verb onward.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from focommon import config

#: Step Functions' limit on an execution input and on any single state.
_STATE_LIMIT = 256 * 1024

#: S3's own maximum key length. The worst selection is every key at this length.
_MAX_KEY_BYTES = 1024

#: A generous Cognito ID token. It rides at the top level of every request.
_MAX_TOKEN_BYTES = 8 * 1024


def _selection(items: int, key_char: str = "k", *, with_names: bool = True) -> list:
    """Builds the worst selection of a given size this plane's contract allows.

    Every key at S3's maximum length, every item a folder, and every item carrying a
    ``targetName`` — which is what makes this plane's item heavier than file-send's and is exactly
    the term a model borrowed from that plane would drop.

    Args:
      items: How many items to build.
      key_char: The character to fill keys with. A control character measures the escaped worst
        case; an ASCII letter measures the comfortable one.
      with_names: Whether every item carries a per-item destination name.

    Returns:
      The selection, as the browser would send it.

    Raises:
      None.
    """
    item = {"kind": "folder", "key": key_char * _MAX_KEY_BYTES}
    if with_names:
        item["targetName"] = key_char * config.MAX_TARGET_NAME
    return [dict(item) for _ in range(items)]


def _serialised(value: object) -> int:
    """Returns the compact JSON byte length of a value.

    Args:
      value: Anything JSON-serialisable.

    Returns:
      The byte length of the UTF-8 form that actually travels — non-ASCII left literal, as both
      the browser's serialiser and the Pipe leave it.

    Raises:
      None.
    """
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def _pipe_record(selection: list) -> int:
    """Returns the size of the execution input the Pipe hands to ``StartExecution``.

    The link an obvious model leaves out. A request over this limit cannot start an execution at
    all: no verb runs, no Catch fires, and nothing notifies anyone — the request dead-letters and
    the actor hears about it from the drain minutes later, if at all.

    Args:
      selection: The selection, as the browser sends it.

    Returns:
      The serialised byte length of the Pipe's forwarded batch.

    Raises:
      None.
    """
    body = json.dumps(
        {
            "requestId": "0" * 36,
            "actor": "t" * _MAX_TOKEN_BYTES,
            "operation": "move",
            "source": {"space": {"kind": "personal", "name": "a" * 64}, "items": selection},
            "destination": {
                "space": {"kind": "shared", "name": "s" * 64},
                "prefix": ("p" * 512) + "/",
            },
            "onConflict": "overwrite",
            "submittedAt": "2026-08-19T12:00:00Z",
        },
        separators=(",", ":"),
    )
    record = [
        {
            "messageId": "m" * 36,
            "receiptHandle": "r" * 1024,
            "body": body,
            "attributes": {"MessageGroupId": "g" * 64, "MessageDeduplicationId": "d" * 36},
            "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:dat-prod-file-ops-requests.fifo",
        }
    ]
    return _serialised(record)


def _validated_state(selection: list) -> int:
    """Returns the size of validate-authorize's output at its worst allowed shape.

    **Includes the outcome list**, which is the term that separates this plane from the one its
    shape was borrowed from: every selected item carries a record from here to the notification, so
    the selection is effectively on the state twice.

    Args:
      selection: The selection at the cap.

    Returns:
      The serialised byte length.

    Raises:
      None.
    """
    outcomes = [
        {
            "itemKey": item["key"],
            "label": item.get("targetName", ""),
            "outcome": "protected",
            "reason": "results_folder_not_deletable",
        }
        for item in selection
    ]
    return _serialised(
        {
            "requestId": "0" * 36,
            "actor": {"username": "a" * 64},
            "operation": "move",
            "source": {"bucket": "b" * 63, "root": ("r" * 63) + "/", "items": selection},
            "destination": {"bucket": "b" * 63, "prefix": ("p" * 512) + "/"},
            "onConflict": "overwrite",
            "submittedAt": "2026-08-19T12:00:00Z",
            "outcomes": outcomes,
            "lock": {"attempt": 20, "acquired": True, "exhausted": False, "etags": ['"e"' * 8] * 2},
        }
    )


def _items_at_the_byte_cap(key_char: str) -> list:
    """Returns the largest selection of this character the byte cap admits.

    Args:
      key_char: The character every key is filled with.

    Returns:
      The selection.

    Raises:
      None.
    """
    count = config.FILE_OPS_MAX_ITEMS
    while count > 1 and _serialised(_selection(count, key_char)) > config.FILE_OPS_MAX_SELECTION_BYTES:
        count -= 1
    return _selection(count, key_char)


def test_the_item_cap_fits_the_verbs_own_timeout_at_the_MEASURED_per_item_cost():
    """The unit is one item's validation, and this MEASURES it rather than describing it.

    The budget is validate-authorize's Lambda timeout. The work charged per item is everything this
    verb does with an item and nothing it does not: two containment checks, the derived-destination
    key, and the four protected-location rules. There is no listing in this verb, so nothing here is
    charged per OBJECT — the caps that bound the expansion belong to the verb that lists.

    An earlier version asserted ``FILE_OPS_MAX_ITEMS % 25 == 0``, which is satisfied by every
    multiple of 25 from 100 to 1175 and certifies the number against no quantity at all — the exact
    pattern this module's own docstring opens by condemning.

    The margin is enormous, and that is the honest result rather than a reason to raise the cap:
    string work over a few hundred items is microseconds against a 15-second budget, so what really
    bounds this number is the byte cap below and the product reading — the file browser pages at 25,
    so 200 is eight full pages of selection.
    """
    import time

    from focommon import paths, protected

    root = "alice/"
    items = [
        {"kind": "folder", "key": f"alice/reports/2026/quarter-{n:04d}/"}
        for n in range(config.FILE_OPS_MAX_ITEMS)
    ]

    started = time.perf_counter()
    for item in items:
        paths.assert_inside_root(root, item["key"])
        paths.has_dot_segment(item["key"])
        paths.derived_destination_key("alice/out/", item)
        protected.destination_refusal(root, "alice/out/", "personal")
        protected.source_refusal(root, item["key"], "move", "personal")
        protected.settings_source_refusal(root, item["key"])
        protected.marker_refusal(item["key"])
    elapsed = time.perf_counter() - started

    verb_timeout_seconds = 15
    assert elapsed < verb_timeout_seconds / 10, (
        f"validating {config.FILE_OPS_MAX_ITEMS} items took {elapsed:.3f}s against a "
        f"{verb_timeout_seconds}s budget — the cap no longer leaves an order of magnitude"
    )
    assert config.FILE_OPS_MAX_ITEMS % 25 == 0, "the cap should be a whole number of browser pages"


def test_the_byte_cap_admits_its_worst_selection_through_the_pipe():
    """The whole chain, measured on the ESCAPED form, at the cap.

    A control character costs six bytes escaped where an ASCII letter costs one, so this is the
    selection that actually decides the number — and it is the case a count cap cannot see.
    """
    worst = _items_at_the_byte_cap("\x01")

    assert _serialised(worst) <= config.FILE_OPS_MAX_SELECTION_BYTES
    assert _pipe_record(worst) < _STATE_LIMIT, (
        f"a selection at the byte cap reaches StartExecution at {_pipe_record(worst)} bytes, "
        f"over the {_STATE_LIMIT}-byte limit — the execution could not start at all"
    )


def test_the_byte_cap_leaves_the_validated_state_room_for_the_outcome_list():
    """The term borrowed models drop: every selected item rides twice.

    Once as the item and once as its outcome record, from this verb to the notification. A cap
    sized against the request alone would pass every check here and breach the state limit at the
    first verb that adds one.
    """
    worst = _items_at_the_byte_cap("\x01")

    assert _validated_state(worst) < _STATE_LIMIT, (
        f"the validated state reaches {_validated_state(worst)} bytes with the outcome list, "
        f"over the {_STATE_LIMIT}-byte limit"
    )


def test_each_cap_binds_a_case_the_other_leaves_open():
    """Both caps are needed, and this is what proves neither is redundant.

    They bind on OPPOSITE selections, which is the whole reason there are two:

      - **Short keys, many items.** A realistic selection — a full page of ordinary filenames —
        is a few KB, nowhere near the byte cap, so the ITEM cap is the only thing bounding the
        per-item work.
      - **Long keys, few items.** At S3's maximum key length the byte cap admits an order of
        magnitude fewer than the item cap allows, so it binds first and the item cap never fires.

    An earlier version of this test asserted that a selection of ``FILE_OPS_MAX_ITEMS`` items at
    the maximum key length fits the byte cap. It does not — 200 maximal keys is ~264 KB of plain
    ASCII — and the mistake is worth recording rather than quietly fixing: it is the same
    wrong-quantity error the caps exist to prevent, made about the caps themselves.
    """
    realistic = [{"kind": "file", "key": f"alice/reports/2026/q4-{n:04d}.csv"} for n in range(config.FILE_OPS_MAX_ITEMS)]

    assert _serialised(realistic) < config.FILE_OPS_MAX_SELECTION_BYTES, (
        "an ordinary full-size selection should be bounded by the item cap, not the byte cap"
    )
    assert len(realistic) == config.FILE_OPS_MAX_ITEMS

    assert len(_items_at_the_byte_cap("k")) < config.FILE_OPS_MAX_ITEMS
    assert len(_items_at_the_byte_cap("\x01")) < len(_items_at_the_byte_cap("k"))


def test_the_stale_threshold_exceeds_the_machine_ceiling():
    """A threshold below the ceiling steals a RUNNING execution's lock.

    Asserting only that a ceiling "exists" is satisfied by any threshold, which is how this ships
    broken.
    """
    assert config.STALE_LOCK_SECONDS > config.MACHINE_TIMEOUT_SECONDS


def test_the_give_up_bound_is_strictly_under_the_machine_ceiling():
    """The waiter is a state INSIDE the machine, so the ceiling kills it before its give-up can
    fire unless this holds — and the failure surfaces as a bare timeout rather than the refusal the
    waiting design promises.

    The naive chain is unsatisfiable and must not be re-derived: requiring the give-up to outlast
    the steal threshold, which itself exceeds the ceiling, forces the give-up past the ceiling. It
    does not need to outlast a steal, because the waiter performs the steal.

    The per-attempt cost is the ``Wait`` plus the acquire Task's own worst case under this fleet's
    retry block: three retries over 2/4/8 seconds, so ``4 x timeout + 14``.
    """
    acquire_timeout = 15
    worst_attempt = config.LOCK_WAIT_SECONDS + (4 * acquire_timeout + 14)
    give_up = config.LOCK_MAX_ATTEMPTS * worst_attempt

    assert give_up < config.MACHINE_TIMEOUT_SECONDS, (
        f"a waiter can burn {give_up}s against a {config.MACHINE_TIMEOUT_SECONDS}s ceiling"
    )


def test_the_protected_folder_lists_are_not_a_union():
    """The three browser lists differ ON PURPOSE, and unioning them is the wrong repair.

    The clearest case is the one this asserts: ``athenaresults`` is picker-locked AND undeletable,
    and copying out of it is still permitted. ``saved_queries`` is the inverse — undeletable but a
    perfectly good destination. If either of these ever became true of both lists at once, the
    per-(side x operation) rules would have been quietly collapsed into one.
    """
    picker = set(config.PICKER_LOCKED_FOLDERS)
    undeletable = set(config.UNDELETABLE_ROOT_FOLDERS)

    assert picker != undeletable
    assert "saved_queries" in undeletable and "saved_queries" not in picker
    assert config.USER_SETTINGS_FOLDER in picker and config.USER_SETTINGS_FOLDER not in undeletable


def test_the_browsers_mirrored_caps_are_never_more_permissive_than_these():
    """The browser refuses early so the common case fails fast and legibly, but it is not the
    authority — and it cannot measure the same quantity anyway.

    Its byte cap is over ``JSON.stringify(items)`` alone; this one is over the whole chain, which
    includes the actor's token, the destination and one outcome record per item. So the property
    that matters is not equality but DIRECTION: a local refusal must never admit a request the
    plane would refuse, or the user gets a notification minutes later where they could have had a
    message immediately.
    """
    import pathlib
    import re

    service = (
        pathlib.Path(__file__).resolve().parents[2]
        / "apps"
        / "portal"
        / "src"
        / "features"
        / "file-browser"
        / "fileOps.service.ts"
    ).read_text()

    browser_items = int(re.search(r"FILE_OPS_MAX_ITEMS = (\d+)", service).group(1))
    factors = re.search(r"FILE_OPS_MAX_SELECTION_BYTES = ([\d* ]+);", service).group(1)
    browser_bytes = 1
    for factor in factors.split("*"):
        browser_bytes *= int(factor.strip())

    assert browser_items <= config.FILE_OPS_MAX_ITEMS
    assert browser_bytes <= config.FILE_OPS_MAX_SELECTION_BYTES


def test_the_two_runtimes_MEASURE_the_same_selection_the_same_way():
    """Equal constants are not enough, and this is the test that would have caught it.

    Python escapes non-ASCII by default and JavaScript does not, so the identical selection of
    accented filenames measured 26 KB in the browser and 66 KB here — the browser accepting
    selections this plane then refused by notification, which is the outcome the browser's own cap
    exists to prevent. Two matching numbers said nothing about it.

    Asserted on the SERIALISER, against the byte length JavaScript produces for the same input:
    compact separators, non-ASCII left literal.
    """
    selection = [{"kind": "file", "key": "alice/" + ("\u00e9" * 60)} for _ in range(170)]

    # What `new TextEncoder().encode(JSON.stringify(items))` yields for this input, computed in
    # Node rather than derived from this side — a value taken from Python would only prove Python
    # is self-consistent.
    javascript_bytes = 25671

    assert _serialised(selection) == javascript_bytes
