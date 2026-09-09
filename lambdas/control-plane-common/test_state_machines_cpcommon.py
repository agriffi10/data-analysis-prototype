"""Invariants that must hold in EVERY control-plane state machine.

These read the deployed ASL templates under infra/ rather than a copy, because the whole
point is to fail when one of them drifts. They are not about any single arc — they encode
rules that were each learned by breaking production.
"""

import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from cpcommon import config

_HERE = os.path.dirname(os.path.abspath(__file__))
_INFRA = os.path.join(_HERE, "..", "..", "infra", "modules")
_TEMPLATES = sorted(glob.glob(os.path.join(_INFRA, "*", "state-machine.asl.json.tftpl")))

#: Intrinsics that RAISE rather than degrade when their input is the wrong shape.
#:
#: They raise ``States.Runtime``, which AWS documents as neither retriable NOR catchable —
#: a ``Catch: ["States.ALL"]`` on the very same Task does not catch it. So one of these
#: anywhere, in ANY state type, kills the execution outright. (An earlier version of this
#: guard checked only ``Pass`` states, on the mistaken belief that "a Pass state cannot
#: Catch" was the mechanism. It is not — the Pass states were merely where the bug
#: happened to live.)
_THROWING_INTRINSICS = ("States.StringToJson", "States.ArrayGetItem", "States.MathAdd")

#: Every control plane whose machine must satisfy the invariants below. Named rather than
#: counted so a renamed or deleted module fails loudly instead of shrinking the sample.
_EXPECTED_ARCS = {
    "data-quality",
    "shared-spaces",
    "table-builder",
    "table-share",
    "file-send",
    "archive",
    "file-ops",
    "results-conversion",
}

#: Every state field in which ASL EVALUATES intrinsic functions. The scan below walked
#: ``Parameters`` alone while its docstring claimed every state type — true of state types,
#: not of fields. No production machine has an intrinsic in the other five today
#: (``table-share``'s ``ItemSelector`` holds only ``$$.Map.Item.Value`` and ``$``), so this
#: was a coverage hole rather than a live defect — but a ``States.StringToJson`` added to a
#: ``ResultSelector`` would be exactly as uncatchable and entirely unseen. ``Arguments``,
#: ``Assign`` and ``Output`` are JSONata/variables-era fields: unused here, and the point of
#: naming them is that adopting one must not silently leave the scan behind.
_INTRINSIC_FIELDS = (
    "Parameters",
    "ResultSelector",
    "ItemSelector",
    "Assign",
    "Output",
    "Arguments",
)


