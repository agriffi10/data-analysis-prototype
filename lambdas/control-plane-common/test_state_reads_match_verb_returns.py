"""One cross-check, over every plane, holding a field-naming state to its verb's real return.

THE GAP THIS FILLS. A Task hands its output on whole, so nothing in a Task-to-Task chain notices a
verb renaming a field. A `Pass` that names each key does notice — but only in one direction, and
only where somebody wrote the check. Three planes had one; five had none, and archive's machine
said in its own comments that it did.

DIRECTION IS THE POINT. `reads ⊆ returns` catches a state reading a key its verb does not return,
which is a `States.Runtime` at execution and therefore loud. It cannot catch a verb returning a key
the state DROPS, which is silent — and that is exactly how the run's traceparent went missing.

BARE SET EQUALITY IS STILL TOO STRONG. A state may drop a key deliberately — `table-share`'s Map
children shape a per-recipient outcome and drop the request block whole. So the form is
`reads == returns - declared_drops`, with the drop set pinned PER PAIR, which turns a dropped key
from a silent event into a written decision and reddens on a key added to a verb's return as well as
on one removed. No checked pair may drop `traceparent`; that is refused rather than merely unused.

AND DRIVING A VERB ONLY ANSWERS THE QUESTION FOR SOME VERBS. This is the discriminator that decides
what this file covers, and it is about evidence rather than cost. A verb returning `{**event, …}`
INHERITS its key set from its input, so driving it with a hand-built mid-chain state compares that
fixture with itself and would agree with any state at all. Eleven pairs exist; SEVEN have a verb
that builds its own return, rooted at the plane's real API envelope or the plane's own Map-item
fixture, and those are checked here. The other FOUR are recorded in `_ECHOING` with the reason,
because for three of them a faithful drive is not merely expensive but impossible: a Distributed Map
sits in the chain and the state after it is built from a Map Run export no drive can produce without
hand-shaping the very thing under test.

What still covers the four, stated exactly because a looser version of this sentence was wrong:
`file-send/ShapeSummary` is in `_THREADING_STATES` and the success-path sweep pins that it names the
traceparent. The other three are NOT, and are not meant to be — they are success terminals whose
`Next` is `Succeeded`, which is precisely why they may drop the key, and
`test_no_checked_pair_is_allowed_to_drop_the_traceparent` asserts that rather than assuming it. The
two collectors' exclusion sets are pinned verb-side in `test_one_run_one_trace.py`.

Runnable under pytest or directly: python3 test_state_reads_match_verb_returns.py.
"""

import ast
import json
import os
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_LAMBDAS = _HERE.parent
for _dir in (
    ".",
    "control-plane-common",
    "archive-common",
    "file-send-common",
    "table-share-common",
    "results-conversion-common",
    "archive-validate-authorize",
    "archive-write-receipt",
    "data-quality-drop-temp-tables",
    "data-quality-common",
    "file-send-validate-authorize",
    "file-send-collect-transfer-results",
    "results-conversion-validate-authorize",
    "results-conversion-describe-results",
    "results-conversion-convert",
    "table-share-collect-transfer-results",
    "table-share-check-target-absent",
    "table-share-create-table",
):
    sys.path.insert(0, str(_LAMBDAS / _dir))

import pytest
import test_state_machines_cpcommon as machines
from cpcommon import clients
from token_shapes import JWT_SHAPED

#: Every replacing `Pass` the walk-back rule pairs with exactly one producing Task, across the
#: fleet. Derived by `_pairs` and pinned here as a MEMBERSHIP, because a rule that widened in one
#: place and narrowed in another keeps the count and changes the answer.
#:
#: This is the whole population. `_CHECKED` and `_ECHOING` partition it, and that partition is
#: asserted, so a pair cannot fall out of both.
_PAIRS = {
    ("archive", "Validated"): "ValidateAuthorize",
    ("archive", "ArchiveComplete"): "WriteReceipt",
    ("data-quality", "RecordSuccess"): "DropTempTables",
    ("file-send", "Validated"): "ValidateAuthorize",
    ("file-send", "ShapeSummary"): "CollectTransferResults",
    ("results-conversion", "Validated"): "ValidateAuthorize",
    ("results-conversion", "Described"): "DescribeResults",
    ("results-conversion", "Converted"): "Convert",
    ("table-share", "ShapeSummary"): "CollectTransferResults",
    ("table-share", "GuardRecipients/RecipientCleared"): "CheckTargetAbsent",
    ("table-share", "FinishRecipients/RecipientSucceeded"): "CreateTable",
}

#: The pairs whose verb DECIDES its own return, with the keys the state may drop.
#:
#: The discriminator is not cost — it is whether the answer is independent of the fixture. A verb
#: returning `{**event, …}` inherits its key set from its input, so driving it with a hand-built
#: mid-chain state compares that fixture with itself and would agree with any state at all. These
#: seven are rooted at the plane's real API envelope (or, for the two Map children, the plane's own
#: item fixture) and the verb builds the dict, so the key set is the verb's decision.
_CHECKED = {
    ("archive", "Validated"): frozenset(),
    ("file-send", "Validated"): frozenset(),
    ("results-conversion", "Validated"): frozenset(),
    ("results-conversion", "Described"): frozenset(),
    ("results-conversion", "Converted"): frozenset(),
    ("table-share", "GuardRecipients/RecipientCleared"): frozenset({"request"}),
    ("table-share", "FinishRecipients/RecipientSucceeded"): frozenset({"request"}),
}

