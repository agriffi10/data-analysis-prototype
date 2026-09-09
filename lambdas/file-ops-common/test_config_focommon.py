"""Every file-ops number a comment promises is checked, checked here.

Three subjects: the two request-shape caps and the three expansion ones, each COMPUTED against
the budget that sizes it; the three values Python and Terraform both hold that nothing else pins,
each read back out of ``locals.tf``; and the protected-folder lists, pinned member for member.
(``PLAN_PREFIX`` is a fourth such mirror and is NOT here — ``test_file_ops_admin_list_grant`` holds
it to the Terraform and to the bucket's lifecycle rule, which is the same check in a better place.)

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
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from cpcommon import config as cp_config
from focommon import config, delete

#: Step Functions' limit on an execution input and on any single state.
_STATE_LIMIT = cp_config.STATE_PAYLOAD_LIMIT_BYTES

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
        silently skipping every bound computed from it — or when there is more than one.

    ANCHORED TO THE START OF A LINE, and matched over one line only. Unanchored, the first match
    wins, and in a file this heavily commented a `# was "inspect-source" = { ... timeout = 600 }`
    left above a lowered row is an ordinary edit that would silently freeze every bound computed
    from that verb at the old number. The multiplicity is asserted for the same reason: a row
    duplicated during an edit would resolve to whichever copy came first.
    """
    rows = re.findall(
        rf'^[^\S\n]*"{name}"\s*=\s*{{[^}}\n]*timeout\s*=\s*(\d+),\s*memory\s*=\s*(\d+)',
        (_MODULE / "locals.tf").read_text(),
        re.MULTILINE,
    )
    assert len(rows) == 1, f"locals.tf has {len(rows)} rows for {name}, expected exactly one"
    return int(rows[0][0]), int(rows[0][1])


def _local(name: str) -> str:
    """Returns one scalar ``locals.tf`` value as Terraform actually renders it.

    Args:
      name: The local's name, as ``locals.tf`` declares it.

    Returns:
      The rendered value with its surrounding quotes stripped, so a string local and a numeric one
      are read the same way.

    Raises:
      AssertionError: When the local is absent or has been reshaped, so a rename fails loudly
        rather than leaving the comparison below vacuous.
    """
    found = re.search(
        rf'^\s*{name}\s*=\s*"?([^"\n]+?)"?\s*$',
        (_MODULE / "locals.tf").read_text(),
        re.MULTILINE,
    )
    assert found, f"locals.tf declares no {name}"
    return found.group(1)


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
      The byte length of the form that actually travels — non-ASCII ESCAPED, because the API
      re-serialises the body with the default escaping one hop before the Pipe. Measuring the
      literal form counted an accented key at two bytes where the wire spends six.

    Raises:
      None.
    """
    return len(json.dumps(value, separators=(",", ":")).encode())


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

    **The timing clause cannot fail at any timeout Lambda accepts, and that is the measurement
    rather than a defect.** Validating the whole selection takes under a millisecond against a
    budget of 1.5 seconds, so reddening it would need a row of 0.009s where the smallest legal
    value is 1. The clause is kept because it MEASURES the per-item cost instead of describing it —
    a model that charged a listing or a HEAD per item would come out three orders of magnitude
    worse and fail here — and the timeout is read back so it is the deployed budget being measured
    against, not a literal.

    What actually bounds this cap is therefore the byte cap below and the product reading: the file
    browser pages at 25, so 200 is eight full pages, and the page clause is what a wrong number
    trips. On its own that clause would certify nothing — every multiple of 25 from 100 to 1175
    satisfies it — which is why it ships beside a measurement rather than alone.
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

    verb_timeout_seconds = _verb_row("validate-authorize")[0]
    assert elapsed < verb_timeout_seconds / 10, (
        f"validating {config.FILE_OPS_MAX_ITEMS} items took {elapsed:.3f}s against a "
        f"{verb_timeout_seconds}s budget — the cap no longer leaves an order of magnitude"
    )
    assert config.FILE_OPS_MAX_ITEMS % 25 == 0, "the cap should be a whole number of browser pages"


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

    WHAT THE MARGIN HAS TO COVER, rather than that a margin exists. Ordering alone cannot fail:
    ``STALE_LOCK_SECONDS`` is ``MACHINE_TIMEOUT_SECONDS + 900``, so against either home of the
    ceiling the assertion reduces to ``x < x + 900`` — true whatever both numbers become, which
    makes it a comment wearing an assert.

    The quantity it must cover is the LONGEST VERB TIMEOUT. A state machine hitting its ceiling
    does not kill the Task it is waiting on: that Lambda runs to its own timeout, so an execution
    the machine has already abandoned can still be writing objects. Stealing its lock inside that
    window reintroduces exactly the concurrency the lock exists to prevent. The two are equal
    today at 900s, deliberately and with no slack — raising a verb past the margin is precisely
    the change that should redden this.
    """
    deployed_ceiling = int(_local("state_machine_timeout_seconds"))
    longest_verb = max(_verb_row(verb)[0] for verb in _ALL_CHARGED_VERBS)
    margin = config.STALE_LOCK_SECONDS - deployed_ceiling

    assert margin >= longest_verb, (
        f"a lock is stolen {margin}s past the ceiling while {longest_verb}s is the longest a verb "
        "the machine has abandoned can still be running — the steal would take a live run's lock"
    )


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
    acquire_timeout = _verb_row("acquire-lock")[0]
    worst_attempt = config.LOCK_WAIT_SECONDS + (4 * acquire_timeout + 14)
    give_up = config.LOCK_MAX_ATTEMPTS * worst_attempt

    assert give_up < config.MACHINE_TIMEOUT_SECONDS, (
        f"a waiter can burn {give_up}s against a {config.MACHINE_TIMEOUT_SECONDS}s ceiling"
    )


