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
import math
import os
import pathlib
import re
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

#: The module whose ``locals.tf`` carries the memory and timeout every expansion cap is computed
#: against. Read back rather than restated, so lowering one without lowering the cap fails the
#: build rather than the invocation.
_MODULE = pathlib.Path(__file__).resolve().parents[2] / "infra" / "modules" / "file-ops"

#: A parsed dict is several times the size of the bytes it came from — the same allowance the two
#: neighbouring planes compute their own object caps with.
_PARSED_OBJECT_OVERHEAD = 3

#: A pessimistic ``HeadObject`` round trip. The guard's whole cost is round trips, not bytes.
_HEAD_LATENCY_SECONDS = 0.1

#: botocore's default ``max_pool_connections``. Asserted against the real value where botocore is
#: importable, so this cannot quietly become a restatement of a number that has since moved.
_BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS = 10


def _verb_row(name: str) -> tuple[int, int]:
    """Returns one verb's ``(timeout, memory)`` as Terraform actually configures it.

    Args:
      name: The function suffix, as ``locals.tf`` keys it.

    Returns:
      The timeout in seconds and the memory in MB.

    Raises:
      AssertionError: When the row is not there, so a renamed verb fails loudly rather than
        silently skipping every bound computed from it.
    """
    row = re.search(
        rf'"{name}"\s*=\s*{{[^}}]*timeout\s*=\s*(\d+),\s*memory\s*=\s*(\d+)',
        (_MODULE / "locals.tf").read_text(),
    )
    assert row, f"no locals.tf row for {name}"
    return int(row.group(1)), int(row.group(2))


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


# ── The three expansion caps, each against the budget that sizes it ──────────


def _plan_entry_bytes() -> int:
    """One plan object at S3's worst-case key length, serialised.

    Pessimistic in a way real entries cannot be: the destination key is DERIVED from the source key,
    so both cannot independently be 1024 bytes. Over-counting is the safe direction for a bound.
    """
    entry = {
        "srcBucket": "b" * 63,
        "srcKey": "s" * _MAX_KEY_BYTES,
        "relKey": "r" * _MAX_KEY_BYTES,
        "size": 10 * 1024**3,
        "etag": '"' + ("e" * 32) + '"',
        "destBucket": "d" * 63,
        "destKey": "d" * _MAX_KEY_BYTES,
    }
    return len(json.dumps(entry, separators=(",", ":")).encode())


#: Every verb that holds the parsed plan in memory. The cap is the MINIMUM over all of them, so a
#: new plan-holder that is not listed here would have FILE_OPS_MAX_OBJECTS certify memory it never
#: checked — which is the exact failure this budget exists to prevent.
_PLAN_HOLDING_VERBS = (
    "inspect-source",
    "check-destinations",
    "build-transfer-manifest",
    "collect-transfer-results",
    "delete-source",
)