def _intrinsics_in(value):
    """Yield every throwing intrinsic anywhere inside an intrinsic-evaluating field.

    Recurses: such a block nests, and an intrinsic one level down
    (``{"outer": {"cause.$": "States.StringToJson(...)"}}``) is exactly as fatal as one at
    the top and exactly as invisible to a flat scan.
    """
    if isinstance(value, str):
        if any(fn in value for fn in _THROWING_INTRINSICS):
            yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _intrinsics_in(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _intrinsics_in(nested)


def _load(path):
    """Parse a .tftpl with its Terraform placeholders stubbed to a literal.

    Two substitutions, not one, because SPEC-160 introduced the fleet's first placeholder in a
    NUMERIC position (``"MaxItemsPerBatch": $${…}`` — the Distributed Map's sizing, fed from
    locals.tf). Stubbing that to a bare word produced invalid JSON and failed every check in
    this file at once, which reads like a broken machine rather than a broken parser. A
    placeholder that directly follows a colon is a value and becomes ``0``; every other one is
    inside a string and becomes ``stub``.
    """
    with open(path) as handle:
        raw = handle.read()
    raw = re.sub(r":\s*\$\{[^}]+\}", ": 0", raw)
    return json.loads(re.sub(r"\$\{[^}]+\}", "stub", raw))


def _states(asl):
    """Yield (qualified_name, state) for every state, including inside Map/Parallel."""
    def walk(states, prefix=""):
        for name, state in states.items():
            yield prefix + name, state
            for branch in state.get("Branches", []) or []:
                yield from walk(branch["States"], f"{prefix}{name}/")
            for key in ("Iterator", "ItemProcessor"):
                if key in state:
                    yield from walk(state[key]["States"], f"{prefix}{name}/")
    return walk(asl["States"])


def _throwing_intrinsics(asl):
    """Every ``state.field = expression`` in ``asl`` holding an uncatchable intrinsic."""
    offenders = []
    for name, state in _states(asl):
        for field in _INTRINSIC_FIELDS:
            block = state.get(field)
            # JSONata-mode `Output`/`Assign` may be a bare STRING rather than a mapping, and
            # a scan that raised AttributeError on one would break the day someone adopted
            # it — the opposite of the point. Scan the value directly in that case.
            items = block.items() if isinstance(block, dict) else [(None, block)]
            for key, value in items:
                where = f"{name}.{field}" if key is None else f"{name}.{field}.{key}"
                offenders += [f"{where} = {found}" for found in _intrinsics_in(value)]
    return offenders


def test_every_expected_state_machine_is_being_checked():
    """Guards the whole file against passing vacuously if the glob stops matching.

    Asserts the NAMES, not a count: a renamed module would keep a count-based check green
    while silently dropping a whole control plane from every invariant below.
    """
    found = {os.path.basename(os.path.dirname(p)) for p in _TEMPLATES}

    assert found == _EXPECTED_ARCS, f"missing {_EXPECTED_ARCS - found}, unexpected {found - _EXPECTED_ARCS}"


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_no_state_uses_a_throwing_intrinsic(path):
    """THE BUG THIS EXISTS FOR, and it cost the failure path its outcome in all three arcs.

    Every control plane decoded a Lambda error the same way:

        "cause.$": "States.StringToJson($.error.Cause)"

    StringToJson raises States.Runtime whenever Cause is absent or is not JSON, and
    States.Runtime is neither retriable nor catchable — not even by a Catch on the very
    same state. Confirmed against the live service with TestState: States.Timeout (no
    Cause), States.DataLimitExceeded and Lambda.Unknown (plain-sentence Cause) each killed
    the execution BEFORE the recorded-failure state. In data-quality that meant no
    notification at all on exactly the failures a user most needs to hear about; in
    table-share, which decoded per recipient inside a Map, one unparseable Cause failed the
    iteration, which failed the Map, which took down every SIBLING recipient's share.

    CHECKS EVERY STATE TYPE, not just Pass, and recurses into nested blocks — an intrinsic
    in a Task's Parameters is exactly as fatal and was exactly as unguarded. Since SPEC-153
    it also checks every FIELD in which ASL evaluates intrinsics (_INTRINSIC_FIELDS), not
    Parameters alone: the field list, not the state-type list, was the narrow one.

    Decode in Python instead: cpcommon.errors.failure_reason handles any shape.
    """
    offenders = _throwing_intrinsics(_load(path))

    assert not offenders, (
        f"{os.path.basename(os.path.dirname(path))}: States.Runtime cannot be caught "
        f"anywhere, so a throwing intrinsic kills the execution outright: {offenders}"
    )


#: Planes exempt from the NotifyFailure requirement below, each with a reason. EMPTY, and
#: an entry is a decision to leave users in the dark on some failure — not a formality.
_NOTIFY_FAILURE_EXEMPT: dict[str, str] = {}


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_every_plane_notifies_before_it_fails(path):
    """SPEC-152 FR-001. A FIFTH CONTROL PLANE MUST NOT SHIP WITHOUT THIS.

    Every plane here is asynchronous and fire-and-forget: the browser enqueues, gets a
    toast, and the outcome arrives as a notification. SPEC-114 made that explicit — the
    notification IS the completion channel, because the user has no other way to learn what
    happened, and there is no admin UI to check.

    The verbs honour it through their own instrumentation, and SPEC-126's DLQ drain honours
    it for requests that never started an execution. Neither covers the gap between: an
    execution that started and then died BEFORE OR OUTSIDE any verb's Python — a
    States.Timeout, a States.DataLimitExceeded, a task-level throttle, a Lambda that fails
    at IMPORT. In that window the user gets no notification, no DLQ message, and a request
    that simply never completes.

    The design was right and was built once: data-quality carried a NotifyFailure state
    while table-builder, table-share and shared-spaces routed every failure straight to a
    terminal Fail. This is the check that stops it drifting back apart.

    ASSERTS THE STATE BY NAME, not a count of anything (FR-004): a plane that renames it is
    a plane whose failure path nobody can find, and a count would be satisfied by any four
    states at all.
    """
    plane = os.path.basename(os.path.dirname(path))
    if plane in _NOTIFY_FAILURE_EXEMPT:
        pytest.skip(f"{plane} is exempt: {_NOTIFY_FAILURE_EXEMPT[plane]}")

    states = dict(_states(_load(path)))
    assert "NotifyFailure" in states, (
        f"{plane} has no NotifyFailure state: every way a request can fail must end in a "
        f"message, or 'it just never came back' is a reachable state for the user"
    )

    # It must be a real invocation, not a Pass placeholder that reads as one.
    assert states["NotifyFailure"]["Type"] == "Task", f"{plane}: NotifyFailure is not a Task"

    # AND IT MUST NOT BE ABLE TO FAIL THE EXECUTION INTO SILENCE. A notifier error is
    # already-lost information; letting it escape would replace a recorded failure with an
    # unhandled one, which is strictly worse than the missed message.
    caught = {e for c in states["NotifyFailure"].get("Catch", []) or [] for e in c["ErrorEquals"]}
    assert "States.ALL" in caught, f"{plane}: NotifyFailure has no States.ALL Catch"


#: Step Functions' hard cap on a state payload. Breaching it raises
#: States.DataLimitExceeded, which is thrown OUTSIDE every Catch. Read from the module this file
#: tests rather than restated beside it.
_STATE_PAYLOAD_LIMIT = config.STATE_PAYLOAD_LIMIT_BYTES


def _definition_at_cap(cap_bytes):
    """A cloned definition sized to exactly the cap inspect-source enforces.

    Shaped like tscommon.glue.clone_definition's real output — lowercase name/type/comment
    per column plus partitionKeys, serde parameters and tableProperties — not the
    {Name, Type} pairs an earlier model used, which understated it by roughly 3x.

    Kept after SPEC-161 moved the definition off the state, because it is now what shows the
    pointer is LOAD-BEARING rather than tidy: the test below adds a worst-allowed definition
    back to the modelled state and measures the breach.
    """
    definition = {"columns": [], "partitionKeys": [], "serde": {"parameters": {}}, "tableProperties": {}}
    while len(json.dumps(definition, separators=(",", ":")).encode()) < cap_bytes:
        definition["columns"].append(
            {"name": f"column_number_{len(definition['columns']):04d}", "type": "string", "comment": "c" * 255}
        )
    return definition


def test_the_whole_map_state_stays_under_the_payload_limit():
    """The WHOLE state the Map produces, not just the part this change bounded.

    An earlier version of this test measured the failure-records array alone, reported 26%
    of the limit, and read as though the Map were safe. It was not. The dominant term was
    `objects` — inspect-source's copy plan, up to SHARE_MAX_OBJECTS entries, which the Map's
    ItemSelector copied into EVERY item and ResultPath merged back into. Measured then, at
    the shipped caps with ordinary Hive keys (~140 chars):

        FULL Map state, 1000 objects, 50 recipients     249 KB   95%
        the same with ZERO failures                     187 KB   71%

    The plan now travels by POINTER (tscommon.copy_plan), so `objects` is a key rather than
    an array and the term is gone. This asserts the whole state — request + recipients +
    definition + results — because that is the quantity Step Functions actually limits, and
    because measuring a part of it is how the last version came to certify a bound that did
    not exist.

    THREE things hold it: SHARE_MAX_RECIPIENTS (how many entries), errors.MAX_DETAIL_CHARS
    (how big a Cause), and the pointers (neither the object list nor the cloned schema is on
    the state at all). No single one suffices: at the 32 KB Cause ceiling the records breach
    on their own at seven recipients.

    **SPEC-161 removed the fourth, and it was the one a cap could not really hold.** The
    cloned definition used to ride inline under SHARE_MAX_DEFINITION_BYTES — a 1,000-column
    commented definition breached at 150% even after the plan became a pointer, and the cap
    that fixed that was tight enough to refuse a 100-column commented table, which is an
    ordinary thing to want to share. It now travels as `definitionKey`, so the term is a
    64-character digest path, and SHARE_MAX_DEFINITION_BYTES bounds Athena's query string
    instead of this payload. `test_the_definition_never_returns_to_the_state` below is what
    keeps it off.

    **SPEC-160 split the one Map into three states, so this now models TWO peaks.** The old
    single-peak model went stale the moment the machine grew a guard Map: a raw Cause per refused
    recipient appears in `guardResults`, and if the collector both kept that array and re-emitted
    the raw error, the finish Map's merge would hold THREE copies of every refusal at once — which
    measured at 108% of the limit for 50 conflicting recipients, i.e. a silent breach in the most
    ordinary case there is (re-sharing a table most recipients already have). Two rules keep it
    where it was: `collect-transfer-results` CONSUMES `guardResults` rather than passing it on, and
    it carries the DECODED reason instead of the raw error. Both are modelled below, so undoing
    either fails here rather than in production.

    **SPEC-225 put the run's traceparent on the state, so the headroom is RE-DERIVED here rather
    than re-run.** Measured at this commit, against the `_STATE_PAYLOAD_LIMIT // 2` bar the three
    peaks are held to:

        guard, all refused      85,752 bytes   32.7% of the limit
        guard, all accepted     30,402 bytes   11.6%
        finish                  92,970 bytes   35.5%
        guard + at-cap definition (the control below)  152,739 bytes   58.3%

    The traceparent itself is 73 bytes with its key and comma, and contributes 0.03 of a
    percentage point;
    the distance from the ~29% this file used to quote is other growth since, which is the reason
    the figure is re-derived rather than trusted. Re-derive it the same way — the numbers come
    from the three `json.dumps` below and nowhere else. The bar leaves the state room to grow by
    roughly 40% before it is reached, which is headroom on purpose: a budget pinned at the
    measurement leaves the next legitimate addition nothing to spend.
    """
    sys.path.insert(0, os.path.join(_HERE, "..", "table-share-common"))
    from cpcommon import errors
    from tscommon import config as ts_config

    cause = json.dumps({
        "errorMessage": "create_failed: " + ("x" * errors.MAX_DETAIL_CHARS),
        "errorType": "TerminalError",
        "requestId": "0" * 36,
        "stackTrace": ['  File "/var/task/table_share_create_table.py", line 999, in _fn\n    raise\n'] * 8,
    })
    recipients = ts_config.SHARE_MAX_RECIPIENTS
    resolved = {
        "kind": "space", "name": "s" * 64, "valid": True, "database": "s" * 64,
        "destBucket": "b" * 63, "destPrefix": ("s" * 64) + "/shared_tables/" + ("n" * 64) + "/",
    }
    request = {
        # SPEC-225: on the state from validate-authorize onward, and on every Map's BatchInput.
        # 55 bytes as a value, 73 with its key and comma — small, but the model exists to be re-derived
        # rather than assumed, and the measured headroom is restated below.
        "traceparent": "00-" + "0" * 32 + "-" + "0" * 16 + "-01",
        "actor": "a" * 64,
        "source": {"database": "d" * 64, "table": "t" * 64},
        "tableName": "n" * 64,
        "recipients": [{"kind": "space", "name": "s" * 64, "valid": True} for _ in range(recipients)],
        # SPEC-161: a key, not the columns. An earlier version of this test modelled 300 bare
        # {Name, Type} pairs and called it "bounded by column count" — it was not: 1,000
        # columns with 255-char comments reached 150% of the limit even WITH the plan by
        # pointer, and the cap that then bounded it was too tight for an ordinary wide table.
        "definitionKey": "table-share/" + ("0" * 64) + "/definition.json",
        "location": {"bucket": "b" * 63, "prefix": "p" * 200},
        # THE POINT OF PR #256: a key, not up to SHARE_MAX_OBJECTS {relKey, size} entries.
        "copyPlanKey": "table-share/" + ("0" * 64) + "/copy-plan.json",
        "objectCount": ts_config.SHARE_MAX_OBJECTS,
        "partitioned": True,
        "execution": {"name": "e" * 80},
        "transfer": {
            "manifestBucket": "b" * 63,
            "manifestKey": "table-share/" + ("0" * 64) + "/" + ("e" * 80) + "/transfer-manifest.jsonl",
            "resultsBucket": "b" * 63,
            "resultsPrefix": "table-share/" + ("0" * 64) + "/" + ("e" * 80) + "/results",
            # The product, not objects x recipients: SPEC-161's SHARE_MAX_TRANSFER_ITEMS is
            # what bounds this, and it is smaller than the two caps multiplied together.
            "itemCount": ts_config.SHARE_MAX_TRANSFER_ITEMS,
        },
    }

    # PEAK 1 — the guard Map's output: every recipient refused, each carrying a raw Cause. A
    # refused item carries the UNRESOLVED recipient, because a Catch hands back the task's input
    # and check-target-absent raises before it can return the resolved one. (`resolved` below is
    # the accepted shape, which is bigger per entry but carries no Cause — the all-refused case
    # is the heavier of the two.)
    after_guard = {
        **request,
        "guardResults": [
            {"status": "failed", "recipient": {"kind": "space", "name": "s" * 64, "valid": True},
             "error": {"Error": "TerminalError", "Cause": cause}}
            for _ in range(recipients)
        ],
    }

    # The all-accepted variant, for completeness: no Causes, but the resolved recipient per entry.
    after_guard_accepted = {
        **request,
        "guardResults": [{"status": "ok", "recipient": resolved} for _ in range(recipients)],
    }

    # PEAK 2 — the finish Map's output. `guardResults` is GONE (the collector consumed it) and the
    # outcomes carry a decoded reason, not the raw error; only `recipientResults` holds Causes.
    after_finish = {
        **request,
        "outcomes": [
            {"kind": "space", "name": "s" * 64, "status": "failed", "reason": "conflict",
             "failedItems": 0, "recipient": None}
            for _ in range(recipients)
        ],
        "recipientResults": [
            {"kind": "space", "name": "s" * 64, "status": "failed",
             "error": {"Error": "TerminalError", "Cause": cause}}
            for _ in range(recipients)
        ],
    }

    for label, state in (
        ("guard (all refused)", after_guard),
        ("guard (all accepted)", after_guard_accepted),
        ("finish", after_finish),
    ):
        total = len(json.dumps(state))
        assert total < _STATE_PAYLOAD_LIMIT // 2, (
            f"the {label} Map's whole output state reaches {total:,} bytes at "
            f"SHARE_MAX_RECIPIENTS={recipients} x MAX_DETAIL_CHARS={errors.MAX_DETAIL_CHARS} — too "
            f"close to the {_STATE_PAYLOAD_LIMIT:,}-byte limit to be safe"
        )

    # SPEC-161: the definition pointer is LOAD-BEARING, not tidiness. Put the biggest
    # definition the caps still allow back on the same state and it fails the SAME safety bar
    # the three peaks above just cleared — which is what makes those assertions a property of
    # the pointer rather than of the numbers happening to be small today. Measured: the guard
    # peak goes from 32.7% of the limit to 58.3% with an at-cap definition inline. Not a breach
    # at 64 KiB, and that is the point in both directions — the old 32 KiB cap kept it under
    # the bar only by refusing a 100-column commented table, which is an ordinary thing to
    # share. Inline, the cap had to choose between the payload and the user.
    with_definition = {
        **after_guard,
        "tableDefinition": _definition_at_cap(ts_config.SHARE_MAX_DEFINITION_BYTES),
    }
    inline = len(json.dumps(with_definition))
    assert inline > _STATE_PAYLOAD_LIMIT // 2, (
        f"an at-cap definition inline reaches only {inline:,} bytes, inside the "
        f"{_STATE_PAYLOAD_LIMIT // 2:,}-byte bar the peaks above are held to — so this test is "
        "no longer demonstrating why the definition travels by pointer"
    )