def test_the_browsers_mirrored_caps_are_never_more_permissive_than_these():
    """The browser refuses early so the common case fails fast and legibly, but it is not the
    authority — and it cannot measure the same quantity anyway.

    Its byte cap is over the SAME escaped serialisation this side measures — that was made true
    rather than assumed, and the test below compares the two measurements. This one is over the
    whole chain, which also includes the destination and one outcome record per item. So the property
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

    # Anchored on the DECLARATION, not the name: a comment restating the constant above a raised
    # one would otherwise be the first match, and the guard would read the mirrored value while
    # the browser shipped the higher one — admitting exactly the selection this exists to refuse.
    items = re.findall(r"^const FILE_OPS_MAX_ITEMS = (\d+);", service, re.MULTILINE)
    byte_factors = re.findall(
        r"^const FILE_OPS_MAX_SELECTION_BYTES = ([\d* ]+);", service, re.MULTILINE
    )
    assert len(items) == 1 and len(byte_factors) == 1, (
        f"fileOps.service.ts declares the caps {len(items)} and {len(byte_factors)} times"
    )

    browser_items = int(items[0])
    factors = byte_factors[0]
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

    **They were reconciled the wrong way round, and this is the corrected agreement.** Both sides
    were moved to the LITERAL form, which agreed with each other and with nothing else: the API
    re-serialises the body with the default escaping, so the wire spent six bytes on the character
    both caps counted as two. Both sides now measure the ESCAPED form, so all three agree, and the
    number below is what the browser computes for the same input after escaping.
    """
    selection = [{"kind": "file", "key": "alice/" + ("\u00e9" * 60)} for _ in range(170)]

    #: What the browser's own measurement yields for this input, computed in Node rather than
    #: derived from this side — a value taken from Python would only prove Python is
    #: self-consistent.
    javascript_bytes = 66471

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

    EVERY non-test module in a verb directory is read, not the ``file_ops_*`` ones: one verb ships
    as ``fo_notify_failure.py``, so a glob on the common prefix would leave a twelfth of the plane
    outside the check it advertises. The test files are skipped because this module is itself one
    of them and would otherwise report a verb named "common".
    """
    holders = set()
    for verb_dir in sorted((_MODULE.parents[2] / "lambdas").glob("file-ops-*")):
        for source in verb_dir.glob("*.py"):
            if source.name.startswith("test_"):
                continue
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


def test_the_file_ops_guards_pool_fits_inside_the_clients_connection_pool():
    """THE TERM THE OBVIOUS MODEL SKIPS. "Workers x timeout / latency" says to widen the pool until
    the arithmetic fits — but this plane creates no client of its own; it uses
    ``cpcommon.clients.s3()``, which passes no ``Config``, so botocore's default
    ``max_pool_connections`` is the real ceiling. Threads past it do not each get a connection:
    they contend, and urllib3 opens and discards sockets rather than reusing them, so a wider pool
    buys throughput the client cannot deliver while every bound computed from it reads as satisfied.
    """
    # Imported unconditionally. Behind a try/except this whole guard degrades, silently, to a
    # literal compared against a literal — and botocore is a declared dependency here, so an
    # ImportError is a broken environment rather than a case to tolerate.
    from botocore.config import Config

    assert _BOTOCORE_DEFAULT_MAX_POOL_CONNECTIONS >= config.FILE_OPS_HEAD_CONCURRENCY

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
        f"a worst-case expansion is ~{heads + pages:.0f}s against HALF of inspect-source's "
        f"{timeout}s — the budget is half the timeout, so a retry fits inside the same Task"
    )


#: Every verb whose timeout a run spends END TO END, in the order the graph walks them.
#: ``check-destinations`` appears TWICE because the graph sweeps twice, which is why this is a
#: written-out list rather than the Terraform's own row set — the terms are not one per row. The
#: two rows NOT here are charged elsewhere and the guard below holds that accounting closed.
#: Every verb the module deploys, charged to one budget or the other: the serial sum, the lock
#: give-up bound (acquire-lock) or the copy makespan (copy-objects). The guard below holds this
#: equal to the rows Terraform renders, so a thirteenth verb is charged before it can ship.
_ALL_CHARGED_VERBS = frozenset(
    {
        "validate-authorize",
        "acquire-lock",
        "release-lock",
        "inspect-source",
        "check-destinations",
        "build-transfer-manifest",
        "copy-objects",
        "collect-transfer-results",
        "delete-source",
        "finalise-outcomes",
        "notify",
        "notify-failure",
    }
)

_SERIAL_VERBS = (
    "validate-authorize",
    "release-lock",
    "inspect-source",
    "check-destinations",
    "check-destinations",
    "build-transfer-manifest",
    "collect-transfer-results",
    "delete-source",
    "finalise-outcomes",
    "notify",
    "notify-failure",
)


def _serial_verb_seconds() -> int:
    """Every verb timeout a run spends END TO END, read back from locals.tf rather than restated.

    The Map's own batch verb is deliberately absent: its time is inside the copy makespan, which is
    computed from the Map's concurrency, and counting it here would charge it twice. ``release-lock``
    IS here and charged once: exactly one of the three release states runs on every terminal path the
    graph can walk THAT TOOK THE LOCK — a validate failure refuses before the lock and releases
    nothing — so charging it once is an upper bound on time a run spends rather than an
    alternative to time it spends.
    """
    return sum(_verb_row(verb)[0] for verb in _SERIAL_VERBS)


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
    ), (
        "one object is one worker, and the largest legal one no longer streams inside HALF the "
        f"batch verb's {COPY_TIMEOUT_SECONDS}s — it may still fit the timeout, but not with the "
        "margin a batch of several needs"
    )


def test_every_verb_the_TERRAFORM_deploys_is_charged_to_one_budget_or_the_other():
    """The serial sum reads a WRITTEN-OUT list, so a thirteenth verb is invisible to it.

    That is the same shape as the plan-holder set and needs the same protection: without this, a
    verb added to ``locals.tf`` with a 3,000-second timeout would put a worst-case run past the
    ceiling while every budget in this module stayed green. The list cannot derive itself — the
    terms are not one per row, since the graph sweeps ``check-destinations`` twice and charges
    ``copy-objects`` through the makespan instead — so what is asserted is that the accounting is
    CLOSED: every deployed row is charged somewhere, and nothing is charged that is not deployed.
    """
    deployed = set(
        re.findall(r'"([a-z-]+)"\s*=\s*\{\s*handler', (_MODULE / "locals.tf").read_text())
    )

    assert deployed == _ALL_CHARGED_VERBS, (
        f"locals.tf deploys {sorted(deployed - _ALL_CHARGED_VERBS)} that no budget charges, and "
        f"this module charges {sorted(_ALL_CHARGED_VERBS - deployed)} that it does not deploy — a "
        "verb outside both budgets is time a run can spend the ceiling was never sized for"
    )

    # SET equality cannot see the one verb charged twice, and dropping that term is a 600-second
    # gift to the budget that nothing else here would notice. The graph is the authority for it.
    asl = (_MODULE / "state-machine.asl.json.tftpl").read_text()
    sweeps = asl.count("${check_destinations_function_arn}")

    assert sweeps == _SERIAL_VERBS.count("check-destinations") == 2, (
        f"the machine invokes the destination guard from {sweeps} states and the budget charges "
        f"{_SERIAL_VERBS.count('check-destinations')} — the second sweep runs on the same path as "
        "the first, so charging it once understates every run"
    )


def test_the_lock_wait_is_a_TERM_of_that_budget_rather_than_an_alternative_to_it():
    """The term the first version of this budget left out, pinned so it cannot quietly leave again.

    Waiting 2,000s for a busy space and then copying 2 TiB is one execution, not two scenarios.
    Without the give-up term the budget read as satisfied at a cap that was in fact ~2,000s over.
    """
    from cpcommon.transfer.config import (
        CONSERVATIVE_STREAM_BYTES_PER_SECOND,
        MAP_MAX_CONCURRENCY,
    )

    without = config.FILE_OPS_MAX_TOTAL_BYTES / (
        MAP_MAX_CONCURRENCY * CONSERVATIVE_STREAM_BYTES_PER_SECOND
    ) + _serial_verb_seconds()
    headroom = config.MACHINE_TIMEOUT_SECONDS - without

    # Restating the budget's own inequality would prove nothing the test above does not. What is
    # asserted instead is that the term is MATERIAL: it consumes most of the headroom the rest of
    # the run leaves, which is why omitting it let a 3 TiB cap read as satisfied.
    assert _give_up_seconds() > headroom / 2, (
        f"the give-up term is {_give_up_seconds()}s against {headroom:,.0f}s of headroom — if it "
        "has become negligible, re-derive the budget rather than deleting this test"
    )


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
    SECOND is over the limit. A future reader raising the sample size will find this rather than
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


# ── The THIRD budget: the inbox document a notification lands in ─────────────────────────


#: The notifications writer's own ceiling, read back out of the Lambda that enforces it. A
#: producer's bound is a design budget; this one is the refusal, and a payload over it loses the
#: whole message rather than its conflict list.
def _writer_payload_ceiling() -> int:
    """Returns ``MAX_PAYLOAD_BYTES`` as the notifications writer actually defines it.

    Read from the source rather than restated, because two homes for this number is a producer
    that believes it is inside a limit the writer has since lowered — and the failure is a message
    that dead-letters silently, on the queue whose DLQ is deliberately undrained.

    Args:
      None.

    Returns:
      The writer's ceiling in bytes.

    Raises:
      AssertionError: If the constant can no longer be found, which means this budget is being
        computed against nothing.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[1] / "notifications-writer" / "notifications_writer.py"
    ).read_text()
    # Matched as the two operands it is written as, rather than evaluated: a reader that ran the
    # expression would happily accept a form this assertion should be failing on.
    found = re.search(r"^MAX_PAYLOAD_BYTES\s*=\s*(\d+)\s*\*\s*(\d+)\s*$", source, re.MULTILINE)
    assert found, (
        "the notifications writer's MAX_PAYLOAD_BYTES is no longer written as two operands. That "
        "is what this reads rather than evaluating the expression, so a rewrite to a single "
        "literal fails HERE rather than silently accepting a form this should refuse — the cap "
        "may well still exist. Re-read it and re-derive this budget"
    )
    return int(found.group(1)) * int(found.group(2))