def _memory_budget_objects() -> int:
    """How many objects the smallest of the plan-holding verbs can hold at once.

    The expansion builds the whole list of dicts, serialises it to a string and encodes that — three
    live copies at the moment of the write — and every verb after it loads the same plan back. Half
    the configured memory is left for the interpreter, boto3 and its response buffers, which is not
    a rounding allowance: a cold Lambda with botocore loaded is already tens of megabytes.
    """
    per_object = _plan_entry_bytes() * (_PARSED_OBJECT_OVERHEAD + 2)
    memory = min(_verb_row(verb)[1] for verb in _PLAN_HOLDING_VERBS)
    return int((memory * 1024**2 / 2) // per_object)


def test_every_verb_that_HOLDS_THE_PLAN_is_in_the_memory_budget():
    """The budget above is a ``min()``, so a plan-holder left out of it is invisible to the cap.

    Read from the SOURCE rather than restated: any file-ops verb importing ``plan`` and calling
    ``load`` holds the parsed plan, and this asserts the list of them is exactly what the budget
    measures. A sixth plan-holder therefore fails the build rather than the invocation.
    """
    holders = set()
    for verb_dir in sorted((_MODULE.parents[2] / "lambdas").glob("file-ops-*")):
        for source in verb_dir.glob("file_ops_*.py"):
            body = source.read_text()
            if "plan.load(" in body or "plan.write(" in body:
                holders.add(verb_dir.name.removeprefix("file-ops-"))

    assert holders == set(_PLAN_HOLDING_VERBS), (
        f"the plan-holding verbs are {sorted(holders)} but the memory budget measures "
        f"{sorted(_PLAN_HOLDING_VERBS)} — a plan-holder outside the min() is one the object cap "
        "never checked"
    )


def _guard_budget_objects() -> int:
    """How many destinations the guard can head inside its own timeout.

    THE SCHEDULABLE UNIT IS ONE HEAD ON ONE WORKER, and the rounds are what the pool costs: a head
    holds nothing, so capacity is ``concurrency x timeout / latency`` rather than anything about
    bytes. The worst case is the ordinary one — an item whose destinations are all clear, where the
    short-circuit saves nothing and every key is headed.
    """
    timeout = _verb_row("check-destinations")[0]
    rounds = (timeout / 2) / _HEAD_LATENCY_SECONDS
    return int(rounds * config.FILE_OPS_HEAD_CONCURRENCY)


def test_the_object_cap_is_the_MINIMUM_of_two_budgets_held_by_two_verbs():
    """WHAT SIZES FILE_OPS_MAX_OBJECTS, computed rather than asserted, and computed TWICE.

    Naming only the memory budget is how a cap comes to certify something it never checked: if
    memory permitted 200,000 objects the guard could not head them at any concurrency inside
    Lambda's own 900-second ceiling. Both are computed here and both must admit the cap.
    """
    memory_budget = _memory_budget_objects()
    guard_budget = _guard_budget_objects()

    assert memory_budget >= config.FILE_OPS_MAX_OBJECTS, (
        f"a worst-case plan of {config.FILE_OPS_MAX_OBJECTS} objects does not fit the memory "
        f"locals.tf configures (it holds {memory_budget}) — raise the memory or lower the cap"
    )
    assert guard_budget >= config.FILE_OPS_MAX_OBJECTS, (
        f"the guard cannot head {config.FILE_OPS_MAX_OBJECTS} destinations inside its timeout (it "
        f"manages {guard_budget}) — raise the timeout in locals.tf or lower the cap"
    )


def test_the_guard_is_the_budget_that_BINDS_and_the_memory_one_is_slack():
    """Which of the two binds is a fact about the design, not a detail: the number is the guard's,
    so the reflex of raising the verb's memory buys nothing at all. Recorded as an assertion because
    the alternative is a comment that stops being true silently."""
    assert _guard_budget_objects() < _memory_budget_objects()


def test_the_guards_pool_fits_inside_the_clients_connection_pool():
    """THE TERM THE OBVIOUS MODEL SKIPS. "Workers x timeout / latency" says to widen the pool until
    the arithmetic fits — but this plane creates no client of its own; it uses
    ``cpcommon.clients.s3()``, which passes no ``Config``, so botocore's default
    ``max_pool_connections`` is the real ceiling. Threads past it do not each get a connection:
    they contend, and urllib3 opens and discards sockets rather than reusing them, so a wider pool
    buys throughput the client cannot deliver while every bound computed from it reads as satisfied.
    """
    assert _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS >= config.FILE_OPS_HEAD_CONCURRENCY

    try:
        from botocore.config import Config
    except ImportError:
        return
    assert Config().max_pool_connections == _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS, (
        "botocore's default connection pool has moved; FILE_OPS_HEAD_CONCURRENCY was computed "
        "against the old value"
    )


def test_the_expansions_timeout_is_sized_PER_ITEM_rather_than_per_page():
    """The term the obvious model drops. A ``file`` item costs its own serial ``HeadObject``, so 200
    files is 200 round trips where 20,000 objects in one folder is 20 listing pages — the item count
    dominates, and a bound computed per page would be twenty times too generous."""
    timeout = _verb_row("inspect-source")[0]
    heads = config.FILE_OPS_MAX_ITEMS * config.FILE_OPS_ITEM_ROUND_TRIP_SECONDS
    pages = math.ceil(config.FILE_OPS_MAX_OBJECTS / 1000) * config.FILE_OPS_ITEM_ROUND_TRIP_SECONDS

    assert heads > pages, "the per-page reading has overtaken the per-item one — re-derive this"
    assert heads + pages < timeout / 2, (
        f"a worst-case expansion is ~{heads + pages:.0f}s against inspect-source's {timeout}s"
    )


def _serial_verb_seconds() -> int:
    """Every verb timeout a run spends END TO END, read back from locals.tf rather than restated.

    The Map's own batch verb is deliberately absent: its time is inside the copy makespan, which is
    computed from the Map's concurrency, and counting it here would charge it twice.
    """
    return sum(
        _verb_row(verb)[0]
        for verb in (
            "validate-authorize",
            "inspect-source",
            "check-destinations",
            "check-destinations",
            "build-transfer-manifest",
            "collect-transfer-results",
            "delete-source",
            "finalise-outcomes",
            "notify-failure",
        )
    )


def _give_up_seconds() -> int:
    """The longest a waiter can spend before it refuses, which the earlier budget omitted entirely.

    A run that waits for the space and THEN copies is not an alternative worst case to a run that
    copies — it is the ordinary sequence, so the two terms add.
    """
    acquire_timeout = _verb_row("acquire-lock")[0]
    worst_attempt = config.LOCK_WAIT_SECONDS + (4 * acquire_timeout + 14)
    return config.LOCK_MAX_ATTEMPTS * worst_attempt


def test_the_JOINT_budget_fits_the_machines_own_ceiling():
    """SPEC-187 FR-001's joint budget, computed for the first time against a machine that copies.

    Every term a single execution can spend, added: the lock give-up, TWO guard sweeps, every other
    serial verb's timeout, the copy's makespan at the byte cap, and the deletion. The copy's
    denominator is a MAKESPAN and not an aggregate bandwidth — one object is handed WHOLE to one
    worker and the multipart loop inside it is serial, so the rate is the Map's concurrency times
    one stream, not the far larger number multiplying every constant together suggests.

    **The deletion term is delete-source's TIMEOUT, not a computed makespan**, because what the
    ceiling has to budget is what that Task can actually spend.

    This is the computation that moved FILE_OPS_MAX_TOTAL_BYTES from 3 TiB to 2 TiB. Raising the
    ceiling instead would have raised STALE_LOCK_SECONDS with it, and a longer stale window on a
    shared space blocks everyone who works in it.
    """
    from cpcommon.transfer.config import (
        CONSERVATIVE_STREAM_BYTES_PER_SECOND,
        COPY_TIMEOUT_SECONDS,
        MAP_MAX_CONCURRENCY,
    )

    copy_seconds = config.FILE_OPS_MAX_TOTAL_BYTES / (
        MAP_MAX_CONCURRENCY * CONSERVATIVE_STREAM_BYTES_PER_SECOND
    )
    run = copy_seconds + _serial_verb_seconds() + _give_up_seconds()

    assert run < config.MACHINE_TIMEOUT_SECONDS, (
        f"a worst-case run is ~{run:,.0f}s against a {config.MACHINE_TIMEOUT_SECONDS}s ceiling — "
        "lower FILE_OPS_MAX_TOTAL_BYTES, or raise the ceiling and STALE_LOCK_SECONDS together"
    )
    assert config.FILE_OPS_MAX_OBJECT_BYTES / CONSERVATIVE_STREAM_BYTES_PER_SECOND < (
        COPY_TIMEOUT_SECONDS / 2
    ), "one object is one worker, and the largest legal one no longer fits a single batch"


def test_the_lock_wait_is_a_TERM_of_that_budget_rather_than_an_alternative_to_it():
    """The term the first version of this budget left out, pinned so it cannot quietly leave again.

    Waiting 2,000s for a busy space and then copying 2 TiB is one execution, not two scenarios.
    Without the give-up term the budget read as satisfied at a cap that was in fact ~2,000s over.
    """
    assert _give_up_seconds() > 0
    from cpcommon.transfer.config import (
        CONSERVATIVE_STREAM_BYTES_PER_SECOND,
        MAP_MAX_CONCURRENCY,
    )

    without = config.FILE_OPS_MAX_TOTAL_BYTES / (
        MAP_MAX_CONCURRENCY * CONSERVATIVE_STREAM_BYTES_PER_SECOND
    ) + _serial_verb_seconds()

    assert without + _give_up_seconds() < config.MACHINE_TIMEOUT_SECONDS


def test_the_transfer_maps_rendered_numbers_equal_the_constants_the_batch_verb_is_bounded_by():
    """Terraform cannot import Python, so the Map's shape lives in locals.tf as literals. Two homes
    for one number is how a batch silently grows past the limit it was sized against."""
    from cpcommon.transfer import config as transfer_config

    locals_tf = (_MODULE / "locals.tf").read_text()
    for name, expected in (
        ("transfer_max_items_per_batch", transfer_config.MAX_ITEMS_PER_BATCH),
        ("transfer_map_max_concurrency", transfer_config.MAP_MAX_CONCURRENCY),
    ):
        found = re.search(rf"{name}\s*=\s*(\d+)", locals_tf)
        assert found, f"{name} is not in locals.tf"
        assert int(found.group(1)) == expected, f"{name} disagrees with cpcommon.transfer.config"

    assert _verb_row("copy-objects")[0] == transfer_config.COPY_TIMEOUT_SECONDS, (
        "the batch verb's timeout is what its own batch-size bound is computed against"
    )


def test_the_per_object_cap_binds_a_case_the_byte_cap_cannot_see():
    """A total-bytes makespan certifies the DISTRIBUTED case only, and this is the selection that
    satisfies it while being impossible.

    ONE object of the whole byte cap is legal under that cap and under the object COUNT cap, and it
    is one worker's serial work: at the conservative per-stream rate it is over thirty hours,
    against a three-hour ceiling. Nothing but a per-object cap can see it.
    """
    from cpcommon.transfer.config import CONSERVATIVE_STREAM_BYTES_PER_SECOND

    one_enormous_object = config.FILE_OPS_MAX_TOTAL_BYTES

    assert (
        one_enormous_object / CONSERVATIVE_STREAM_BYTES_PER_SECOND
        > config.MACHINE_TIMEOUT_SECONDS
    ), "the case this cap exists for has gone away; re-derive it rather than deleting it"
    assert one_enormous_object > config.FILE_OPS_MAX_OBJECT_BYTES


# ── The outcome list, and the sample it may carry ────────────────────────────


def _state_with_outcomes(selection: list, sample: list | None) -> int:
    """Returns the size of the state the destination guard returns, at its worst allowed shape.

    Every selected item rides twice — as the item and as its outcome record — and a conflicted one
    rides three times, because its record carries a sample of the keys it collided with.
    """
    outcomes = []
    for item in selection:
        record = {"itemKey": item["key"], "label": item["key"], "outcome": "cleared"}
        if sample is not None:
            record.update({"outcome": "conflict", "reason": "destination_occupied", "sample": sample, "more": True})
        outcomes.append(record)
    return _serialised(
        {
            "requestId": "0" * 36,
            "actor": {"username": "a" * 64},
            "operation": "move",
            "source": {"bucket": "b" * 63, "root": ("r" * 63) + "/", "items": selection},
            "destination": {"bucket": "b" * 63, "prefix": ("p" * 512) + "/"},
            "onConflict": "overwrite",
            "submittedAt": "2026-08-19T12:00:00Z",
            "planKey": f"file-ops/{'0' * 36}/plan.json",
            "itemCount": len(selection),
            "objectCount": config.FILE_OPS_MAX_OBJECTS,
            "totalBytes": config.FILE_OPS_MAX_TOTAL_BYTES,
            "checkedCount": config.FILE_OPS_MAX_OBJECTS,
            "outcomes": outcomes,
            "lock": {"attempt": 20, "acquired": True, "exhausted": False, "etags": ['"e"' * 8] * 2},
        }
    )


def test_the_sample_size_is_DERIVED_from_the_state_budget_rather_than_chosen():
    """WHAT SIZES FILE_OPS_CONFLICT_SAMPLE, and it is measured on the escaped worst case.

    ``FILE_OPS_MAX_ITEMS`` bounds the number of entries and says nothing about bytes: S3 keys reach
    1024 bytes and are arbitrary UTF-8, so JSON escaping expands a quote to two bytes and a control
    character to six. The worst case is every item at the byte cap, every one of them conflicted,
    and every sampled path as long as the shortening rule allows.
    """
    for key_char in ("\x01", "k"):
        worst = _items_at_the_byte_cap(key_char)
        sample = [key_char * config.FILE_OPS_SAMPLE_PATH_CHARS] * config.FILE_OPS_CONFLICT_SAMPLE
        measured = _state_with_outcomes(worst, sample)

        assert measured < _STATE_LIMIT, (
            f"the guard's state reaches {measured} bytes with {len(worst)} conflicted items, over "
            f"the {_STATE_LIMIT}-byte limit — lower FILE_OPS_CONFLICT_SAMPLE or the path length"
        )


def test_the_shortening_rule_is_what_makes_a_SAMPLE_of_more_than_one_possible():
    """The measurement that decided the number, kept because it is the whole argument for shortening
    a path a user might rather see whole: at full key length the budget admits ONE per item, and the
    third is over the limit. A future reader raising the sample size will find this rather than
    rediscovering it in production, where the state limit is a caught failure on a request that has
    already done all of its work.
    """
    worst = _items_at_the_byte_cap("k")
    full_length = ["k" * _MAX_KEY_BYTES]

    assert _state_with_outcomes(worst, full_length) < _STATE_LIMIT
    assert _state_with_outcomes(worst, full_length * 2) > _STATE_LIMIT


# ── The SECOND budget: bytes on the state, which the transfer is what stresses ────────────


def _state_after_the_transfer(selection: list, sample: list | None) -> int:
    """Returns the size of the worst state a run reaches AFTER the copy and the deletion.

    The three terms this spec adds are what make this measurable at all: the deletable item keys,
    the per-item object counts and the per-item deletion records. Measured with every item
    CONFLICTED, because a conflict record carries a sample on top of everything else.
    """
    outcomes = []
    for item in selection:
        record = {"itemKey": item["key"], "label": item["key"], "outcome": "cleared"}
        if sample is not None:
            record.update(
                {
                    "outcome": "conflict",
                    "reason": "destination_occupied_late",
                    "sample": sample,
                    "more": True,
                }
            )
        outcomes.append(record)
    return _serialised(
        {
            "requestId": "0" * 36,
            "actor": {"username": "a" * 64},
            "operation": "move",
            "source": {"bucket": "b" * 63, "root": ("r" * 63) + "/", "items": selection},
            "destination": {"bucket": "b" * 63, "prefix": ("p" * 512) + "/"},
            "onConflict": "overwrite",
            "submittedAt": "2026-08-19T12:00:00Z",
            "planKey": f"file-ops/{'0' * 36}/plan.json",
            "transferResultsKey": f"file-ops/{'0' * 36}/{'e' * 80}/transfer-results.json",
            "transfer": {
                "manifestBucket": "b" * 63,
                "manifestKey": f"file-ops/{'0' * 36}/{'e' * 80}/transfer-manifest.jsonl",
                "resultsBucket": "b" * 63,
                "resultsPrefix": f"file-ops/{'0' * 36}/results",
                "itemCount": config.FILE_OPS_MAX_OBJECTS,
                "itemLines": [
                    {"itemKey": item["key"], "lines": config.FILE_OPS_MAX_OBJECTS}
                    for item in selection
                ],
            },
            "mapRun": {
                "MapRunArn": "arn:aws:states:us-east-1:1:mapRun:file-ops/" + ("m" * 40),
                "ResultWriterDetails": {"Bucket": "b" * 63, "Key": "k" * 200},
            },
            "deletableCount": len(selection),
            "deletedCount": config.FILE_OPS_MAX_OBJECTS,
            "guardPass": 2,
            "itemCount": len(selection),
            "objectCount": config.FILE_OPS_MAX_OBJECTS,
            "totalBytes": config.FILE_OPS_MAX_TOTAL_BYTES,
            "checkedCount": config.FILE_OPS_MAX_OBJECTS,
            "outcomes": outcomes,
            "execution": {"arn": "arn:aws:states:us-east-1:1:execution:file-ops:" + "e" * 80,
                          "name": "e" * 80},
            "lock": {"attempt": 20, "acquired": True, "exhausted": False, "etags": ['"e"' * 8] * 2},
        }
    )


def test_the_state_still_fits_AFTER_the_transfer_and_the_deletion():
    """WHY the deletable list, the per-item counts and the deletion records travel BY POINTER.

    Measured on the state, they are ~156 KB on top of a state already carrying the selection and one
    outcome record per item — over the limit, at the caps this plane already accepts. And the place
    it would break is the worst one available: ``States.DataLimitExceeded`` on the collector's
    result lands AFTER the copy, and on delete-source's result AFTER the deletion. That error
    escapes every ``Catch``, so the user would be told nothing at all about an operation that had
    already moved or removed their data.

    This asserts the state as it is actually built — scalars and keys only — still fits.
    """
    for key_char in ("\x01", "k"):
        worst = _items_at_the_byte_cap(key_char)
        sample = [key_char * config.FILE_OPS_SAMPLE_PATH_CHARS] * config.FILE_OPS_CONFLICT_SAMPLE
        measured = _state_after_the_transfer(worst, sample)

        assert measured < _STATE_LIMIT, (
            f"the post-deletion state reaches {measured} bytes with {len(worst)} items, over the "
            f"{_STATE_LIMIT}-byte limit — something else has to travel by pointer"
        )


def test_the_three_pointer_borne_terms_would_NOT_have_fitted_on_the_state():
    """The measurement that decided the pointer, kept because it is the whole argument for one.

    A future reader who finds ``deletableCount`` beside a key in S3 and thinks the list itself would
    be simpler will find this instead of rediscovering it in production — where the failure arrives
    after the data has already moved.
    """
    worst = _items_at_the_byte_cap("k")
    sample = ["k" * config.FILE_OPS_SAMPLE_PATH_CHARS] * config.FILE_OPS_CONFLICT_SAMPLE
    on_the_state = _state_after_the_transfer(worst, sample) + _serialised(
        {
            "deletable": [item["key"] for item in worst],
            "items": [
                {"itemKey": item["key"], "objects": 1200, "failed": 0} for item in worst
            ],
            "deletions": [
                {"itemKey": item["key"], "deleted": 1200, "failed": 0, "reason": ""}
                for item in worst
            ],
        }
    )

    assert on_the_state > _STATE_LIMIT, (
        "the three terms now fit on the state; re-derive the decision rather than deleting the "
        "pointer, because the caps that made them too big may simply have moved"
    )