#: The four pairs excluded from the DRIVEN check, each with the reason — recorded rather than
#: silently skipped, which is the difference between a known limit and a false claim.
#:
#: All four producers echo their input (`{**event, …}`, or the two collectors' filtered form), so
#: the comparison would only be meaningful driven from the plane's envelope through its whole real
#: chain. For archive and both collectors that is not merely expensive, it is impossible without
#: hand-shaping: a Distributed Map sits in the middle and the state after it is built from a Map
#: Run export that no drive can produce. `data-quality/RecordSuccess` is the same shape one verb
#: earlier.
#:
#: What still covers them: `file-send/ShapeSummary` is threaded and pinned by the success-path
#: sweep; the other three are success terminals, which is why they may drop the key at all, and the
#: test below asserts that rather than taking it on trust.
_ECHOING = {
    ("archive", "ArchiveComplete"):
        "write-receipt returns {**event, …}, and archive's chain crosses a Distributed Map whose "
        "result no drive can produce without hand-shaping the very state under test",
    ("data-quality", "RecordSuccess"):
        "drop-temp-tables returns the event plus `cleanup`, so its key set is its input's",
    ("file-send", "ShapeSummary"):
        "the collector filters and re-emits its event, and it reads a Map Run export",
    ("table-share", "ShapeSummary"):
        "the collector filters and re-emits its event, and it reads a Map Run export",
}

#: The producer sets that make each excluded state excluded. Pinned, because the REASON is what the
#: exclusion rests on and deriving it without asserting it leaves the guard unable to tell "excluded
#: because three producers converge" from "excluded because the walk lost an edge kind". Measured:
#: dropping the `Choices` loop from `_inbound` silently takes two of these from three producers to
#: two, and every other test stays green.
_EXCLUDED_PRODUCERS = {
    ("archive", "RestoreComplete"): ["CollectRestoreResults", "DeleteArchived", "UpdateReceipt"],
    ("table-builder", "RecordSuccess"): ["ApplyRefresh", "DiffSchema", "ExecuteDdl"],
    ("table-share", "FinishRecipients/RecipientCarried"): [],
}

#: The planes with nothing to check, and WHY — named so the sweep reports them rather than passing
#: silently over a third of the fleet, which is how a population claim rots.
_NOTHING_TO_CHECK = {
    "file-ops": "no success-path replacing Pass at all: the tail is Task-to-Task to Succeeded",
    "shared-spaces": "no success-path replacing Pass at all",
    "table-builder": "RecordSuccess has three possible producers, because ReleaseRefreshLock "
                     "merges under $.released and the walk passes through it",
}


def _inbound(name, states):
    """Every edge landing on `name`, as (source, kind, the catch's ResultPath or None).

    Args:
      name: The target state's name.
      states: Its container's states.

    Returns:
      One triple per edge.

    Raises:
      None.
    """
    edges = []
    for source, state in states.items():
        for target in (state.get("Next"), state.get("Default")):
            if target == name:
                edges.append((source, "flow", None))
        for choice in state.get("Choices") or []:
            if choice.get("Next") == name:
                edges.append((source, "flow", None))
        for catch in state.get("Catch") or []:
            if catch.get("Next") == name:
                edges.append((source, "catch", catch.get("ResultPath", "<absent>")))
    return edges


def _producers(target, states, seen=None):
    """Every distinct origin of the top-level object a state reads.

    THREE EDGE SEMANTICS decide this, and getting any of them wrong picks the wrong verb:

    * A `Next`/`Default`/`Choices` edge carries the SOURCE'S OUTPUT.
    * A `Catch` edge carries the failing Task's INPUT plus the error — never its result — so the
      walk continues past it rather than stopping on the Task that raised.
    * A state REPLACES the state only when it carries no `ResultPath` key at all. A non-null one
      merges and a `null` one discards, and both leave the incoming object intact, so the walk
      passes through them.

    That last distinction is why every test here reads ``"ResultPath" in state``: an ABSENT
    ResultPath and an explicit ``null`` both parse as None, and only membership tells them apart.

    Args:
      target: The state to walk back from.
      states: Its container's states.
      seen: Names already visited, for cycles.

    Returns:
      The set of producing state names, with a sentinel for any origin that is not a Task.

    Raises:
      None.
    """
    seen = (seen or set()) | {target}
    found = set()
    for source, kind, catch_path in _inbound(target, states):
        if source in seen:
            continue
        state = states[source]
        if kind == "catch":
            if catch_path == "<absent>":
                found.add(f"!error-replaced-at-{source}")
            else:
                found |= _producers(source, states, seen)
        elif "ResultPath" in state:
            found |= _producers(source, states, seen)
        elif state.get("Type") == "Task":
            found.add(source)
        elif state.get("Type") in ("Choice", "Wait"):
            found |= _producers(source, states, seen)
        else:
            found.add(f"!{state.get('Type')}-replaced-at-{source}")
    return found