def _notification_row(conflicts: int | None, key_char: str) -> int:
    """Returns the worst-case ESCAPED size of one stored notification row.

    Every term a row can carry at this plane's caps: the writer's own four fields, the message with
    its full complement of named items, and the percent-encoded link — plus, when ``conflicts`` is
    not None, the payload with that many conflicted items in it.

    ``None`` is the case the marginal budget is measured AGAINST, and passing 0 instead is the
    mistake that made the first version of this measurement meaningless: a payload carrying zero
    conflicts still carries its mandatory head, so comparing the budget to that row compares the
    field against itself.

    Args:
      conflicts: How many conflicted items the payload carries, or None for a row with NO payload
        at all.
      key_char: The character every key and name is filled with.

    Returns:
      The row's serialised byte length.

    Raises:
      None.
    """
    label = key_char * config.FILE_OPS_SAMPLE_PATH_CHARS
    sample = [label] * config.FILE_OPS_CONFLICT_SAMPLE
    message = " ".join(
        [f'"{label}" - something is already in the way there.'] * config.FILE_OPS_NOTIFIED_ITEMS
    )
    payload = {
        "requestId": "0" * 36,
        "operation": "move",
        "source": {"kind": "personal", "name": "a" * 63},
        "destination": {"kind": "shared", "name": "b" * 63, "prefix": key_char * _MAX_KEY_BYTES},
        "conflicts": [
            {
                "itemKey": key_char * _MAX_KEY_BYTES,
                "kind": "folder",
                "targetName": key_char * config.MAX_TARGET_NAME,
                "sample": sample,
                "more": True,
            }
        ]
        * (conflicts or 0),
        "more": True,
    }
    row = {
        "id": "0" * 32,
        "message": message,
        "read": False,
        "timestamp": "2026-08-23T00:00:00.000Z",
        # The link carries the same prefix percent-encoded, which is three ASCII bytes per source
        # byte — a different expansion from JSON's and one this row pays on top.
        "link": f"/files?space=finance&prefix={quote(key_char * _MAX_KEY_BYTES, safe='/')}",
    }
    if conflicts is not None:
        row["payload"] = payload
    # json.dumps ESCAPES here rather than leaving the value literal, which is the difference that
    # matters: a control character becomes six bytes in the document the browser downloads.
    return len(json.dumps(row).encode())