def _read_keys(block):
    """Every top-level state key a Parameters-style block reads, at ANY nesting depth.

    The population this guard actually evaluates is worth stating exactly, because two looser
    versions of this sentence were written before this one and both overstated it. Nineteen nested
    reads exist across every ``Pass`` in the fleet. This guard evaluates the reads of states
    DOWNSTREAM of a seed, and exactly ONE of those is nested today: ``table-builder/RecordFailure``
    reading ``$.space.database``, whose ``ValidateFailureSeed`` supplies a literal ``space``. Three
    more sit on seeds themselves, where the block is read as what is SUPPLIED rather than what is
    read. The remaining fifteen are success-path states this guard never walks.

    A NESTED PATH yields its FIRST SEGMENT — ``$.space.database`` reads ``space`` — because that
    is the key the state must carry for the path to resolve at all.

    A NESTED BLOCK is recursed into, for exactly the reason ``_intrinsics_in`` above already
    recurses: a payload template nests, and ``{"detail": {"who.$": "$.nobody"}}`` is precisely as
    fatal as a top-level read and precisely as invisible to a flat scan. The two helpers in this
    file disagreed about that until a reviewer planted the nested form and watched the whole file
    stay green.

    What this does NOT do, said plainly because the guard's name over-claims otherwise: it
    compares the first segment only, so ``$.error.Detail.Name`` is satisfied by a seed supplying
    a literal ``error`` that has no ``Detail``. Resolving a path INTO a literal would need the
    seed's whole value modelled, which is a different guard.

    Args:
      block: A state's ``Parameters`` (or any block nested inside one), or None.

    Returns:
      The set of top-level state keys the block reads.

    Raises:
      None.
    """
    keys = set()
    if isinstance(block, dict):
        for name, value in block.items():
            if name.endswith(".$") and isinstance(value, str):
                match = re.fullmatch(r"\$\.([A-Za-z0-9_]+)(?:\.[A-Za-z0-9_]+)*", value.strip())
                if match:
                    keys.add(match.group(1))
            else:
                keys |= _read_keys(value)
    elif isinstance(block, list):
        for value in block:
            keys |= _read_keys(value)
    return keys


def _containers(asl):
    """Yields (label, start_at, states) for the machine and for every ItemProcessor in it.

    Each processor is its own graph with its own ``StartAt``, so reachability has to be asked
    per container rather than over one flattened map.

    Args:
      asl: The parsed state machine.

    Returns:
      Nothing; yields one triple per container.

    Raises:
      None.
    """
    def walk(label, block):
        yield label, block["StartAt"], block["States"]
        for name, state in block["States"].items():
            processor = state.get("ItemProcessor") or state.get("Iterator")
            if processor:
                yield from walk(f"{label}/{name}", processor)
            # A Parallel branch is its own graph with its own StartAt, exactly as an
            # ItemProcessor is. No machine has one today, which is precisely why this is here:
            # every sweep built on this walk would be silently blind to the first one added, and
            # `_states` beside it already descends Branches, so the two would disagree.
            for index, branch in enumerate(state.get("Branches") or []):
                yield from walk(f"{label}/{name}[{index}]", branch)

    yield from walk("", asl)


def _targets(state):
    """Every state name one state can hand control to.

    Args:
      state: One ASL state.

    Returns:
      The names it names, in no order.

    Raises:
      None.
    """
    named = [state.get("Next"), state.get("Default")]
    named += [catch.get("Next") for catch in state.get("Catch", []) or []]
    named += [choice.get("Next") for choice in state.get("Choices", []) or []]
    return [name for name in named if name]


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_every_state_is_reachable_and_every_target_exists(path):
    """A dangling target or an unreachable state is a RED FIRST APPLY, not a lint nit.

    Step Functions refuses the whole definition at ``CreateStateMachine`` — ``State "X" is not
    reachable`` — so a template that renders, validates under `tofu validate` and passes every
    other test in this file still fails the apply, on the one run where nothing else has gone
    wrong yet. Neither `tofu validate` nor the ASL's own JSON parse can see it: `validate`
    checks HCL, and the definition is a string to Terraform until AWS reads it.

    Measured on this branch: planting `"Next": "DescribeResult"` in one plane's cross-check Pass
    left the whole suite green at 2,619 passed while five states went unreachable.

    Args:
      path: One plane's state-machine template.

    Returns:
      None.

    Raises:
      AssertionError: On a target that names no state, or a state nothing can reach.
    """
    plane = os.path.basename(os.path.dirname(path))
    for label, start_at, states in _containers(_load(path)):
        where = f"{plane}{label}"
        assert start_at in states, f"{where}: StartAt names {start_at!r}, which is not a state"

        dangling = sorted(
            {target for state in states.values() for target in _targets(state)} - set(states)
        )
        assert not dangling, (
            f"{where}: {dangling} are named as a Next/Default/Catch target but are not states. "
            "CreateStateMachine refuses the definition, so this is a red first apply"
        )

        seen, frontier = set(), [start_at]
        while frontier:
            name = frontier.pop()
            if name in seen:
                continue
            seen.add(name)
            frontier.extend(_targets(states[name]))
        unreachable = sorted(set(states) - seen)
        assert not unreachable, (
            f"{where}: {unreachable} cannot be reached from {start_at!r}. Step Functions REFUSES "
            "an unreachable state outright rather than ignoring it"
        )


def test_the_reachability_walk_sees_a_break_when_one_is_planted():
    """The positive control. Every assertion above is an absence, and an absence proves nothing
    unless the walk that looked for it can find one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a deliberately broken machine reads as sound.
    """
    broken = {
        "StartAt": "A",
        "States": {
            "A": {"Type": "Pass", "Next": "B"},
            "B": {"Type": "Succeed"},
            "Orphan": {"Type": "Pass", "Next": "Nowhere"},
        },
    }
    (_label, start_at, states), = _containers(broken)
    assert sorted({t for s in states.values() for t in _targets(s)} - set(states)) == ["Nowhere"]
    seen, frontier = set(), [start_at]
    while frontier:
        name = frontier.pop()
        if name in seen or name not in states:
            continue
        seen.add(name)
        frontier.extend(_targets(states[name]))
    assert sorted(set(states) - seen) == ["Orphan"]


#: Every state that feeds a failure terminal, as (plane, qualified name). DERIVED by parsing and
#: pinned as a MEMBERSHIP, for the reason `_THREADING_STATES` is: a recognition that widened in one
#: place and narrowed in another keeps the count and changes the answer.
_FAILURE_SEEDS = frozenset({
    ("archive", "NothingToArchiveSeed"),
    ("archive", "NothingToRestoreSeed"),
    ("archive", "RecordFailure"),
    ("archive", "RequestFailureSeed"),
    ("archive", "RestoreIncompleteReturnedSeed"),
    ("archive", "RestoreTimedOutSeed"),
    ("archive", "RollbackReturnedSeed"),
    ("archive", "UnknownModeSeed"),
    ("archive", "ValidateFailureSeed"),
    ("data-quality", "RecordFailure"),
    ("data-quality", "ValidateFailureSeed"),
    ("file-ops", "GiveUpFailureSeed"),
    ("file-ops", "RecordFailure"),
    ("file-ops", "RequestFailureSeed"),
    ("file-ops", "ValidateFailureSeed"),
    ("file-send", "GuardRecipients/RecipientFaulted"),
    ("file-send", "RecordFailure"),
    ("file-send", "RequestFailureSeed"),
    ("file-send", "ValidateFailureSeed"),
    ("results-conversion", "ConvertRefusedSeed"),
    ("results-conversion", "RecordFailure"),
    ("results-conversion", "RequestFailureSeed"),
    ("results-conversion", "ValidateFailureSeed"),
    ("shared-spaces", "RecordFailure"),
    ("shared-spaces", "RefusedSeed"),
    ("shared-spaces", "ValidateFailureSeed"),
    ("table-builder", "RecordFailure"),
    ("table-builder", "ValidateFailureSeed"),
    ("table-share", "FinishRecipients/RecipientFailed"),
    ("table-share", "GuardRecipients/RecipientRefused"),
    ("table-share", "RecordFailure"),
    ("table-share", "ValidateFailureSeed"),
})