def _pairs():
    """Every (plane, state) -> producing Task the rule selects, and every state it excludes.

    A pair is usable only where EVERY inbound path converges on exactly one replacing Task, so the
    `Pass` provably reads that verb's return and nothing else.

    Args:
      None.

    Returns:
      A (usable, excluded) pair of dicts, both keyed by (plane, qualified state name).

    Raises:
      None.
    """
    usable, excluded = {}, {}
    for path in machines._TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        asl = machines._load(path)
        seeds = {name for _p, name in machines._failure_seed_population()
                 if _p == plane}
        for label, start, states in machines._containers(asl):
            for name, state in states.items():
                if state.get("Type") != "Pass" or not isinstance(state.get("Parameters"), dict):
                    continue
                if "ResultPath" in state:
                    continue
                qualified = f"{label}/{name}".lstrip("/")
                if qualified in seeds:
                    continue
                producers = {"!start"} if name == start else _producers(name, states)
                only = next(iter(producers)) if len(producers) == 1 else None
                if only and states.get(only, {}).get("Type") == "Task":
                    usable[(plane, qualified)] = only
                else:
                    excluded[(plane, qualified)] = sorted(producers)
    return usable, excluded


def test_the_sweep_derives_the_pairs_it_checks_and_reports_the_planes_with_none():
    """The population is DERIVED, then pinned — and the empty planes are named, not skipped.

    Naming them is the point of the criterion: a sweep that "covered every plane" while silently
    finding nothing on three of them is how a population claim rots into a false one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the derived pairs, or the empty planes, move.
    """
    usable, excluded = _pairs()

    assert usable, "the sweep selected no pair at all, so every check below is vacuous"
    assert usable == _PAIRS, (
        f"unexpected: {sorted(set(usable) - set(_PAIRS))}; "
        f"missing: {sorted(set(_PAIRS) - set(usable))}"
    )

    checked = {plane for plane, _state in usable}
    assert checked | set(_NOTHING_TO_CHECK) == machines._EXPECTED_ARCS, (
        "a plane is neither checked nor recorded as having nothing to check"
    )
    assert not checked & set(_NOTHING_TO_CHECK), (
        f"{sorted(checked & set(_NOTHING_TO_CHECK))} are recorded as having nothing to check and "
        "the sweep found a pair on them"
    )
    for plane in _NOTHING_TO_CHECK:
        assert not any(p == plane for p, _s in usable), plane

    assert excluded == _EXCLUDED_PRODUCERS, (
        f"unexpected: {sorted(set(excluded) - set(_EXCLUDED_PRODUCERS))}; "
        f"missing: {sorted(set(_EXCLUDED_PRODUCERS) - set(excluded))}; "
        + "; ".join(
            f"{k} produced by {excluded[k]} not {_EXCLUDED_PRODUCERS[k]}"
            for k in set(excluded) & set(_EXCLUDED_PRODUCERS)
            if excluded[k] != _EXCLUDED_PRODUCERS[k]
        )
    )


def test_every_derived_pair_is_either_checked_or_recorded_as_echoing():
    """No pair may be silently absent from both, which is the only way this sweep can lie.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a pair belongs to neither set, or to both.
    """
    assert set(_CHECKED) | set(_ECHOING) == set(_PAIRS), (
        f"in neither: {sorted(set(_PAIRS) - set(_CHECKED) - set(_ECHOING))}; "
        f"invented: {sorted((set(_CHECKED) | set(_ECHOING)) - set(_PAIRS))}"
    )
    assert not set(_CHECKED) & set(_ECHOING)


#: How a plane's ASL state name maps to the lambda directory holding its verb. Derived from the
#: template's own `"FunctionName": "${…_function_arn}"` placeholder, with one irregular pair the
#: convention does not cover.
_IRREGULAR = {("shared-spaces", "acknowledge"): "shared-space-acknowledge-membership"}


def _verb_directory(plane, task):
    """The lambdas/ directory holding the Lambda a Task invokes.

    Args:
      plane: The plane's name.
      task: The ASL state name of the Task.

    Returns:
      The directory name under `lambdas/`.

    Raises:
      AssertionError: If the placeholder does not resolve to a directory, which means a rename has
        silently shrunk whatever population is built on this.
    """
    import re

    path = next(p for p in machines._TEMPLATES
                if os.path.basename(os.path.dirname(p)) == plane)
    raw = pathlib.Path(path).read_text(encoding="utf-8")
    pattern = '"' + re.escape(task) + r'": \{.*?"FunctionName": "\$\{(\w+)\}"'
    match = re.search(pattern, raw, re.DOTALL)
    assert match, f"{plane}:{task} names no FunctionName placeholder"
    verb = match.group(1).removesuffix("_function_arn").replace("_", "-")
    candidates = [
        _IRREGULAR.get((plane, match.group(1).removesuffix("_function_arn"))),
        f"{plane}-{verb}",
        f"{plane.rstrip('s')}-{verb}",
    ]
    directory = next((c for c in candidates if c and (_LAMBDAS / c).is_dir()), None)
    assert directory, f"{plane}:{task} resolves to none of {candidates}"
    return directory


#: The one producer that neither echoes nor mints, and may not: `archive-rollback` ALWAYS raises
#: (`archive_rollback.py:66` — "every path raises"), so it returns no state at all and cannot drop a
#: key from one. `RollbackReturnedSeed` exists to make a RETURNING rollback fail the way it meant
#: to, and its own template comment says it is unreachable today.
#:
#: Pinned as an EQUALITY, not a skip-list. A verb that stops offending must be removed from here, so
#: this cannot quietly become the place failures go to be forgiven.
#: The exact number of (plane, Task) producers the walk reaches. Pinned rather than floored: a
#: `>= 40` floor left eighteen percent of headroom, and dropping the `Default` edge or the `Wait`
#: pass-through from the walk stayed above it while silently losing producers — after which a real
#: key-drop on one of the lost verbs went unseen.
_PRODUCER_COUNT = 49