def test_the_payload_budget_is_the_MARGINAL_one_and_the_constant_sits_under_it():
    """WHAT SIZES ``FILE_OPS_NOTIFIED_PAYLOAD_BYTES``, measured rather than chosen.

    The quantity is ``NOTIFICATIONS_MAX`` rows, not one row: the inbox is capped at 200 and the
    browser fetches and parses the WHOLE document on every 60-second poll, from the header bell, on
    every page — so a worst-case inbox is a recurring per-minute download.

    The budget is the MARGINAL one: the structured field may not add more to that document than the
    row already costs without it. Anything absolute would be a number chosen and then defended,
    and the row's own fixed cost — a percent-encoded link and a 1,024-byte destination prefix — is
    not something this spec controls.
    """
    for key_char in ("\x01", "k"):
        without = _notification_row(None, key_char)

        assert without > config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES, (
            f"the payload budget of {config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES} bytes exceeds the "
            f"{without}-byte row it rides on, so the field would dominate every poll"
        )


def test_WHICH_of_the_two_payload_bounds_binds_depends_on_the_keys_and_both_are_needed():
    """The measurement that decided there had to be two, kept because it is the whole argument.

    A count cap is what a reader reaches for first, and it bounds nothing here: one conflicted item
    is a couple of hundred bytes at ordinary key lengths and roughly twelve THOUSAND at this
    plane's caps, because S3 keys are 1,024 bytes of arbitrary UTF-8 and JSON escaping turns a
    control character into six. So the count binds at one end of the range and the bytes at the
    other, and dropping either leaves the payload unbounded in exactly the case that matters.
    """
    ordinary = {
        "itemKey": "alice/reports/2026/q1.csv",
        "kind": "file",
        "sample": ["reports/2026/q1.csv"],
    }
    worst = {
        "itemKey": "\x01" * _MAX_KEY_BYTES,
        "kind": "folder",
        "targetName": "\x01" * config.MAX_TARGET_NAME,
        "sample": ["\x01" * config.FILE_OPS_SAMPLE_PATH_CHARS] * config.FILE_OPS_CONFLICT_SAMPLE,
    }
    budget = config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES

    assert len(json.dumps([ordinary] * config.FILE_OPS_NOTIFIED_CONFLICTS).encode()) < budget, (
        "the byte budget refuses an ORDINARY selection's conflicts, so no user ever gets the list"
    )
    assert len(json.dumps([worst]).encode()) > budget, (
        "one worst-case conflicted item now fits the byte budget — re-derive it rather than "
        "deleting this test, because the caps that made it too big may simply have moved"
    )


