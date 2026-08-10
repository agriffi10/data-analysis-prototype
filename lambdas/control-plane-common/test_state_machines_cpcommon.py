"""Invariants that must hold in EVERY control-plane state machine.

These read the deployed ASL templates under infra/ rather than a copy, because the whole
point is to fail when one of them drifts. They are not about any single arc — they encode
rules that were each learned by breaking production.

Runnable under pytest or directly: python3 test_state_machines_cpcommon.py.
"""

import glob
import inspect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest

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
_EXPECTED_ARCS = {"data-quality", "shared-spaces", "table-builder", "table-share"}

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


def test_the_intrinsic_scan_sees_a_result_selector():
    """Guards the guard (SPEC-153 FR-003): synthetic machine, no production file touched.

    A ``States.StringToJson`` in a ``ResultSelector`` is exactly as uncatchable as one in
    ``Parameters``, and until this spec the scan above walked straight past it — so the
    check that four machines are clean proved less than it read as. This fixture is the
    difference between the scan being clean and the scan being blind.
    """
    synthetic = {
        "States": {
            "Decode": {
                "Type": "Task",
                "ResultSelector": {"cause.$": "States.StringToJson($.error.Cause)"},
            }
        }
    }

    assert _throwing_intrinsics(synthetic) == [
        "Decode.ResultSelector.cause.$ = States.StringToJson($.error.Cause)"
    ]


def test_the_intrinsic_scan_is_quiet_on_a_clean_machine():
    """The other half of the guard: a scan that flagged everything would also pass above."""
    synthetic = {
        "States": {
            "Fan": {
                "Type": "Map",
                "ItemSelector": {"item.$": "$$.Map.Item.Value", "ctx.$": "$"},
            }
        }
    }

    assert _throwing_intrinsics(synthetic) == []


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


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_the_raw_error_reaches_the_notifier_undecoded(path):
    """SPEC-152 FR-004. The other half of the throwing-intrinsic guard above.

    That test says no state MAY decode a Cause. This one says the undecoded object actually
    ARRIVES — which is a different claim, and the one the notifier depends on. A plane could
    satisfy the first perfectly by copying `$.error.Error` alone, or by reaching into
    `$.error.Cause` with a plain JSONPath: no intrinsic, no States.Runtime, and
    `failure_reason` gets a string it cannot decode instead of the ``{Error, Cause}`` pair
    it was written for. The user then hears the generic sentence on a failure that had a
    real reason available.

    So: the recorded-failure state must copy ``$.error`` WHOLE. A bare JSONPath copy of a
    key that always exists is the one form that cannot fail, which is why it is also the
    only form allowed here.
    """
    plane = os.path.basename(os.path.dirname(path))
    if plane in _NOTIFY_FAILURE_EXEMPT:
        pytest.skip(f"{plane} is exempt: {_NOTIFY_FAILURE_EXEMPT[plane]}")

    states = dict(_states(_load(path)))
    assert "RecordFailure" in states, f"{plane} has no RecordFailure state"
    assert states["RecordFailure"]["Parameters"].get("error.$") == "$.error", (
        f"{plane}: RecordFailure must copy $.error WHOLE — the notifier decodes the "
        f"{{Error, Cause}} pair in Python, and a narrowed copy silently degrades every "
        f"message to the generic"
    )
    assert states["NotifyFailure"]["Parameters"]["Payload.$"] == "$", (
        f"{plane}: NotifyFailure must forward the whole recorded-failure object"
    )


@pytest.mark.parametrize("path", _TEMPLATES, ids=lambda p: p.split(os.sep)[-2])
def test_every_transition_resolves_and_every_state_is_reachable(path):
    """A dangling Next is a deploy-time error; an orphan state is dead code that reads as
    live. Both are cheap to check and neither is visible in a diff."""
    asl = _load(path)

    def check(states, start, scope):
        names = set(states)
        targets = set()
        for name, state in states.items():
            if state.get("Next"):
                targets.add(state["Next"])
            for catch in state.get("Catch", []) or []:
                targets.add(catch["Next"])
            for choice in state.get("Choices", []) or []:
                if choice.get("Next"):
                    targets.add(choice["Next"])
            if state.get("Default"):
                targets.add(state["Default"])
            for key in ("Iterator", "ItemProcessor"):
                if key in state:
                    check(state[key]["States"], state[key]["StartAt"], f"{scope}{name}/")
            for branch in state.get("Branches", []) or []:
                check(branch["States"], branch["StartAt"], f"{scope}{name}/")

        assert not targets - names, f"{scope}: transitions to missing states {sorted(targets - names)}"
        assert not names - targets - {start}, f"{scope}: unreachable states {sorted(names - targets - {start})}"

    check(asl["States"], asl["StartAt"], os.path.basename(os.path.dirname(path)) + ":")


#: Step Functions' hard cap on a state payload. Breaching it raises
#: States.DataLimitExceeded, which is thrown OUTSIDE every Catch.
_STATE_PAYLOAD_LIMIT = 256 * 1024