#: Directories whose source RETURNS or SPREADS a dict comprehension — the shape that RESHAPES a
#: mapping rather than removing a named key from it. Pinned as a tripwire, not as a verdict: three
#: separate bypasses of the check below all took this form (a helper returning a filtered
#: comprehension, a return rewritten to `{k: out[k] for k in KEEP}`, and the same thing one level
#: deeper in the shared layer), and none of them names `traceparent` anywhere, so nothing that looks
#: for the key can see them.
#:
#: A new entry here is not a defect — most of these reshape something that is not the run's state.
#: It is a demand that somebody look, which is the honest thing a shape check can offer.
_RESHAPES_A_MAPPING = frozenset({
    "api",
    "control-plane-common",
    "data-quality-start-profile-query",
    "file-ops-collect-transfer-results",
    "file-ops-finalise-outcomes",
    "file-send-collect-transfer-results",
    "results-conversion-common",
    "table-builder-diff-schema",
    "table-share-collect-transfer-results",
})

_NEVER_RETURNS = frozenset({"archive:Rollback"})


def _returns_carry(directory):
    """Whether a verb ECHOES its event, MINTS the traceparent, or neither — read by AST.

    By AST rather than by substring, and the difference is not pedantry: a substring test over the
    verb's source is satisfied by the words appearing in a DOCSTRING. Since `lambdas/` forbids
    inline comments, a docstring is the whole risk surface, and a reviewer used exactly that to
    silence a genuine disagreement — mention `{**event, …}` in the module docstring, move the pair
    into `_ECHOING`, and the file went on reporting full coverage over eleven pairs.

    Every shape is anchored on ONE question — does this expression evaluate to the handler's whole
    event — rather than on a pattern per shape. Three drafts were written pattern-by-pattern and
    each one called a verb that BUILDS its return an echoing verb: first any `return <name>`, which
    caught `archive-validate-authorize` returning a dict it names `validated`; then any `**<name>`
    spread, which caught `file-send-validate-authorize` merging a local `{**entry, …}`. Both errors
    ran in the direction that matters — they would have let this guard pass for a verb that drops
    whatever it was not told to keep.

    The shapes that really occur: `{**event, …}`, `out = dict(event)`, `return event`, and the two
    collectors' `{**{k: v for k, v in event.items() if …}, …}`.

    Carrying the event is NOT sufficient on its own, and that is the fourth draft's lesson rather
    than a refinement: `carried = dict(event)` followed by `carried.pop("traceparent", None)`
    satisfies every "does the event reach the return" rule above and drops the key regardless. So a
    verb that removes THIS key anywhere is not echoing, whatever else it does. That question is
    decidable where the general one is not.

    Args:
      directory: The verb's directory name under `lambdas/`.

    Returns:
      An (echoes, mints) pair of booleans.

    Raises:
      None.
    """
    def is_the_event(node):
        """Whether an expression evaluates to the handler's whole event."""
        if isinstance(node, ast.Name):
            return node.id == "event"
        if isinstance(node, ast.Call):
            return (getattr(node.func, "id", None) == "dict"
                    and any(is_the_event(arg) for arg in node.args))
        if isinstance(node, ast.DictComp):
            return any(
                isinstance(gen.iter, ast.Call)
                and getattr(gen.iter.func, "attr", None) == "items"
                and is_the_event(getattr(gen.iter.func, "value", None))
                for gen in node.generators
            )
        return False

    def discards_the_traceparent(node):
        """Whether an expression REMOVES the traceparent from a mapping.

        Key-specific on purpose. Deciding in general whether a verb's return still carries its
        input's keys is dataflow analysis on Python, and three source-shape rules were written and
        defeated in turn before this one: `carried = dict(event)` followed by
        `carried.pop("traceparent", None)` satisfies every "does the event flow to the return"
        test there is, and drops the key anyway. Asking instead whether anything removes THIS key
        is decidable, catches that exact shape, and cannot false-positive on the two dozen
        unrelated pops and filtering comprehensions elsewhere in the fleet.
        """
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "pop":
            return any(isinstance(a, ast.Constant) and a.value == "traceparent" for a in node.args)
        if isinstance(node, ast.Delete):
            return any(
                isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                and t.slice.value == "traceparent"
                for t in node.targets
            )
        if isinstance(node, ast.DictComp):
            return any(
                isinstance(c, ast.Constant) and c.value == "traceparent"
                for gen in node.generators for test in gen.ifs for c in ast.walk(test)
            )
        return False

    echoes = mints = False
    for module in sorted((_LAMBDAS / directory).glob("**/*.py")):
        if module.name.startswith("test_") or "__pycache__" in module.parts:
            continue
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if key is None and is_the_event(value):
                        echoes = True
                    if (isinstance(key, ast.Constant) and key.value == "traceparent"
                            and isinstance(value, ast.Call)
                            and getattr(value.func, "attr", None) == "run_traceparent"):
                        mints = True
            elif (isinstance(node, (ast.Assign, ast.Return))
                    and is_the_event(node.value)):
                echoes = True
            if discards_the_traceparent(node):
                return False, mints
    return echoes, mints