def _terminals_reachable_from(start, states):
    """Every state reachable from `start` that hands control NOWHERE, with its type.

    "Terminal" means exactly that — no ``Next``, ``Default``, ``Choices`` or ``Catch`` target.

    Read instead as "a ``Succeed`` or ``Fail`` STATE", an ``ItemProcessor`` contains neither, so
    its walk returns an empty list, ``all([])`` is vacuously True, and the recognition below
    selects success leaves — ``table-share/FinishRecipients/RecipientSucceeded`` among
    thirty-five states rather than thirty-two.

    **That number needs BOTH mistakes at once, and saying so is the honest form.** Measured all
    four ways: this definition gives thirty-two with or without the non-empty check beside it,
    and the state-type reading gives thirty-two too as long as that check stands. So neither
    defence is load-bearing while the other holds, and a mutation of either alone leaves the
    fleet-wide sweeps green — which is why the definition is pinned DIRECTLY, on a ``Pass`` that
    ends its branch and is a terminal under this reading and not under the other.

    Args:
      start: The state name to walk from.
      states: Its container's states, since ``Next`` names siblings unqualified.

    Returns:
      One (name, type) pair per terminal, in no order.

    Raises:
      None.
    """
    seen, frontier, terminals = set(), [start], []
    while frontier:
        name = frontier.pop()
        if name in seen or name not in states:
            continue
        seen.add(name)
        state = states[name]
        onward = _targets(state)
        if not onward:
            terminals.append((name, state.get("Type")))
        frontier.extend(onward)
    return terminals


def _is_a_failure_seed(name, state, states):
    """Whether one state feeds a failure terminal and nothing else.

    Recognition is the UNION of two tests, and a union rather than a replacement because each is
    blind exactly where the other sees.

    The STRUCTURAL test — ``Parameters["error.$"] in ("$", "$.error")`` — is what this guard used
    alone. It cannot see a state that replaces the state with a LITERAL ``error`` object: NINE of
    them across the fleet, six on archive, plus ``file-ops/GiveUpFailureSeed``,
    ``results-conversion/ConvertRefusedSeed`` and ``shared-spaces/RefusedSeed``.

    The GRAPH test asks whether a ``Pass`` carrying no ``ResultPath`` can reach nothing but
    ``Fail`` terminals. It finds those nine and LOSES three the structural test keeps —
    ``file-send/GuardRecipients/RecipientFaulted``, ``table-share/GuardRecipients/RecipientRefused``
    and ``table-share/FinishRecipients/RecipientFailed`` — because their ``ItemProcessor`` holds no
    ``Fail`` state at all: a branch failure propagates to the parent Map's ``Catch``, which is not
    a walkable state. Obeying "recognition moves to the graph" literally trades nine gained seeds
    for three lost ones. Measured: structural 23, graph 29, union 32.

    The ``ResultPath`` discriminator is the graph half's own: a MERGING ``Pass`` does not replace
    the state, so "the seed supplies everything downstream reads" is false for it, and without the
    discriminator four extra states are selected and produce seven findings that are not defects.

    The non-empty terminal check is a SECOND defence rather than the same one twice. With the
    terminal definition above it changes nothing — both readings give twenty-nine. It is what
    stands between this sweep and thirty-five states, including success leaves, on the day someone
    narrows ``_terminals_reachable_from`` back to a state type.

    Args:
      name: The state's name within its container.
      state: The state.
      states: Its container's states.

    Returns:
      True if the state seeds a failure terminal.

    Raises:
      None.
    """
    if state.get("Type") != "Pass":
        return False
    parameters = state.get("Parameters")
    if isinstance(parameters, dict) and parameters.get("error.$") in ("$", "$.error"):
        return True
    if "ResultPath" in state:
        return False
    terminals = _terminals_reachable_from(name, states)
    return bool(terminals) and all(kind == "Fail" for _name, kind in terminals)


def _failure_seeds(asl):
    """Yields (container label, name, state, that container's states) for every failure seed.

    Per CONTAINER, which is the repair for a latent bug rather than a tidying. The old walk
    flattened every state to a qualified key (``GuardRecipients/RecipientFaulted``) and then looked
    up ``Next``, which names siblings UNQUALIFIED — so every nested walk dead-ended on its first
    hop and asserted nothing at all.

    Args:
      asl: The parsed state machine.

    Returns:
      Nothing; yields one quadruple per seed.

    Raises:
      None.
    """
    for label, _start, states in _containers(asl):
        for name, state in states.items():
            if _is_a_failure_seed(name, state, states):
                yield label, name, state, states


def _seed_violations(plane, asl):
    """Every downstream `Pass` read that a failure seed does not supply, across one machine.

    Collected rather than raised at the first offender, so a red run names every seed missing the
    key and the remedy can be applied in one pass instead of one run per seed.

    EVERY state's reads are checked, not only a ``Pass``'s. ``NotifyFailure`` is a Task and it
    sits between the seed and ``Failed`` on all eight planes; a reviewer planted
    ``"who.$": "$.nobody"`` in its ``Parameters`` and the whole file stayed green. This file
    already says elsewhere that such a read on a non-``Pass`` state is "an uncatchable
    States.Runtime on every share" — the walk simply was not asking.

    A Task between the seed and the read only ADDS keys through its ``ResultPath`` and never
    removes one, so anything read downstream must already come from the seed. That premise is
    MEASURED rather than guarded — no seed's forward walk crosses a Task with an absent
    ``ResultPath`` today, and nothing enforces that it stays so. The converse is a known
    FALSE-POSITIVE risk rather than a hole: a Task whose ``ResultPath`` adds a key that a later
    state reads would be reported here, because ``supplied`` is the seed's block and not a
    per-path accumulation. Measured at zero today, and a false positive is a red test somebody
    reads, which is the right way round for this guard to be wrong.

    Args:
      plane: The plane's name, for the message.
      asl: The parsed state machine.

    Returns:
      A sorted list of violation sentences, empty when the machine is sound.

    Raises:
      None.
    """
    found = []
    for label, seed_name, seed, states in _failure_seeds(asl):
        supplied = {key.removesuffix(".$") for key in (seed.get("Parameters") or {})}
        qualified = f"{label}/{seed_name}".lstrip("/")
        seen, frontier = set(), list(_targets(seed))
        while frontier:
            name = frontier.pop()
            if name in seen or name not in states:
                continue
            seen.add(name)
            state = states[name]
            missing = _read_keys(state.get("Parameters")) - supplied
            if missing:
                found.append(
                    f"{plane}: {name} ({state.get('Type')}) reads {sorted(missing)}, which "
                    f"{qualified} does not seed — an absent key raises an uncatchable "
                    "States.Runtime and the user is never notified"
                )
            frontier.extend(_targets(state))
    return sorted(found)


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: os.path.basename(os.path.dirname(p)))
def test_a_failure_seed_supplies_every_key_the_failure_terminal_reads(path):
    """A Pass state reading a key its seed does not supply KILLS the failure path.

    THE MECHANISM, which is why this is worth a general guard rather than a comment: a Pass
    state's JSONPath hard-fails on an ABSENT key with ``States.Runtime``, and
    ``States.Runtime`` is neither retriable nor catchable. So the failure terminal dies
    BEFORE its notify state, and the user hears nothing at all — on a request that already
    failed, which is precisely when they most need to hear something.

    It has bitten this arc twice. ``$.location`` was added to the failure terminal and had
    to be seeded (SPEC-112); ``$.reportKey`` was added and seeded the same way (SPEC-114).
    Both times the seeding was remembered. This makes forgetting it a test failure instead
    of a silent production one, and it is a real risk to automate away: the two edits are in
    different states, tens of lines apart, and the machine still parses fine without the
    seed.

    Recognition, the per-container walk and the collected violations all live in
    ``_is_a_failure_seed`` / ``_failure_seeds`` / ``_seed_violations``, which carry the reasoning
    for each. What this test adds is the per-plane parametrisation, so a red run says WHICH
    machine.

    Args:
      path: One plane's state-machine template.

    Returns:
      None.

    Raises:
      AssertionError: On a downstream read no seed supplies.
    """
    plane = os.path.basename(os.path.dirname(path))
    violations = _seed_violations(plane, _load(path))

    assert not violations, "\n".join(violations)


def _failure_seed_population():
    """Every (plane, qualified name) the recognition selects, across all eight templates.

    Args:
      None.

    Returns:
      A set of (plane, qualified name) pairs.

    Raises:
      None.
    """
    found = set()
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        for label, name, _state, _states in _failure_seeds(_load(path)):
            found.add((plane, f"{label}/{name}".lstrip("/")))
    return found