def test_a_payload_at_the_budget_is_one_the_WRITER_still_accepts():
    """The producer's bound and the writer's refusal are two different numbers in two languages.

    A payload the producer considers fine and the writer refuses does not lose its conflict list —
    it loses the WHOLE message, on the one queue whose dead-letter queue is deliberately undrained.
    So the mandatory head plus a full complement of conflicts has to sit under the ceiling, and the
    ceiling is read out of the writer rather than restated here.
    """
    ceiling = _writer_payload_ceiling()
    head = {
        "requestId": "0" * 36,
        "operation": "move",
        "source": {"kind": "personal", "name": "a" * 63},
        # The prefix is the head's one otherwise-unbounded term, and the producer refuses to carry
        # one longer than this. Measured AT that bound rather than at S3's key limit by
        # coincidence: they are the same number for the same reason, and reading the constant back
        # is what keeps them so.
        "destination": {
            "kind": "shared",
            "name": "b" * 63,
            "prefix": "\x01" * config.FILE_OPS_NOTIFIED_PREFIX_BYTES,
        },
        "more": True,
    }
    # The producer adds a conflict only while the result stays inside its own budget, so the
    # largest payload it can emit is the head — which it always sends — or the budget, whichever
    # is larger.
    largest = max(len(json.dumps(head).encode()), config.FILE_OPS_NOTIFIED_PAYLOAD_BYTES)

    assert largest < ceiling, (
        f"this plane can emit a {largest}-byte payload against the writer's {ceiling}-byte "
        "ceiling — a run at the caps would lose its entire notification"
    )