def test_every_producer_of_a_failure_path_traceparent_read_carries_it_through():
    """The invariant the whole failure path rests on, DERIVED rather than stated.

    A `Catch` hands its target the failing Task's INPUT, so a failure seed stands on a success-path
    state — and what actually keeps the traceparent alive on that state is the fleet's echo
    convention: every replacing Task returns `{**event, …}` and so cannot drop a key it was never
    told about. Nothing checked that.

    It is not a hypothetical. Deleting the traceparent from `archive-build-transfer-manifest`'s echo
    left the ENTIRE suite green while `archive/NothingToArchiveSeed` — which reads `$.traceparent`
    off that verb's return — would raise an uncatchable `States.Runtime`, killing the execution
    before `NotifyFailure`, so a user whose archive found nothing to archive is told nothing at all.

    The population is bounded and derived, not listed: walk back from every state that reads
    `$.traceparent` on a failure path to the Task whose return it reads, resolve that Task to its
    Lambda, and require the verb to echo its event or mint the key itself. Forty-nine verbs, and one
    pinned exemption whose premise is checked by its own test.

    **This is a DETECTOR, not a proof, and the difference is worth stating where it lives.** Whether
    a verb's return still carries its input's keys is not decidable from source, and five drafts
    were each defeated by a reviewer: a `return <name>`, a `**<name>` spread, an `event`-anchored
    version, `dict(event)` followed by `.pop`, and a helper that trimmed the mapping after a genuine
    echo. What it now catches is the shapes that occur — carrying the event, minting the key,
    removing it by name — with a fleet-wide tripwire beside it for the one shape that names nothing
    (`test_the_shape_that_reshapes_a_mapping_is_pinned_fleet_wide`). A determined enough indirection
    still gets past it.

    What makes that acceptable rather than hollow: production correctness does not rest on this
    test. A separate review traced every one of the reads with an abstract interpreter over all
    eight graphs and found zero states reachable with the key absent, and no producer can carry
    `requestId` and drop `traceparent` because every one either mints or echoes. This guard's job is
    to make the NEXT change to one of those verbs loud, and it is honest about being that rather
    than a fence.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a producer can drop the run's trace on its way to a failure.
    """
    producers, offenders = set(), set()
    for path in machines._TEMPLATES:
        plane = os.path.basename(os.path.dirname(path))
        asl = machines._load(path)
        for label, _start, states in machines._containers(asl):
            if label:
                continue
            for name, state in states.items():
                block = state.get("Parameters") or {}
                if block.get("traceparent.$") != "$.traceparent":
                    continue
                for task in sorted(_producers(name, states)):
                    if task.startswith("!") or states[task].get("Type") != "Task":
                        continue
                    producers.add((plane, task))

    assert len(producers) == _PRODUCER_COUNT, (
        f"the walk found {len(producers)} producers, not {_PRODUCER_COUNT}. A floor was tried here "
        "first and it left eighteen percent of headroom: dropping the `Default` edge or the `Wait` "
        "pass-through silently lost producers and stayed above it, and a real key-drop on one of "
        "the lost verbs then went unseen. An exact count has no headroom to hide in"
    )

    for plane, task in sorted(producers):
        echoes, mints = _returns_carry(_verb_directory(plane, task))
        if not (echoes or mints):
            offenders.add(f"{plane}:{task}")

    assert set(offenders) == _NEVER_RETURNS, (
        f"unexpected: {sorted(set(offenders) - _NEVER_RETURNS)} neither echo their event nor mint "
        "the traceparent, and a state downstream reads `$.traceparent` off their return — an "
        "uncatchable States.Runtime on the failure path, which kills the execution before the user "
        f"is notified. No longer offending: {sorted(_NEVER_RETURNS - set(offenders))}"
    )


def test_the_producer_walk_follows_a_default_edge_and_passes_through_a_wait():
    """Two rules of the backward walk that the fleet cannot separate from their absence.

    Both were found by planting: dropping the `Default` edge, or the `Wait` pass-through, silently
    lost producers while every fleet-wide assertion stayed green — and with the `Wait` rule gone, a
    blunt `out.pop("traceparent", None)` planted in the verb behind it went unseen. The exact
    producer count above closes the headroom they hid in; these give each rule a case where it alone
    decides.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either rule stops being followed.
    """
    via_default = {
        "Make": {"Type": "Task", "Next": "Fork"},
        "Fork": {"Type": "Choice", "Choices": [], "Default": "Reader"},
        "Reader": {"Type": "Pass", "Parameters": {"k.$": "$.k"}, "End": True},
    }
    assert _producers("Reader", via_default) == {"Make"}, (
        "the walk does not follow a `Default` edge, so a state reached only through one has no "
        "producer and drops out of the population unnoticed"
    )

    via_wait = {
        "Make": {"Type": "Task", "Next": "Hold"},
        "Hold": {"Type": "Wait", "Seconds": 1, "Next": "Reader"},
        "Reader": {"Type": "Pass", "Parameters": {"k.$": "$.k"}, "End": True},
    }
    assert _producers("Reader", via_wait) == {"Make"}, (
        "a `Wait` touches nothing on the state, so the walk must pass THROUGH it; stopping there "
        "loses the verb whose return the reader actually reads"
    )