def test_the_failure_seed_sweep_selects_exactly_the_states_that_feed_a_failure_terminal():
    """The population is DERIVED by parsing, then held to a pinned membership.

    Both halves matter, for the reason the success-path sweep gives: deriving it makes a
    thirty-third seed joining the fleet a failure here rather than an unguarded failure path,
    and pinning the membership catches a recognition that quietly widened in one place and
    narrowed in another, which a count alone would not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derived set and the pinned set disagree.
    """
    found = _failure_seed_population()

    assert found, "the sweep selected nothing at all, so every assertion over it is vacuous"
    assert found == _FAILURE_SEEDS, (
        f"unexpected: {sorted(found - _FAILURE_SEEDS)}; "
        f"missing: {sorted(_FAILURE_SEEDS - found)}"
    )


def test_every_plane_contributes_a_failure_seed():
    """The positive control, and it is per PLANE rather than fleet-wide on purpose.

    A recognition change that stopped matching on one machine would leave that plane's failure
    path unguarded while the fleet-wide count stayed healthy enough to look right. Every plane
    notifies before it fails, so every plane has at least one seed by construction.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane contributes no seed.
    """
    seen = {plane for plane, _name in _failure_seed_population()}

    assert seen == _EXPECTED_ARCS, f"{sorted(_EXPECTED_ARCS - seen)} contribute no failure seed"


def test_the_failure_seed_walk_traverses_a_nested_container():
    """The repair for the dead-ending bug, which NO production template can demonstrate.

    Said plainly because it would otherwise look like an omission: with the per-container walk in
    place, all three nested seeds still reach ZERO states, because every one of them is
    ``End: true`` with no ``Next``. Fixing the bug therefore buys no new assertion over today's
    fleet — it buys the assertion back on the day a nested seed gains a successor, which is
    exactly when the old walk would have gone quiet.

    So the fixture is synthetic, and it asserts BOTH halves: that the per-container walk finds a
    nested violation, and that the old flattened lookup finds none. Only the second makes the
    first mean anything — a fixture that both walks fail on proves nothing about the repair.

    The violating read sits TWO hops from the seed, behind a relay, and that is the point rather
    than decoration: with it one hop away, truncating the walk to a seed's immediate successors —
    which is the very shape of the bug being repaired — left the whole suite green. The relay
    carries a ``ResultPath`` so that it merges rather than replaces; without one it is itself
    recognised as a seed by the graph half and the fixture yields two violations instead of the
    one it asserts.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the walk cannot see into a container, or if the old one could.
    """
    machine = {
        "StartAt": "Fan",
        "States": {
            "Fan": {
                "Type": "Map",
                "ItemsPath": "$.items",
                "ResultPath": "$.out",
                "ItemProcessor": {
                    "ProcessorConfig": {"Mode": "INLINE"},
                    "StartAt": "Work",
                    "States": {
                        "Work": {
                            "Type": "Task",
                            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "Seed"}],
                            "End": True,
                        },
                        "Seed": {
                            "Type": "Pass",
                            "Parameters": {"error.$": "$"},
                            "Next": "Relay",
                        },
                        "Relay": {"Type": "Pass", "ResultPath": "$.relay", "Next": "Shape"},
                        "Shape": {
                            "Type": "Pass",
                            "Parameters": {"who.$": "$.recipient"},
                            "Next": "Failed",
                        },
                        "Failed": {"Type": "Fail"},
                    },
                },
                "Next": "Done",
            },
            "Done": {"Type": "Succeed"},
        },
    }

    violations = _seed_violations("fixture", machine)

    assert len(violations) == 1, f"the walk did not reach into the container: {violations}"
    assert "Shape (Pass) reads ['recipient']" in violations[0], violations[0]
    assert machine["States"]["Fan"]["ItemProcessor"]["States"]["Seed"]["Next"] == "Relay", (
        "the violation must sit more than one hop from the seed, or a walk truncated to a seed's "
        "immediate successors passes this fixture"
    )

    flattened = dict(_states(machine))
    assert "Fan/Seed" in flattened and "Seed" not in flattened, (
        "the fixture no longer reproduces the bug's precondition — the old walk flattened to "
        "qualified keys while `Next` names siblings unqualified"
    )
    assert flattened["Fan/Seed"]["Next"] not in flattened, (
        "the old flattened lookup would have RESOLVED this hop, so the fixture cannot show what "
        "the per-container walk repaired"
    )


def test_the_read_extraction_sees_a_nested_path_and_a_seed_that_reaches_no_terminal():
    """Two discriminators whose failure would be silent, pinned directly rather than by effect.

    Neither can be reached through the fleet today, and both would otherwise be guards that
    cannot fail.

    The NESTED READ: widening ``_read_keys`` to the first path segment moved no plane — zero
    violations under either form — so nothing above would redden if it were narrowed back to a
    bare ``$.key``. What it protects is the one nested read this guard evaluates
    today — ``table-builder/RecordFailure`` reading ``$.space.database`` — where the old form
    extracted an empty set, so a seed that stopped supplying ``space`` produced no finding.

    The EMPTY TERMINAL SET: with a terminal defined as a state that hands control nowhere, every
    walk in the fleet reaches one, so the non-empty check never fires and reads as decorative. A
    cycle is the shape that reaches none, and a state whose only future is a loop seeds no
    failure terminal — asserting that keeps the check honest, and keeps it in place for the day
    the terminal definition is narrowed back to a state type, where it is the only thing standing
    between this sweep and thirty-five states.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a nested read is dropped, or a terminal-less state is called a seed.
    """
    assert _read_keys({"database.$": "$.space.database"}) == {"space"}, (
        "a nested read yields nothing, so any equality built on this compares two empty sets"
    )
    assert _read_keys({"a.$": "$.x", "b.$": "$.y.z", "c": "literal"}) == {"x", "y"}

    looping = {
        "Round": {"Type": "Pass", "Parameters": {"error.$": "$$.nope"}, "Next": "Again"},
        "Again": {"Type": "Pass", "Next": "Round"},
    }
    ending = {"Leaf": {"Type": "Pass", "Parameters": {"k.$": "$.k"}, "End": True}}
    assert _terminals_reachable_from("Leaf", ending) == [("Leaf", "Pass")], (
        "a state that hands control nowhere is a terminal whatever its TYPE; reading terminal as "
        "a Succeed/Fail state finds none inside an ItemProcessor, where `all([])` then calls "
        "every success leaf a failure seed"
    )

    assert _terminals_reachable_from("Round", looping) == []
    assert not _is_a_failure_seed("Round", looping["Round"], looping), (
        "a state whose only future is a cycle reaches no terminal, so `all([])` calls it a "
        "failure seed unless the non-empty check refuses it"
    )


def test_each_recognition_discriminator_decides_a_case_of_its_own():
    """One synthetic case per discriminator, because the fleet exercises none of them alone.

    An adversarial pass narrowed each of these in turn and the whole file stayed green: the fleet
    happens not to contain the shape that separates the correct form from the narrow one. A
    discriminator nothing can distinguish is a discriminator the next editor deletes, so each gets
    a case where it alone decides the answer.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any discriminator stops deciding its own case.
    """
    mixed = {
        "Seed": {"Type": "Pass", "Parameters": {"k": None}, "Next": "Fork"},
        "Fork": {"Type": "Choice", "Choices": [{"Next": "Bad"}], "Default": "Good"},
        "Bad": {"Type": "Fail"},
        "Good": {"Type": "Succeed"},
    }
    assert not _is_a_failure_seed("Seed", mixed["Seed"], mixed), (
        "a state that can still SUCCEED is not a failure seed; `any` in place of `all` calls it "
        "one, and the guard then demands failure-path seeding of the success path"
    )

    via_choice = {
        "Seed": {"Type": "Pass", "Parameters": {"k": None}, "Next": "Fork"},
        "Fork": {"Type": "Choice", "Choices": [{"Next": "Bad"}]},
        "Bad": {"Type": "Fail"},
    }
    assert _terminals_reachable_from("Seed", via_choice) == [("Bad", "Fail")], (
        "the terminal walk followed `Next` only, so a Fail reachable through a Choice is unseen "
        "and the Choice itself reads as the terminal"
    )
    assert _is_a_failure_seed("Seed", via_choice["Seed"], via_choice)

    replaced = {
        "Seed": {"Type": "Pass", "Parameters": {"error.$": "$"}, "ResultPath": "$.e", "Next": "Ok"},
        "Ok": {"Type": "Succeed"},
    }
    assert _is_a_failure_seed("Seed", replaced["Seed"], replaced), (
        "the structural test's `\"$\"` arm — the error REPLACED the state — is what identifies a "
        "PRE-IDENTITY seed, and nothing on the fleet distinguishes it today because every such "
        "state is graph-recognised as well; deleting it reddens nothing without this case"
    )

    discarding = {
        "Seed": {"Type": "Pass", "Parameters": {"k": None}, "ResultPath": None, "Next": "Bad"},
        "Bad": {"Type": "Fail"},
    }
    assert not _is_a_failure_seed("Seed", discarding["Seed"], discarding), (
        "an explicit `ResultPath: null` DISCARDS the block, so the state passes through unchanged "
        "and seeds nothing — telling that from an absent ResultPath needs `in`, not `.get()`, "
        "because both parse as None"
    )