# ── The three unheld values both runtimes hold, read back rather than trusted ─


def test_the_machines_ceiling_is_the_number_terraform_renders():
    """The one term of the joint budget that was NOT read back, and every ceiling assertion in this
    module rests on it.

    The budget above reads eleven verb timeouts out of ``locals.tf`` and then measures their sum
    against a PYTHON copy of the ceiling. A ceiling lowered in Terraform alone would leave the whole
    chain — the joint budget, the give-up bound, the per-object cap — certifying a ceiling the
    machine does not have, and every one of them would stay green. The stale threshold is the one
    member that would notice on its own, because it reads the rendered number directly.

    A grep for the local finds a neighbouring guard and that is the trap: ``test_file_ops_browser_mirrors``
    reads this same number and holds it against the BROWSER's constant, never against this one.
    """
    assert int(_local("state_machine_timeout_seconds")) == config.MACHINE_TIMEOUT_SECONDS, (
        f"locals.tf renders a {_local('state_machine_timeout_seconds')}s ceiling against Python's "
        f"{config.MACHINE_TIMEOUT_SECONDS}s — every budget in this module is measured against the "
        "Python number, so all of them are now certifying a ceiling that is not deployed"
    )


def test_the_lock_wait_is_the_number_terraform_renders():
    """The ASL ``Wait`` between re-acquire attempts, which ASL cannot import from Python.

    It is a TERM of the give-up bound, so the two homes diverging does not just mis-describe the
    wait — it moves the bound that has to stay under the machine's ceiling, in a computation that
    reads the interval from Python and the ceiling from Python and would notice neither.
    """
    assert int(_local("lock_wait_seconds")) == config.LOCK_WAIT_SECONDS, (
        f"locals.tf waits {_local('lock_wait_seconds')}s between attempts and Python computes the "
        f"give-up bound from {config.LOCK_WAIT_SECONDS}s"
    )


def test_the_lock_prefix_is_the_one_terraform_grants():
    """Two homes for one prefix is a lock the verbs write and the policy does not permit.

    The verbs build the key from the Python constant; the IAM grant is rendered from the Terraform
    local. Diverge them and every acquire fails as an AccessDenied at runtime, on a path whose whole
    job is to stop two runs touching one space at once.
    """
    assert _local("lock_prefix") == config.LOCK_PREFIX, (
        f"the IAM grant covers {_local('lock_prefix')!r} and the verbs write "
        f"{config.LOCK_PREFIX!r}"
    )


# ── The protected-folder lists, member for member ────────────────────────────


def test_the_picker_locked_folders_are_exactly_these_eight():
    """Spelled out, in order: three members now come from cpcommon and must not move a seat."""
    assert config.PICKER_LOCKED_FOLDERS == (
        "athenaresults",
        "user_settings",
        "_data-quality-reports",
        "_directory",
        "_config",
        "shared_tables",
        "archive",
        "system_settings",
    )


def test_the_undeletable_root_folders_are_exactly_these_four():
    """Spelled out, in order."""
    assert config.UNDELETABLE_ROOT_FOLDERS == ("athenaresults", "saved_queries", "archive", "system_settings")


def test_the_any_depth_undeletable_folders_are_exactly_these_three():
    """The delete module's own any-depth list, spelled out."""
    assert delete._UNDELETABLE_FOLDERS == ("athenaresults", "user_settings", "archive")