def test_the_shape_that_reshapes_a_mapping_is_pinned_fleet_wide():
    """The tripwire for the one thing a key-named check cannot see: a RESHAPE.

    Every guard in this file that asks about the traceparent asks it by name — is the key spread
    in, is it popped, is it excluded by a filter that names it. A verb that instead builds its
    return from a KEEP-list never mentions the key at all, and all three bypasses of the check below
    took exactly that form. The population is small enough to pin, so a new one is a red run.

    It is a tripwire and not a verdict, and the difference is worth being exact about: most of these
    reshape something that is not the run's state, and a fence that claimed otherwise would be a
    detector wearing a fence's clothes.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a directory starts or stops reshaping a mapping.
    """
    found = set()
    for module in sorted(_LAMBDAS.glob("**/*.py")):
        if module.name.startswith("test_") or "__pycache__" in module.parts:
            continue
        try:
            tree = ast.parse(module.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            reshapes = isinstance(node, ast.Return) and isinstance(node.value, ast.DictComp)
            if isinstance(node, ast.Dict):
                reshapes = reshapes or any(
                    key is None and isinstance(value, ast.DictComp)
                    for key, value in zip(node.keys, node.values, strict=True)
                )
            if reshapes:
                found.add(module.relative_to(_LAMBDAS).parts[0])

    assert found == _RESHAPES_A_MAPPING, (
        f"new: {sorted(found - _RESHAPES_A_MAPPING)} — each one builds a mapping from a chosen set "
        "of keys, which drops everything it was not told to keep WITHOUT naming what it dropped. "
        f"If any sits on a failure-reachable path, the run's trace stops there silently. "
        f"No longer reshaping: {sorted(_RESHAPES_A_MAPPING - found)}"
    )


def test_the_rollback_exemption_still_cannot_return_a_mapping():
    """`_NEVER_RETURNS` rests on a claim about archive-rollback, so the claim is checked.

    The exemption says the verb always raises and so returns no state to drop a key from. That is a
    property of the source, not a licence, and `RollbackReturnedSeed` — the state built precisely
    for a rollback that DOES return — reads `$.traceparent` as its first parameter. On any path
    where the premise is false, the seed built for it raises the very error the guard prevents
    elsewhere.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the verb gains a path that returns a mapping.
    """
    returns = []
    for module in sorted((_LAMBDAS / "archive-rollback").glob("**/*.py")):
        if module.name.startswith("test_") or "__pycache__" in module.parts:
            continue
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Return) and isinstance(node.value, (ast.Dict, ast.DictComp)):
                returns.append(f"{module.name}:{node.lineno}")

    assert not returns, (
        f"archive-rollback returns a mapping at {returns}, so `_NEVER_RETURNS` no longer holds: "
        "the verb can now hand a state to RollbackReturnedSeed, which reads `$.traceparent` off it"
    )


def test_a_pair_recorded_as_echoing_really_does_echo():
    """The exclusion list is the escape hatch, so it is the thing most worth checking.

    Without this, a pair whose check started failing could be silenced by moving it into
    `_ECHOING` with a plausible sentence, and the sweep would keep reporting full coverage. The
    reason those four are excluded is a property of their SOURCE — the return spreads the event —
    so it is read off the source rather than taken on trust.

    Asserted in both directions, because a rule that only checked the exclusions would be
    satisfied by a file that excluded everything.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an excluded verb builds its own return, or a checked one echoes.
    """
    for (plane, state), _reason in sorted(_ECHOING.items()):
        echoes, _mints = _returns_carry(_verb_directory(plane, _PAIRS[(plane, state)]))
        assert echoes, (
            f"{plane}:{state} is recorded as echoing its event, and {_PAIRS[(plane, state)]} does "
            "not — so it builds its own return and belongs in the driven check"
        )

    for plane, state in sorted(_CHECKED):
        echoes, _mints = _returns_carry(_verb_directory(plane, _PAIRS[(plane, state)]))
        assert not echoes, (
            f"{plane}:{state}'s verb now echoes its event, so the driven comparison is against "
            "this file's own fixture and proves nothing — move it to _ECHOING with the reason"
        )


def test_no_checked_pair_is_allowed_to_drop_the_traceparent():
    """A drop set is a licence to lose a key silently, and this is the key the arc is about.

    None of the seven driven pairs may hold that licence: every one of them is a state whose output
    a later state reads. The permission exists in the shape of the check — a drop set is per pair —
    so it is refused here rather than merely unused, which is the difference between a rule and an
    accident.

    The four ECHOING pairs are not covered by this file at all, so their traceparent is checked
    where it can be: `_THREADING_STATES` in the success-path sweep pins that each of them names the
    key, and this asserts that pairing rather than assuming it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a checked pair may drop the trace, or an echoing one is unpinned elsewhere.
    """
    dropping = {key for key, drops in _CHECKED.items() if "traceparent" in drops}
    assert not dropping, (
        f"{sorted(dropping)} are held to their verb's return AND allowed to drop the run's trace, "
        "so the trace stops there with this file's blessing"
    )

    threaded = machines._THREADING_STATES
    terminal = {
        key for key in _ECHOING
        if key not in threaded
    }
    for plane, state in sorted(terminal):
        path = next(p for p in machines._TEMPLATES
                    if os.path.basename(os.path.dirname(p)) == plane)
        states = machines._load(path)["States"]
        following = states[state].get("Next") if state in states else None
        assert following and states.get(following, {}).get("Type") == "Succeed", (
            f"{plane}:{state} is neither driven here nor threaded by the success-path sweep, and "
            "it is not a success terminal either — so nothing checks that it carries the run's "
            "trace, and nothing has decided it may drop it"
        )