def test_the_walk_follows_every_kind_of_edge_a_state_can_hand_control_along():
    """`Next` is one of four edges, and the fleet's failure paths exercise only some of them.

    Narrowing the walk to `Next` alone left the whole file green, and then hid a real
    `States.Runtime` planted behind a `Choice`. So the breadth is pinned on a fixture that routes
    a bad read behind each edge in turn.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any edge kind stops being followed.
    """
    for edge, wiring in (
        ("Choices", {"Type": "Choice", "Choices": [{"Next": "Bad"}]}),
        ("Default", {"Type": "Choice", "Choices": [], "Default": "Bad"}),
        ("Catch", {"Type": "Task", "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "Bad"}],
                   "End": True}),
    ):
        machine = {
            "StartAt": "Seed",
            "States": {
                "Seed": {"Type": "Pass", "Parameters": {"error.$": "$"}, "Next": "Hop"},
                "Hop": wiring,
                "Bad": {"Type": "Pass", "Parameters": {"who.$": "$.nobody"}, "Next": "Failed"},
                "Failed": {"Type": "Fail"},
            },
        }
        violations = _seed_violations("fixture", machine)

        assert len(violations) == 1 and "nobody" in violations[0], (
            f"a read behind a `{edge}` edge is invisible to the walk: {violations}"
        )


def test_a_read_nested_inside_a_payload_template_is_not_invisible():
    """A payload template nests, and a read one level down is exactly as fatal as one on top.

    `_intrinsics_in` in this file has recursed for that reason since it was written; this
    extraction did not, and a reviewer planted `{"detail": {"who.$": "$.nobody"}}` in archive's
    `RecordFailure` and watched every test pass. The two helpers now agree.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a nested read, or a deeply nested one, is dropped.
    """
    assert _read_keys({"detail": {"who.$": "$.nobody"}}) == {"nobody"}
    assert _read_keys({"a": {"b": {"c.$": "$.deep"}}}) == {"deep"}, (
        "the recursion stops after one level, so anything further down is unseen"
    )
    assert _read_keys({"items": [{"k.$": "$.inList"}]}) == {"inList"}
    assert _read_keys({"Payload.$": "$"}) == set(), (
        "a whole-state pass-through reads no NAMED key and must not be reported as one"
    )

    machine = {
        "StartAt": "Seed",
        "States": {
            "Seed": {"Type": "Pass", "Parameters": {"error.$": "$"}, "Next": "Notify"},
            "Notify": {
                "Type": "Task",
                "Parameters": {"Payload": {"who.$": "$.nobody"}},
                "Next": "Failed",
            },
            "Failed": {"Type": "Fail"},
        },
    }
    violations = _seed_violations("fixture", machine)

    assert len(violations) == 1 and "Notify (Task)" in violations[0], (
        f"a Task's payload read on the failure path is unchecked: {violations}"
    )


def test_the_widened_guard_catches_the_edit_that_passes_today():
    """The plant that exposed all of this, kept as a test rather than as a story.

    A reviewer added a key to archive's ``RecordFailure`` and to the two seeds the structural
    recognition can see — the obvious edit — and the suite stayed green while six archive failure
    paths would have hit an absent key inside a ``Pass``. That is an uncatchable
    ``States.Runtime``, so the execution dies BEFORE ``NotifyFailure`` and a user whose archive
    failed is told nothing at all.

    Both halves are asserted. Without the first, the plant could stop landing — a renamed state, a
    changed key — and this test would go quiet while reading exactly as green as a working one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the old recognition catches the plant, or the widened one misses it.
    """
    path = next(p for p in _TEMPLATES if os.path.basename(os.path.dirname(p)) == "archive")
    asl = _load(path)
    states = asl["States"]

    states["RecordFailure"]["Parameters"]["probe.$"] = "$.probe"
    seen_by_the_old_recognition = ("RequestFailureSeed", "ValidateFailureSeed")
    for name in seen_by_the_old_recognition:
        assert states[name]["Parameters"].get("error.$") in ("$", "$.error"), (
            f"{name} is no longer structurally recognised, so the plant no longer reproduces "
            "the edit that passed"
        )
        states[name]["Parameters"]["probe"] = None

    violations = _seed_violations("archive", asl)
    named = {line.split(" does not seed")[0].rsplit(" ", 1)[-1] for line in violations}

    assert named == {
        "NothingToArchiveSeed",
        "NothingToRestoreSeed",
        "RestoreIncompleteReturnedSeed",
        "RestoreTimedOutSeed",
        "RollbackReturnedSeed",
        "UnknownModeSeed",
    }, f"the widened guard named {sorted(named)}"

    assert all("reads ['probe']" in line for line in violations), (
        "the six seeds are named for a DIFFERENT missing key, so this test would pass on a "
        "neighbouring defect rather than on the plant it exists to reproduce"
    )

    structural_only = {
        name
        for name, state in states.items()
        if state.get("Type") == "Pass"
        and (state.get("Parameters") or {}).get("error.$") in ("$", "$.error")
    }
    for seed_name in structural_only:
        supplied = {key.removesuffix(".$") for key in states[seed_name]["Parameters"]}
        seen, frontier = set(), list(_targets(states[seed_name]))
        while frontier:
            name = frontier.pop()
            if name in seen or name not in states:
                continue
            seen.add(name)
            if states[name].get("Type") == "Pass":
                assert not _read_keys(states[name].get("Parameters")) - supplied, (
                    f"the OLD structural-only recognition already caught this plant via "
                    f"{seed_name}, so it is not the edit that passed today"
                )
            frontier.extend(_targets(states[name]))


# ── SPEC-225: one run, one trace — the success path ─────────────────────────────────────────

#: Every state whose own block must name the run's traceparent, as (plane, qualified name).
#: Pinned as MEMBERSHIP and not just a count, because a discriminator that widened in one place
#: and narrowed in another would keep the count and change the population.
_THREADING_STATES = frozenset({
    ("archive", "Validated"),
    ("archive", "NotifyArchived"),
    ("archive", "NotifyRestoreStarted"),
    ("archive", "NotifyRestored"),
    ("file-send", "Validated"),
    ("file-send", "ShapeSummary"),
    ("results-conversion", "Validated"),
    ("results-conversion", "Described"),
    ("results-conversion", "Converted"),
    ("table-share", "FinishRecipients/CreateTable"),
})

#: The planes whose state carries a request id where a Distributed Map can read it. table-share's
#: validator returns none and no state downstream of it holds one, so `"requestId.$": "$.requestId"`
#: in ITS BatchInput would be an uncatchable States.Runtime on every share.
#:
#: PINNED, not derived — and said plainly, because an earlier version of this comment claimed the
#: second while doing the first. Deriving it would mean reading each validator's return, which is
#: the very thing the guard below is checking the templates against; the two would then agree with
#: each other and with nothing else. A plane that starts or stops carrying a request id has to
#: change this line, which is the point.
_PLANES_WITH_A_REQUEST_ID = frozenset({"archive", "file-ops", "file-send"})


def _is_success_terminal(state, states, container_merges):
    """Whether a state's own output leaves the machine, or leaves a Map branch.

    Two shapes, and a walk that knows only one of them is wrong in a different direction each
    time. `End: true` is how a Map branch ends — no `Succeed` state exists inside an
    `ItemProcessor` anywhere in this fleet — while the top-level machines end by handing control
    to a `Succeed`. A rule that asked instead whether a state can REACH a `Succeed` would call
    `archive:NotifyArchived` terminal, which is one of the four Task blocks this sweep exists to
    find.

    Args:
      state: The state.
      states: Its container's states, since `Next` names siblings unqualified.

    Returns:
      True if nothing in this container reads what the state produced.

    Raises:
      None.
    """
    if state.get("End") is True:
        # A Map branch's leaf is only safe to exclude because its output becomes one ELEMENT of
        # the Map's result array, merged back under the Map's own ResultPath into a state that
        # still carries the key. A Map with NO ResultPath replaces the state with that array, and
        # then the leaf really is the last place the key could live. The precondition is checked
        # rather than stated: it holds for all three inline Maps today and nothing made it hold.
        return container_merges
    following = state.get("Next")
    return bool(following) and states.get(following, {}).get("Type") == "Succeed"


def _reaches_a_success_terminal(start, states):
    """Whether a state can finish successfully without leaving through a `Catch`.

    `Catch` edges are deliberately NOT followed: every Task with a catcher can reach the failure
    terminal, so following them selects almost the whole machine. What is being asked is whether
    this state sits on a path that can succeed at all — a failure seed cannot, and those belong
    to SPEC-227.

    Args:
      start: The state name to walk from.
      states: Its container's states.

    Returns:
      True if some success terminal is reachable.

    Raises:
      None.
    """
    seen, frontier = set(), [start]
    while frontier:
        name = frontier.pop()
        if name in seen or name not in states:
            continue
        seen.add(name)
        state = states[name]
        if state.get("Type") == "Succeed" or state.get("End") is True:
            return True
        for target in (state.get("Next"), state.get("Default")):
            if target:
                frontier.append(target)
        for choice in state.get("Choices") or []:
            if choice.get("Next"):
                frontier.append(choice["Next"])
    return False