def _definition_at_cap(cap_bytes):
    """A cloned definition sized to exactly the cap inspect-source enforces.

    Shaped like tscommon.glue.clone_definition's real output — lowercase name/type/comment
    per column plus partitionKeys, serde parameters and tableProperties — not the
    {Name, Type} pairs an earlier model used, which understated it by roughly 3x.
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

    FOUR things hold it: SHARE_MAX_RECIPIENTS (how many entries), errors.MAX_DETAIL_CHARS
    (how big a Cause), SHARE_MAX_DEFINITION_BYTES (how big the cloned schema — the last
    unbounded, user-controlled term), and the pointer (no object list at all). No single one
    suffices: at the 32 KB Cause ceiling the records breach on their own at seven recipients,
    and a 1,000-column commented definition breached at 150% even after the pointer landed.

    **SPEC-160 split the one Map into three states, so this now models TWO peaks.** The old
    single-peak model went stale the moment the machine grew a guard Map: a raw Cause per refused
    recipient appears in `guardResults`, and if the collector both kept that array and re-emitted
    the raw error, the finish Map's merge would hold THREE copies of every refusal at once — which
    measured at 108% of the limit for 50 conflicting recipients, i.e. a silent breach in the most
    ordinary case there is (re-sharing a table most recipients already have). Two rules keep it
    where it was: `collect-transfer-results` CONSUMES `guardResults` rather than passing it on, and
    it carries the DECODED reason instead of the raw error. Both are modelled below, so undoing
    either fails here rather than in production.
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
        "actor": "a" * 64,
        "source": {"database": "d" * 64, "table": "t" * 64},
        "tableName": "n" * 64,
        "recipients": [{"kind": "space", "name": "s" * 64, "valid": True} for _ in range(recipients)],
        # The cloned definition still rides INLINE, and it is USER-CONTROLLED (columns with
        # comments, plus the source's Glue table properties, copied verbatim). An earlier
        # version of this test modelled 300 bare {Name, Type} pairs and called it "bounded by
        # column count" — it was not: 1,000 columns with 255-char comments reached 150% of the
        # limit even WITH the plan by pointer. It is bounded now because inspect-source
        # rejects an oversized definition (SHARE_MAX_DEFINITION_BYTES), so the worst case is
        # modelled at exactly that cap rather than at a column count someone guessed.
        "tableDefinition": _definition_at_cap(ts_config.SHARE_MAX_DEFINITION_BYTES),
        "location": {"bucket": "b" * 63, "prefix": "p" * 200},
        # THE POINT OF PR #256: a key, not up to 1000 {relKey, size} entries.
        "copyPlanKey": "table-share/" + ("0" * 64) + "/copy-plan.json",
        "objectCount": ts_config.SHARE_MAX_OBJECTS,
        "partitioned": True,
        "execution": {"name": "e" * 80},
        "transfer": {
            "manifestBucket": "b" * 63,
            "manifestKey": "table-share/" + ("0" * 64) + "/" + ("e" * 80) + "/transfer-manifest.jsonl",
            "resultsBucket": "b" * 63,
            "resultsPrefix": "table-share/" + ("0" * 64) + "/" + ("e" * 80) + "/results",
            "itemCount": ts_config.SHARE_MAX_OBJECTS * recipients,
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


def test_the_copy_plan_never_returns_to_the_state():
    """The regression that would silently undo this change.

    Putting the object list back on the state is a one-line edit in inspect-source, it
    breaks nothing visible, and it re-arms States.DataLimitExceeded on the Map for large
    partitioned tables. Asserted against the verb's actual output shape.
    """
    sys.path.insert(0, os.path.join(_HERE, "..", "table-share-inspect-source"))
    sys.path.insert(0, os.path.join(_HERE, "..", "table-share-common"))
    import table_share_inspect_source as verb

    source = inspect.getsource(verb)
    emitted = source[source.index("return {"):]

    assert '"copyPlanKey"' in emitted, "inspect-source must emit the plan KEY"
    assert '"objects"' not in emitted, (
        "inspect-source is putting the object list back on the state — that is what pushed "
        "the Map's payload to 95% of the 256 KB limit"
    )


def _read_keys(parameters):
    """The top-level ``$.key`` names a Parameters block reads (its `"x.$": "$.key"` pairs)."""
    keys = set()
    for name, value in (parameters or {}).items():
        if not name.endswith(".$") or not isinstance(value, str):
            continue
        match = re.fullmatch(r"\$\.([A-Za-z0-9_]+)", value.strip())
        if match:
            keys.add(match.group(1))
    return keys


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

    A "failure seed" is identified structurally — a Pass state that captures the whole error
    (``"error.$": "$"``) — so this holds for any arc that grows one, not just this one.
    """
    asl = _load(path)
    states = dict(_states(asl))
    seeds = {
        name: state
        for name, state in states.items()
        if state.get("Type") == "Pass" and state.get("Parameters", {}).get("error.$") == "$"
    }
    if not seeds:
        pytest.skip("no failure-seed state in this machine")

    for seed_name, seed in seeds.items():
        supplied = set(seed.get("Parameters", {}))
        # "error.$" supplies "error"; a literal null key supplies itself.
        supplied = {name.removesuffix(".$") for name in supplied}

        # Walk forward from the seed to every Pass state it can reach, collecting what they
        # read. A Task in between only ADDS keys (ResultPath) — it never removes one — so
        # anything a downstream Pass reads must already come from the seed.
        seen, frontier = set(), [seed.get("Next")]
        while frontier:
            name = frontier.pop()
            if not name or name in seen or name not in states:
                continue
            seen.add(name)
            state = states[name]
            if state.get("Type") == "Pass":
                missing = _read_keys(state.get("Parameters")) - supplied
                assert not missing, (
                    f"{os.path.basename(os.path.dirname(path))}: {name} reads "
                    f"{sorted(missing)}, which {seed_name} does not seed — an absent key "
                    f"raises an uncatchable States.Runtime and the user is never notified"
                )
            frontier.append(state.get("Next"))
            frontier.extend(c.get("Next") for c in state.get("Catch", []) or [])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