_IDENTITY = {"actor": "alice", "delegated_by": None, "assurance": "interactive"}
_UUID = "9f2c1b8e-4c1a-4b2f-8d3e-1a2b3c4d5e6f"


def _drive_archive_validated(monkeypatch):
    """archive validate-authorize, BOTH modes, because `Validated` is entered from both.

    `ValidateAuthorize` is a single producing Task and not a single return shape: the restore arm
    delegates to `arcommon.restore.validate`, which builds its own dict. Driving one mode makes the
    equality below a claim about one of two runtime paths — the same objection this file uses to
    EXCLUDE `archive/RestoreComplete`, and it applies just as much to a verb's internal branches.
    Measured when this was written: a key added to the restore arm alone left the whole suite green.

    The two returns are required to agree, and only then is one compared against the state — so the
    state is held to both arms rather than to whichever this fixture happened to drive.
    """
    import archive_validate_authorize as verb

    monkeypatch.setattr(verb.authz.reg, "load", lambda name: None)
    monkeypatch.setattr(verb.notify, "emit_notification", lambda *a, **kw: None, raising=False)

    def drive(body):
        return verb.handler([{"messageId": "m-1", "body": json.dumps(body)}], None)

    archived = drive({
        "requestId": _UUID, "mode": "archive", "actor": JWT_SHAPED,
        "source": {"space": {"kind": "personal", "name": "alice"},
                   "items": [{"kind": "file", "key": "alice/q1.csv"}]},
        "identity": _IDENTITY,
    })
    restored = drive({
        "requestId": _UUID, "mode": "restore", "actor": JWT_SHAPED,
        "space": {"kind": "personal", "name": "alice"},
        "archiveId": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
        "identity": _IDENTITY,
    })

    assert set(archived) == set(restored), (
        "archive's two modes return different top-level keys, and both flow through one `Validated` "
        f"Pass: archive-only {sorted(set(archived) - set(restored))}, restore-only "
        f"{sorted(set(restored) - set(archived))}. Whichever the Pass does not carry is an "
        "uncatchable States.Runtime on that mode"
    )
    return archived


def _drive_file_send_validated(monkeypatch):
    """file-send validate-authorize."""
    import file_send_validate_authorize as verb

    monkeypatch.setattr(verb.reg, "load", lambda name: None)
    monkeypatch.setattr(verb.cognito, "user_exists", lambda name: True)
    return verb.handler([{"body": json.dumps({
        "requestId": "req-1",
        "source": {"space": {"kind": "personal", "name": "alice"},
                   "items": [{"kind": "file", "key": "alice/q1.csv"}]},
        "recipients": [{"kind": "user", "name": "bob"}],
        "identity": _IDENTITY,
    })}], None)


def _drive_results_conversion(which, monkeypatch):
    """The three results-conversion verbs, driven through the plane's OWN fixtures.

    Imported rather than copied. These need an Athena fake that answers `get_query_execution` and
    `get_query_results`, an S3 fake with `head_object`/`download_fileobj`/`put_object`, and a
    scratch root — forty-odd lines that already exist beside the verbs. A second copy here would be
    a second thing to keep true, and the copy that drifts is the one nobody is looking at.

    Args:
      which: "validate", "describe" or "convert".
      monkeypatch: pytest's patcher.

    Returns:
      The verb's success return.

    Raises:
      None.
    """
    import pathlib as _pathlib
    import tempfile

    import rc_convert as convert
    import rc_describe_results as describe
    import rc_validate_authorize as validate
    import test_state_machine_results_conversion as plane

    monkeypatch.setattr(clients, "_athena", plane._Athena(), raising=False)
    monkeypatch.setattr(clients, "_s3", plane._S3(), raising=False)
    for module in (validate, describe, convert):
        monkeypatch.setattr(module.notify, "emit_notification", lambda *a, **kw: None,
                            raising=False)
    monkeypatch.setattr(convert, "SCRATCH_ROOT", _pathlib.Path(tempfile.mkdtemp()))

    validated = validate.handler(plane._event(), None)
    if which == "validate":
        return validated
    described = describe.handler(validated, None)
    if which == "describe":
        return described
    return convert.handler(described, None)


def _drive_table_share(which, monkeypatch):
    """table-share's three verbs, through their own suites' fixtures.

    Args:
      which: "check" or "create".
      monkeypatch: pytest's patcher.

    Returns:
      The verb's success return.

    Raises:
      None.
    """
    if which == "check":
        import table_share_check_target_absent as verb
        import test_table_share_check_target_absent as plane

        monkeypatch.setattr(verb.glue_mod, "table_exists", lambda db, t: False)
        monkeypatch.setattr(clients, "_s3", plane._FakeS3(0), raising=False)
        return verb.handler(plane._event(), None)
    import table_share_create_table as verb
    import test_table_share_create_table as plane

    monkeypatch.setattr(verb.athena_mod, "run_ddl", lambda **kw: "qid-1", raising=False)
    return verb.handler(plane._event(), None)


#: How each pinned pair's producing verb is driven to a SUCCESS return. Keyed identically to
#: `_PAIRS`, and the two are held equal below, so a pair added without a drive is a red run rather
#: than a silently unchecked plane.
_DRIVES = {
    ("archive", "Validated"): _drive_archive_validated,
    ("file-send", "Validated"): _drive_file_send_validated,
    ("results-conversion", "Validated"): lambda mp: _drive_results_conversion("validate", mp),
    ("results-conversion", "Described"): lambda mp: _drive_results_conversion("describe", mp),
    ("results-conversion", "Converted"): lambda mp: _drive_results_conversion("convert", mp),
    ("table-share", "GuardRecipients/RecipientCleared"): lambda mp: _drive_table_share("check", mp),
    ("table-share", "FinishRecipients/RecipientSucceeded"): lambda mp: _drive_table_share("create", mp),
}