def _blocks_that_name_their_fields(asl):
    """Yields (qualified name, the block) for every state that would DROP a new key.

    Most threading is free: a Task passing `"Payload.$": "$"` with `"OutputPath": "$.Payload"`
    carries a new key untouched. These are the states that do not, and finding them needs five
    discriminators — each of which was established by building the sweep without it and reading
    what came back:

    1. A `Pass` carrying a `ResultPath` MERGES under that path and drops nothing. Without this,
       SEVEN `StampExecution`-style states join the population as false positives — measured by
       disabling the rule, which takes the population from ten to seventeen.
    2. A Task's `Parameters.Payload` block IS its Lambda's input, so a field-naming one drops a
       key exactly as a `Pass` does. Four qualify.
    3. Failure-path states are excluded — 29 of them, which SPEC-227 owns.
    4. Inside a Map branch a success terminal is `End: true`, not a `Succeed` state, which is
       what `_is_success_terminal` and `_reaches_a_success_terminal` both have to know.
    5. A `Pass` that is ITSELF a success terminal is excluded, and for two different reasons
       worth keeping apart. A Map branch's leaf becomes one ELEMENT of the Map's result array,
       merged back under the Map's own `ResultPath` into a state that still carries the
       traceparent — so nothing is lost by leaving it out. A `Pass` whose `Next` is a `Succeed`
       produces the EXECUTION's output, which no state reads. Without this fifth rule the first
       four select twenty-one states rather than ten. It is applied to `Pass` states only: a
       Task's `Payload` is its Lambda's input, read wherever the Task sits.

    Args:
      asl: The parsed state machine.

    Returns:
      Nothing; yields one pair per state.

    Raises:
      None.
    """
    by_name = dict(_states(asl))
    for label, _start, states in _containers(asl):
        container = label.lstrip("/").split("/")[0] if label else None
        # The top level always "merges" in the sense that matters: its terminals ARE the run's
        # output. Inside a Map, it depends on that Map's own ResultPath.
        merges = True if container is None else "ResultPath" in by_name.get(container, {})
        for name, state in states.items():
            qualified = f"{label}/{name}".lstrip("/")
            if state.get("Type") == "Pass":
                block = state.get("Parameters")
                if "ResultPath" in state and state["ResultPath"] is not None:
                    continue
                if not isinstance(block, dict):
                    continue
                if _is_success_terminal(state, states, merges):
                    continue
            elif state.get("Type") == "Task":
                block = (state.get("Parameters") or {}).get("Payload")
                if not isinstance(block, dict):
                    continue
            else:
                continue
            if not _reaches_a_success_terminal(name, states):
                continue
            yield qualified, block


def _threading_population():
    """Every (plane, state) the sweep selects, across all eight templates.

    Args:
      None.

    Returns:
      A set of (plane, qualified name) pairs.

    Raises:
      None.
    """
    found = set()
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        for qualified, _block in _blocks_that_name_their_fields(_load(path)):
            found.add((plane, qualified))
    return found


def test_the_sweep_selects_exactly_the_states_that_would_drop_the_traceparent():
    """The population is DERIVED by parsing, then held to a pinned membership.

    Both halves matter. Deriving it is what makes a ninth state joining the fleet a failure here
    rather than a silently unthreaded verb; pinning the membership is what makes a discriminator
    that quietly widened or narrowed fail, which a count alone would not — a rule that gained one
    state and lost another keeps the count and changes the answer.
    """
    found = _threading_population()

    assert found, "the sweep selected nothing at all, so every assertion over it is vacuous"
    assert found == _THREADING_STATES, (
        f"unexpected: {sorted(found - _THREADING_STATES)}; "
        f"missing: {sorted(_THREADING_STATES - found)}"
    )


def test_the_sweep_would_notice_a_field_naming_state_it_does_not_know_about():
    """The positive control for the discriminators, since the test above asserts an equality.

    A sweep that returned the pinned set by accident — because its discriminators cancelled out —
    reads identically to one that works. This plants a state of exactly the shape the sweep is
    looking for and requires it to come back.
    """
    machine = {
        "StartAt": "Validated",
        "States": {
            # Threaded THROUGH a later state, which is what makes it a state that can drop a key.
            # An earlier version of this fixture pointed `Validated` straight at `Succeed` and the
            # sweep correctly refused it — a bad fixture and a dead rule read the same on a red run.
            "Validated": {"Type": "Pass", "Parameters": {"requestId.$": "$.requestId"}, "Next": "Work"},
            "Work": {"Type": "Task", "Parameters": {"Payload.$": "$"}, "Next": "Terminal"},
            "Merged": {"Type": "Pass", "Parameters": {"x.$": "$.x"}, "ResultPath": "$.m", "Next": "Work"},
            "Terminal": {"Type": "Pass", "Parameters": {"y.$": "$.y"}, "Next": "Done"},
            "Done": {"Type": "Succeed"},
            "Seed": {"Type": "Pass", "Parameters": {"error.$": "$"}, "Next": "Failed"},
            "Failed": {"Type": "Fail"},
        },
    }
    selected = {name for name, _block in _blocks_that_name_their_fields(machine)}

    assert "Validated" in selected, "the sweep cannot see a field-naming Pass at all"
    assert "Merged" not in selected, "a Pass with a ResultPath merges and must not be selected"
    assert "Terminal" not in selected, "a Pass handing straight to Succeed produces the output"
    assert "Seed" not in selected, "a state that can only reach a Fail is SPEC-227's, not this sweep's"

    # Discriminator 5 excludes a Map leaf because the Map MERGES its result back. Take the merge
    # away and the leaf is the last place the key could live, so it must come back into the
    # population — otherwise the rule's justification is a sentence nothing enforces.
    def _with_map(result_path):
        """One machine holding an inline Map whose leaf names its fields.

        Args:
          result_path: The Map's ResultPath, or None to omit it entirely.

        Returns:
          The machine.

        Raises:
          None.
        """
        mapping = {
            "Type": "Map",
            "ItemsPath": "$.items",
            "ItemProcessor": {
                "ProcessorConfig": {"Mode": "INLINE"},
                "StartAt": "Leaf",
                "States": {"Leaf": {"Type": "Pass", "Parameters": {"k.$": "$.k"}, "End": True}},
            },
            "Next": "Done",
        }
        if result_path is not None:
            mapping["ResultPath"] = result_path
        return {"StartAt": "Fan", "States": {"Fan": mapping, "Done": {"Type": "Succeed"}}}

    merging = {n for n, _b in _blocks_that_name_their_fields(_with_map("$.out"))}
    replacing = {n for n, _b in _blocks_that_name_their_fields(_with_map(None))}

    assert "Fan/Leaf" not in merging, "a merged Map's leaf loses nothing and must stay excluded"
    # No machine has a Parallel today, so the walk's blindness to one could only ship silently.
    parallel = {
        "StartAt": "Split",
        "States": {
            "Split": {
                "Type": "Parallel",
                "Branches": [{
                    "StartAt": "Named",
                    "States": {
                        "Named": {"Type": "Pass", "Parameters": {"k.$": "$.k"}, "Next": "Work"},
                        "Work": {"Type": "Task", "Parameters": {"Payload.$": "$"}, "End": True},
                    },
                }],
                "ResultPath": "$.out",
                "Next": "Done",
            },
            "Done": {"Type": "Succeed"},
        },
    }
    assert "Split[0]/Named" in {n for n, _b in _blocks_that_name_their_fields(parallel)}, (
        "the sweep cannot see inside a Parallel branch, so the first one added would carry "
        "field-naming states nothing checks"
    )

    assert "Fan/Leaf" in replacing, (
        "a Map with no ResultPath REPLACES the state with its result array, so its leaf is the "
        "last place the key could live and the sweep has to demand it there"
    )


@pytest.mark.parametrize(
    "plane,state", sorted(_THREADING_STATES), ids=lambda v: v if isinstance(v, str) else str(v)
)
def test_every_field_naming_success_state_names_the_traceparent(plane, state):
    """Each one, named individually, so a red run says WHICH plane and WHICH state.

    A single assertion over the whole set fails once and names the first offender, and the
    remedy — adding the key back — is per state.
    """
    path = next(p for p in _TEMPLATES if os.path.basename(os.path.dirname(p)) == plane)
    blocks = dict(_blocks_that_name_their_fields(_load(path)))

    assert state in blocks, f"{plane}:{state} is no longer selected by the sweep"
    assert "traceparent.$" in blocks[state], (
        f"{plane}:{state} names its fields individually and does not name `traceparent`, so the "
        "run's trace stops here and every verb after it opens its own"
    )


def test_every_distributed_map_carries_the_traceparent_to_its_children():
    """A Distributed Map's child cannot see the parent state, so the key travels in `BatchInput`.

    All six read a JSONL manifest through `ItemReader` and none has an `ItemSelector`, so the
    child receives `{"Items": [...]}` and nothing else. Writing the traceparent into the manifest
    instead would repeat it on every line of a dataset that can hold tens of thousands.

    The count is DERIVED by parsing rather than written down, so a seventh Distributed Map fails
    here on the day it is added rather than shipping unjoinable.
    """
    maps, batched = [], []
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        for name, state in _states(_load(path)):
            if state.get("Type") != "Map" or "ItemBatcher" not in state:
                continue
            maps.append((plane, name))
            if "traceparent.$" in (state["ItemBatcher"].get("BatchInput") or {}):
                batched.append((plane, name))

    assert maps, "no Distributed Map found, so this proves nothing"
    assert sorted(batched) == sorted(maps), (
        f"{sorted(set(maps) - set(batched))} hand their children no traceparent"
    )


def test_no_batch_input_reads_a_path_its_planes_state_does_not_supply():
    """`BatchInput`'s paths resolve against the MAP STATE's input, so an absent one is fatal.

    table-share's validator returns no `requestId` and no state downstream of it holds one, so
    `"requestId.$": "$.requestId"` there is an uncatchable `States.Runtime` on every share — not
    a missing field. The pair is per-plane, derived from what the plane's state actually carries.

    Asserted in BOTH directions, because a rule that only forbade the absent key would be
    satisfied by a fleet that dropped the request id everywhere.
    """
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        for name, state in _states(_load(path)):
            batch = (state.get("ItemBatcher") or {}).get("BatchInput")
            if not batch:
                continue
            reads_request_id = "requestId.$" in batch
            supplies = plane in _PLANES_WITH_A_REQUEST_ID
            assert reads_request_id == supplies, (
                f"{plane}:{name}'s BatchInput "
                + ("reads `$.requestId`, which this plane's state never carries — an uncatchable "
                   "States.Runtime on every run" if reads_request_id else
                   "does not read `$.requestId`, which this plane does supply, so its Map "
                   "children cannot be joined to their run by request id")
            )


#: The run-level failure-path states that must name the traceparent, as (plane, state).
#: Split by whether the state can READ it off the state or must supply a literal, because the two
#: are different edits and a state moving between them is exactly what this pins.
#:
#: Nested seeds are absent BY RULE, not by oversight: the three of them are `End: true` inside an
#: `ItemProcessor` and cannot reach `RecordFailure` at all — their output becomes one element of
#: their Map's result array. `_failure_path_threading` asserts that rule rather than restating it.
_PRE_IDENTITY_SEEDS = frozenset(
    (plane, "ValidateFailureSeed") for plane in _EXPECTED_ARCS
)


def _failure_path_threading():
    """Every run-level failure-path state, split into the ones that read and the ones that cannot.

    The discriminator is DERIVED, not listed: a seed whose ``Parameters["error.$"]`` is ``"$"`` had
    the error REPLACE the whole state, so nothing from before the failure survives and there is no
    ``$.traceparent`` to read. Every other seed stands on a validated state — each already reads
    ``$.requestId`` or ``$.actor`` today and would be raising ``States.Runtime`` if it did not.

    Args:
      None.

    Returns:
      A (readers, literals) pair of (plane, state) sets.

    Raises:
      None.
    """
    readers, literals = set(), set()
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        for label, name, state, _states in _failure_seeds(_load(path)):
            if label:
                continue
            block = state.get("Parameters") or {}
            (literals if block.get("error.$") == "$" else readers).add((plane, name))
    return readers, literals


def test_the_pre_identity_seeds_are_the_ones_the_error_replaced():
    """The split is derived; this pins it, and pins that nested seeds are excluded BY RULE.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the split moves, or a nested seed joins the population.
    """
    readers, literals = _failure_path_threading()

    assert literals == _PRE_IDENTITY_SEEDS, (
        f"unexpected: {sorted(literals - _PRE_IDENTITY_SEEDS)}; "
        f"missing: {sorted(_PRE_IDENTITY_SEEDS - literals)}"
    )
    assert len(readers) == 21, f"the failure path has {len(readers)} readers, not 21"
    assert not {name for _plane, name in readers | literals if "/" in name}, (
        "a NESTED seed joined the run-level failure path; the three of them are `End: true` "
        "inside an ItemProcessor and cannot reach RecordFailure, so they carry no traceparent"
    )
    assert len(_failure_seed_population()) == len(readers) + len(literals) + 3, (
        "the run-level population plus the three nested seeds no longer accounts for every seed"
    )


@pytest.mark.parametrize(
    "plane,state",
    sorted(_failure_path_threading()[0] | _failure_path_threading()[1]),
    ids=lambda v: v,
)
def test_every_failure_path_state_names_the_traceparent(plane, state):
    """Each one named individually, so a red run says WHICH plane and WHICH state.

    A failed run's terminal and its notification sit in the run's trace only if every state on the
    way names the key: `RecordFailure` is a `Pass` naming its fields, so a seed that does not
    supply the traceparent drops it, and `notify-failure` — a separate invocation, reached through
    `"Payload.$": "$"` — then opens a fresh trace on exactly the run an operator went looking for.

    Args:
      plane: The plane's name.
      state: The state's name.

    Returns:
      None.

    Raises:
      AssertionError: If the state does not name the traceparent, or names it the wrong way.
    """
    path = next(p for p in _TEMPLATES if os.path.basename(os.path.dirname(p)) == plane)
    block = dict(_states(_load(path)))[state].get("Parameters") or {}
    _readers, literals = _failure_path_threading()

    if (plane, state) in literals:
        assert "traceparent" in block and block["traceparent"] is None, (
            f"{plane}:{state} is the PRE-IDENTITY seed — the error replaced the state, so there "
            "is no `$.traceparent` to read and it must supply a literal null. Omitting the key "
            "instead makes RecordFailure's read an uncatchable States.Runtime"
        )
        assert "traceparent.$" not in block, (
            f"{plane}:{state} reads `$.traceparent` off a state the error REPLACED — the read "
            "cannot resolve and it kills the execution before NotifyFailure"
        )
    else:
        assert block.get("traceparent.$") == "$.traceparent", (
            f"{plane}:{state} does not read the run's traceparent, so the failed run's "
            "notification opens a trace of its own"
        )


def _traceparent_reads(asl):
    """Yields (container label, qualified name, the reference path) for every traceparent read.

    Args:
      asl: The parsed state machine.

    Returns:
      Nothing; yields one triple per read, across `Parameters`, a Task's `Payload`, and a
      Distributed Map's `ItemBatcher.BatchInput`.

    Raises:
      None.
    """
    for label, _start, states in _containers(asl):
        for name, state in states.items():
            parameters = state.get("Parameters") or {}
            payload = parameters.get("Payload") if isinstance(parameters.get("Payload"), dict) else None
            batch = (state.get("ItemBatcher") or {}).get("BatchInput")
            for block in (parameters, payload, batch):
                if block and "traceparent.$" in block:
                    yield label, f"{label}/{name}".lstrip("/"), block["traceparent.$"]


def test_every_traceparent_read_names_a_path_its_state_actually_supplies():
    """Naming the key is not enough — the PATH has to resolve, and nothing else checks that.

    A reference path to an ABSENT key is `States.Runtime`, which is neither retriable nor
    catchable, so a mistyped path is not a missing log field: it kills the execution before
    `NotifyFailure`. Measured, and this guard exists because of it: changing
    `results-conversion:Converted` to read `$.nope` left every other test in this file AND the
    end-to-end guard green, because the sweep asks whether the key is named and the driven runs
    only cover file-send and archive.

    Two forms are legitimate and they are checked differently rather than pattern-matched
    together:

    * At the top level, and in a Distributed Map's `BatchInput` — which resolves against the MAP
      STATE's input, itself a top-level state — the state carries the key directly, so the path
      is `$.traceparent` and nothing else.
    * Inside an `ItemProcessor`, the child sees the item the Map's `ItemSelector` built, so a
      nested path is only resolvable if the selector binds that block to the whole parent state.
      That is checked against the selector rather than allowed by shape: `$.request.traceparent`
      is correct exactly when the Map maps `"request.$": "$"`.
    """
    checked = 0
    for path in _TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        asl = _load(path)
        states = dict(_states(asl))
        for label, qualified, reference in _traceparent_reads(asl):
            checked += 1
            if not label:
                assert reference == "$.traceparent", (
                    f"{plane}:{qualified} reads {reference!r}; a top-level state carries the key "
                    "directly, and an unresolvable path is an uncatchable States.Runtime"
                )
                continue

            container = label.lstrip("/").split("/")[0]
            selector = states[container].get("ItemSelector") or {}
            bound_to_the_parent = {
                key.removesuffix(".$") for key, value in selector.items() if value == "$"
            }
            assert bound_to_the_parent, (
                f"{plane}:{qualified} sits in {container}, whose ItemSelector binds no block to "
                "the parent state, so no nested path can resolve"
            )
            # `$.traceparent` is NOT automatically resolvable here: inside an ItemProcessor the
            # state IS the item the selector built, so a top-level read resolves only if the
            # selector puts the key there itself. An earlier version of this guard allowed it
            # unconditionally, which would have passed the one edit that breaks every share.
            selected = {key.removesuffix(".$") for key in selector}
            allowed = {f"$.{block}.traceparent" for block in bound_to_the_parent}
            if "traceparent" in selected:
                allowed.add("$.traceparent")
            assert reference in allowed, (
                f"{plane}:{qualified} reads {reference!r}, which {container}'s ItemSelector does "
                f"not supply — it builds {sorted(selected)} and binds {sorted(bound_to_the_parent)} "
                f"to the parent state, so {sorted(allowed)} are the resolvable paths"
            )

    assert checked == 37, (
        f"the sweep found {checked} traceparent reads and the fleet has 37 — ten success states "
        "(`_THREADING_STATES`), six Distributed Maps (derived by the guard above), and twenty-one "
        "on the failure path (`_failure_path_threading`, which pins that number) — so it is "
        "looking at the wrong thing. The eight pre-identity seeds are NOT reads: they supply a "
        "literal null, which is why the total is not 45"
    )