def _full_paths(block):
    """Every `$.a.b` reference path a Parameters block reads, at any nesting depth.

    `machines._read_keys` yields FIRST SEGMENTS, which is what the set equality below compares.
    This yields the whole path, because a state can read `$.recipient.kind` off a verb that
    returns `recipient` without any `kind` in it — and the first segment alone cannot see that.

    Args:
      block: A `Parameters` block, or any block nested inside one.

    Returns:
      The set of reference paths, without their leading `$.`.

    Raises:
      None.
    """
    paths = set()
    if isinstance(block, dict):
        for name, value in block.items():
            if name.endswith(".$") and isinstance(value, str):
                if value.startswith("$.") and "$$" not in value:
                    paths.add(value.removeprefix("$."))
            else:
                paths |= _full_paths(value)
    elif isinstance(block, list):
        for value in block:
            paths |= _full_paths(value)
    return paths


def _unresolvable(block, returned):
    """Every reference path in `block` that `returned` cannot resolve, whole.

    Args:
      block: A state's `Parameters`.
      returned: The verb's driven return.

    Returns:
      The set of unresolvable paths, without their leading `$.`.

    Raises:
      None.
    """
    bad = set()
    for reference in _full_paths(block):
        value = returned
        for segment in reference.split("."):
            if not isinstance(value, dict) or segment not in value:
                bad.add(reference)
                break
            value = value[segment]
    return bad


def test_the_nested_path_check_sees_a_read_whose_first_segment_resolves():
    """The positive control for a check the fleet cannot currently exercise.

    Every nested read on the fleet resolves today, so deleting the check outright leaves the whole
    file green — it is an absence, and an absence proves nothing unless the thing looking for it can
    find one. This plants the exact shape it exists for: a first segment the verb DOES return, and a
    remainder it does not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the check stops distinguishing a resolvable path from a broken one.
    """
    returned = {"recipient": {"kind": "user"}, "request": {}}

    assert _unresolvable({"kind.$": "$.recipient.kind"}, returned) == set()
    assert _unresolvable({"name.$": "$.recipient.name"}, returned) == {"recipient.name"}, (
        "the check compares first segments only, so a read into a value that lacks the rest passes"
    )
    assert _unresolvable({"deep.$": "$.recipient.kind.more"}, returned) == {"recipient.kind.more"}
    assert _unresolvable({"whole.$": "$"}, returned) == set(), (
        "a whole-state read names no path and must not be reported as unresolvable"
    )


def test_every_pinned_pair_has_a_drive():
    """A pair with no drive would be a plane the sweep claims to cover and does not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two mappings disagree.
    """
    assert set(_DRIVES) == set(_CHECKED), (
        f"undriven: {sorted(set(_CHECKED) - set(_DRIVES))}; "
        f"driven but not pinned: {sorted(set(_DRIVES) - set(_CHECKED))}"
    )


@pytest.mark.parametrize("plane,state", sorted(_CHECKED), ids=lambda v: v)
def test_a_field_naming_state_reads_exactly_what_its_verb_returns(plane, state, monkeypatch):
    """Both directions, against the verb's REAL return rather than its source.

    Reading the source would answer a different question: what the verb appears to return. Driving
    it answers what it does return, which is the only thing the machine will meet.

    Two assertions, because one of them alone is satisfiable while the state is broken. The set
    equality catches a key the verb stopped returning AND a key the state silently drops; the path
    check catches a nested read whose first segment resolves and whose remainder does not, which
    the set equality cannot see.

    Args:
      plane: The plane's name.
      state: The qualified state name.
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: On any disagreement between the state and its verb.
    """
    verb, drops = _PAIRS[(plane, state)], _CHECKED[(plane, state)]
    returned = _DRIVES[(plane, state)](monkeypatch)

    assert isinstance(returned, dict) and returned, (
        f"{plane}:{verb} returned {returned!r}; the drive did not reach a success return, so the "
        "comparison below would pass against an empty set"
    )

    path = next(p for p in machines._TEMPLATES
                if os.path.basename(os.path.dirname(p)) == plane)
    block = dict(machines._states(machines._load(path)))[state].get("Parameters")
    reads = machines._read_keys(block)

    assert reads == set(returned) - drops, (
        f"{plane}:{state} reads {sorted(reads)} and {verb} returns {sorted(returned)} "
        f"(dropping {sorted(drops)} deliberately). "
        f"Reads the verb does not return: {sorted(reads - set(returned))} — an uncatchable "
        f"States.Runtime. Returns the state drops undeclared: "
        f"{sorted(set(returned) - drops - reads)} — silent, and how the traceparent went missing"
    )

    unresolvable = _unresolvable(block, returned)
    assert not unresolvable, (
        f"{plane}:{state} reads {sorted(unresolvable)} off {verb}'s return, which does not resolve "
        "them. A matching FIRST SEGMENT is not enough: a nested read into a value that lacks the "
        "rest is the same uncatchable States.Runtime, and the set equality above cannot see it"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
