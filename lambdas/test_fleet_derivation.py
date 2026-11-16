"""The fleet's Terraform-derived membership, and the two lists that must not drift from it.

**The deploy table is gone, and the bridge that proved this replacement against it went with it.**
That test asserted the two were the same 86 names in both directions, and it landed and ran green
before a single deletion — which is what made the deletion safe rather than hopeful. It is not
kept: a test comparing the derivation against a file that no longer exists is not a weaker guard,
it is a broken one.

What remains guards the replacement's own soft spot. The root output aggregates fourteen module
outputs by hand in a `concat`, which is a new hand-maintained list of exactly the kind this spec
exists to remove — a plane added to `main.tf` and forgotten there would contribute no functions,
CI would deploy a fleet one plane short, and every set comparison downstream derives from the
same output and would agree with the shortfall.

Attributes:
  ROOT: The repository root.
  ROOT_TF: The root module's Terraform, where the aggregation lives.
  MODULES: The bounded-context module directory.
  AGGREGATE: The local the root output reads.
"""

import fnmatch
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROOT_TF = ROOT / "infra" / "outputs.tf"
MODULES = ROOT / "infra" / "modules"
AGGREGATE = "lambda_deployed_names"

sys.path.insert(0, str(ROOT / "lambdas"))
import fleet
from tf_blocks import (
    argument,
    module_calls,
    output_blocks,
    span,
    strip_comments,
    strip_noise,
)


def _modules_declaring_functions() -> set[str]:
    """Every module directory holding at least one `docker-lambda` call.

    Derived rather than listed, so a new plane is covered the day it lands.

    Args:
      None.

    Returns:
      The module directory names.

    Raises:
      None.
    """
    found = set()
    for module in sorted(MODULES.iterdir()):
        if not module.is_dir():
            continue
        for path in sorted(module.glob("*.tf")):
            for inner in module_calls(path.read_text(encoding="utf-8")).values():
                try:
                    source = argument(inner, "source")
                except ValueError:
                    continue
                if fleet._is_fleet_module(source):
                    found.add(module.name)
    return found


def _root_calls_deploying_functions() -> set[str]:
    """Every root module call whose module holds at least one `docker-lambda` call.

    The aggregate names root CALLS, and one building block is called once per plane, so the
    comparison is between call names, never module directories.

    Args:
      None.

    Returns:
      The root call names, as written.

    Raises:
      None.
    """
    declaring = _modules_declaring_functions()
    found = set()
    for path in sorted(ROOT_TF.parent.glob("*.tf")):
        for call, inner in module_calls(path.read_text(encoding="utf-8")).items():
            try:
                source = argument(inner, "source").strip('"').rstrip("/")
            except ValueError:
                continue
            if source.startswith("./modules/") and source.rsplit("/", 1)[-1] in declaring:
                found.add(call)
    return found


def _aggregated_modules() -> set[str]:
    """The root module call names the fleet aggregate concatenates.

    Read to the MATCHING close paren rather than to the first one. `concat(` nests — every element
    is itself a `[for … : …]` or a bracketed literal — so stopping at the first `)` slices one
    element and reports thirteen modules missing.

    **Located over ``strip_noise``, and that is the half this file got wrong first.** The other
    side of the comparison is comment-aware for free, because it goes through the shared module
    reader; this side read the file raw, so a plane commented OUT of the concat still matched the
    regex and the test passed. Measured: both `# module.table_share.function_names,` and a
    `# TODO:` line naming it passed a full run. Blanking first also stops an unbalanced paren
    inside a comment from ending the scan early, which was a false positive in the same place.

    Args:
      None.

    Returns:
      The call names, as written in `infra/outputs.tf`.

    Raises:
      AssertionError: When the aggregate cannot be found, so a renamed local fails here rather
        than resolving to an empty set that every comparison below would pass against.
    """
    text = strip_noise(ROOT_TF.read_text(encoding="utf-8"))
    match = re.search(rf"^\s*{AGGREGATE}\s*=\s*concat\(", text, re.MULTILINE)
    assert match, f"no `{AGGREGATE} = concat(` in {ROOT_TF.name} — the aggregate was renamed"

    depth, index = 0, match.end() - 1
    while index < len(text):
        depth += {"(": 1, ")": -1}.get(text[index], 0)
        index += 1
        if depth == 0:
            break
    assert depth == 0, f"`{AGGREGATE}`'s concat( is never closed"

    names = set(re.findall(r"module\.([A-Za-z0-9_]+)\.function_names", text[match.end() : index]))
    assert names, f"`{AGGREGATE}` concatenates nothing"
    return names


def _fleet_calls(module: pathlib.Path) -> dict[str, bool]:
    """Every ``docker-lambda`` call in one module, mapped to whether it fans out.

    Args:
      module: The module directory.

    Returns:
      Each call name mapped to True when it carries a ``for_each``.

    Raises:
      None.
    """
    found = {}
    for path in sorted(module.glob("*.tf")):
        for call, inner in module_calls(path.read_text(encoding="utf-8")).items():
            try:
                source = argument(inner, "source")
            except ValueError:
                continue
            if not fleet._is_fleet_module(source):
                continue
            try:
                argument(inner, "for_each")
            except ValueError:
                found[call] = False
            else:
                found[call] = True
    return found


def test_the_root_output_aggregates_every_module_that_deploys_a_function() -> None:
    """The root's hand-written `concat` covers every plane, and names no module that has none.

    Both directions, for the reason the aggregate is a risk at all. A plane missing from the
    concat contributes nothing and the fleet is silently short — and because CI and every
    comparison read the same output, nothing anywhere disagrees. A module named in the concat that
    declares no function is the milder half and still wants deleting, because it reads as coverage.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the concat and the modules disagree in either direction.
    """
    aggregated = _aggregated_modules()
    declaring = _root_calls_deploying_functions()

    assert aggregated == declaring, (
        f"the root fleet aggregate concatenates {sorted(aggregated)} but the root calls deploying "
        f"functions are {sorted(declaring)}. Missing from the concat: "
        f"{sorted(declaring - aggregated)} — those functions reach no consumer and every count "
        f"derived from the output agrees with the shortfall. Named but deploying nothing: "
        f"{sorted(aggregated - declaring)}."
    )


@pytest.mark.parametrize("module", sorted(_modules_declaring_functions()))
def test_every_module_exports_the_names_of_every_function_it_deploys(module: str) -> None:
    """A module's `function_names` output reaches every `docker-lambda` call it makes.

    **Asserting the output EXISTS is not enough, and the gap was measured rather than argued.**
    An earlier version of this test looked only for the string `output "function_names"`. With it,
    `archive`'s output was cut from a walk of all eighteen verbs down to
    `[module.functions["notify"].function_name]` — one of eighteen — and the whole suite passed,
    exit 0. Fourteen hand-written output values had replaced one hand-written table, and nothing
    read any of them.

    So the value is parsed. Every `docker-lambda` call in the module must appear in it, and a call
    with `for_each` must be reached by `for … in module.<call>` rather than by an index — indexing
    picks one instance out of a fleet, which is exactly the shortfall above and reads as coverage.

    Two ways past those checks were found by planting them, and both are closed here. The value is
    read through `strip_noise`, so a walk mentioned only in a COMMENT above an indexed export no
    longer satisfies the substring — the same comment-blindness this file had on its other half.
    And a filtered comprehension, `for k, f in module.functions : … if k == "notify"`, contains
    every substring the checks look for while exporting one verb of eighteen, so an `if` in this
    output is refused outright: no module here needs one, and the shape is indistinguishable from
    a full walk at a glance.

    Args:
      module: The module directory.

    Returns:
      None.

    Raises:
      AssertionError: When the output is missing, or does not reach every function the module
        deploys.
    """
    outputs = MODULES / module / "outputs.tf"
    assert outputs.is_file(), f"{module} deploys functions but has no outputs.tf"

    text = outputs.read_text(encoding="utf-8")
    blocks = output_blocks(text)
    assert "function_names" in blocks, (
        f"{module} deploys functions and exports no `function_names`, so the root aggregate "
        "cannot reach them."
    )
    written = argument(blocks["function_names"], "value")
    value = strip_noise(written)

    for call, fans_out in _fleet_calls(MODULES / module).items():
        assert f"module.{call}" in value, (
            f"{module}'s `function_names` never mentions `module.{call}`, so those functions "
            f"reach no consumer. The output is: {written}"
        )
        if fans_out:
            assert f"in module.{call}" in value, (
                f"{module}'s `module.{call}` is a for_each fleet, but `function_names` does not "
                f"walk it with `for … in module.{call}` — an index picks ONE instance out of "
                f"many and reads exactly like coverage. The output is: {written}"
            )
    assert not re.search(r"\bif\b", value), (
        f"{module}'s `function_names` filters with `if`. Every function this module deploys must "
        f"reach the fleet, and a filtered walk satisfies every check above while exporting a "
        f"subset — which is the shortfall this test exists to catch, wearing the shape of a walk. "
        f"The output is: {written}"
    )


def test_no_hand_maintained_function_list_survives_in_github() -> None:
    """Nothing under `.github/` enumerates the fleet any more.

    The point of moving the fleet's membership to Terraform is that there is ONE declaration. A
    second list is not merely redundant — it is a list that can only ever drift, and the drift is
    invisible until a function is deployed against the wrong one. So the absence is asserted
    rather than assumed.

    Scoped to files that enumerate the FLEET. `.github/lambda-probes.json` is deliberately not
    caught: it is a documented SAMPLE — one verb per plane plus each standalone — derived from and
    held to the deploy role's invoke grants by `test_cold_start_probe.py`, which fails in both
    directions if it drifts.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a file under `.github/` lists most of the fleet.
    """
    names = set(fleet.function_names(ROOT))
    offenders = []
    for path in sorted((ROOT / ".github").rglob("*")):
        if not path.is_file() or path.name == "lambda-probes.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        mentioned = sum(1 for name in names if f'"{name}"' in text)
        if mentioned > len(names) // 2:
            offenders.append(f"{path.relative_to(ROOT)} ({mentioned} of {len(names)})")

    assert not offenders, (
        f"these files under .github/ enumerate the fleet: {offenders}. Terraform is the single "
        "declaration of which Lambdas exist; a second list drifts, and the drift is invisible "
        "until something deploys against the wrong one."
    )


#: What `CreateFunction` accepts in THIS account, which is not what Lambda documents. Lambda's
#: own maximum is 10,240 MB; an account keeps a 3,008 MB ceiling until someone asks AWS to lift
#: the quota, and this one has not. Measured the expensive way, on 2026-09-06: a `convert` verb
#: declared at 10,240 passed `tofu validate`, passed the module's own range check, planned green,
#: and failed the APPLY on `main` with `'MemorySize' value failed to satisfy constraint: Member
#: must have value less than or equal to 3008`.
ACCOUNT_MAX_MEMORY_MB = 3008

#: Ephemeral storage. 2,048 is what this account has been observed to ACCEPT — the converter runs
#: at it — which is not the same as knowing the ceiling is 2,048. Somebody writing 4,096 later is
#: back where this morning started, and that is the point of holding the line at what is proven
#: rather than at what is documented.
ACCOUNT_PROVEN_EPHEMERAL_MB = 2048

#: BOTH NUMBERS ABOVE ARE ACCOUNT QUOTAS, WHICH MEANS THEY MOVE. Lambda's documented maxima —
#: 10,240 for either — are service limits and do not; an account's are raised by a support
#: request. So this gate is wrong in the DENYING direction the moment somebody lifts one, and
#: whoever hits it then meets a number that matches no documentation they can find.
#:
#: To re-derive rather than re-check: `aws service-quotas list-service-quotas --service-code
#: lambda` lists what is adjustable, but the authority is `CreateFunction` itself — the refusal
#: names the ceiling verbatim, which is how 3,008 was learned. Raising the AWS quota and raising
#: the constant here are ONE change, not two: leave them apart and the fleet keeps refusing a
#: value the account would now accept, with nothing to explain why.



#: The two dimensions this gate covers, and the constant bounding each. Written as a table so
#: the sweep, the fixtures and the failure message all read the same list — a third dimension
#: added to one and not the others is the way a gate goes half-quiet.
ACCOUNT_LIMITS = (
    ("memory", ACCOUNT_MAX_MEMORY_MB),
    ("ephemeral", ACCOUNT_PROVEN_EPHEMERAL_MB),
)



#: How a caller wires a function's size into the shared Lambda module. Every Lambda in this repo
#: goes through ``infra/modules/docker-lambda``, so a module that does not source it deploys no
#: function and its numbers answer to a different service — ``spa`` sizes a Fargate task, where
#: 4,096 MB is ordinary and this Lambda ceiling would be a false refusal of a correct value.
#:
#: Which modules those are is asked with ``fleet._is_fleet_module``, NOT with a substring test.
#: A private helper is reached into deliberately: its own docstring records that a suffix test
#: "accepted ``../not-docker-lambda`` and rejected ``../docker-lambda/`` — a legal trailing slash
#: that silently dropped an entire plane's verbs". A substring test written here reintroduced the
#: second half of that exactly, and a scratch module proved it: with the slash, every check in
#: this file passed over ``memory_mb = 10240``.
def declaration_files() -> list[pathlib.Path]:
    """Every Terraform file an account-quota number can reach ``CreateFunction`` through.

    The population this gate sweeps, and getting it wrong is how the gate stays green over a
    function it never read. It began as ``infra/modules/*/locals.tf`` — the per-module fleet map —
    and that missed TEN declarations: a module with one function passes ``memory_mb`` straight to
    the shared block in its own ``lambda.tf`` and never builds a map.

    **The gate's known ceiling is INDIRECTION, and it is not closeable from here.** A value
    assigned through a local — ``memory = local.heavy_tier`` — leaves no literal for any text
    sweep. Refusing non-literal assignment is not open either: indirection is how this fleet is
    wired. Resolving it needs the plan's own values, a CI-side check beside the apply that already
    knows, and it is recorded in ``docs/testing/owed.md`` rather than left silent — the guard
    below bounds the residue by FORM so a NEW kind of it cannot arrive unnoticed.

    The root's own ``.tf`` files are in: nothing there sizes a function today, because no plane
    module takes a size variable, but the moment one does — which is how a size becomes
    environment-tunable — the root is where the number would be written.

    Args:
      None.

    Returns:
      Every ``.tf`` file in a module that deploys a Lambda, plus the shared module's own and the
      root's, sorted.

    Raises:
      None.
    """
    modules = {MODULES / fleet.MODULE_SOURCE}
    for path in MODULES.rglob("*.tf"):
        if ".terraform" in path.parts:
            continue
        for body in module_calls(strip_comments(path.read_text(encoding="utf-8"))).values():
            if fleet._is_fleet_module(argument(body, "source")):
                modules.add(path.parent)
    found = set((ROOT / "infra").glob("*.tf"))
    for module in modules:
        found.update(path for path in module.rglob("*.tf") if ".terraform" not in path.parts)
    return sorted(found)


def declaration_pattern(dimension: str) -> str:
    """The regex that finds one dimension's declarations, used by the sweep AND its control.

    Derived in one place because a control compiling its own copy of the pattern is a control
    that keeps passing after the sweep's copy stops matching — the two drift apart silently and
    the tree looks healthy from both sides.

    The dimension may carry a prefix or a suffix: the keys are ``memory``, ``memory_mb`` and
    ``ephemeral`` today, but ``ephemeral_storage_mb`` is the spelling a new module is as likely to
    reach for, and a bare-token match walks straight past it while reporting nothing. The trade is
    deliberate and one-sided — ``max_memory = 10240`` is refused as well, which is a number in a
    fleet ``.tf`` a person should look at either way, against a miss that deploys unseen.

    The value may be QUOTED. ``memory = "10240"`` is not a typo that Terraform rejects: HCL
    converts a string to the declared ``number``, so ``tofu validate`` and ``tofu plan`` are both
    green and only the apply refuses — verified against a scratch module rather than argued.
    ``10_240`` needs no handling: HCL rejects numeric underscores outright.

    There is deliberately NO left lookbehind. One was written and removed as provably dead: where
    the rest of the pattern matches at a position whose predecessor is a word character, the
    greedy prefix also matches one character earlier, so the leftmost match is never the one a
    lookbehind would block. It read as anchoring and did nothing.

    Args:
      dimension: The token an account quota bites on, from ``ACCOUNT_LIMITS``.

    Returns:
      A regex whose first group is the key as written and whose second is the declared integer.

    Raises:
      None.
    """
    return rf'([A-Za-z0-9_]*{dimension}[A-Za-z0-9_]*)\s*=\s*"?(\d+)"?'


def over_account_limits(text: str, label: str) -> list[str]:
    """Names every declaration in ONE Terraform file that exceeds what this account will create.

    Split out from the sweep so the FIXTURES below can drive it against text rather than against
    the tree. Running a gate over the real tree proves the tree passes; it proves nothing about
    whether the check fires, and a gate whose checks have gone quiet looks exactly like a healthy
    repo.

    Two ways a number reaches ``CreateFunction`` are read, because they fail identically and are
    written differently: a direct assignment, and a ``variable`` block's ``default``, whose key on
    the line is the word ``default`` and which therefore no assignment pattern can see. The
    default is the more dangerous of the two — one line in the shared module, applying to every
    function that passes no argument, which is all of them but one.

    Args:
      text: The contents of one file from ``declaration_files`` — a module's ``locals.tf`` fleet
        map, its single-function ``lambda.tf``, or the shared module's ``variables.tf``. The
        checker is shape-agnostic about the first two: it reads ``key = digits`` and does not care
        whether the key sits in a map or in a ``module`` block.
      label: How to name the file in an offence, so the message points somewhere.

    Returns:
      One string per offending declaration, naming the key AS WRITTEN, the value and the ceiling —
      the key rather than the dimension, because a match on a suffixed spelling that reported the
      bare token would send the reader looking for a line that is not there.

    Raises:
      None.
    """
    live = strip_comments(text)
    offences = []
    for dimension, ceiling in ACCOUNT_LIMITS:
        for match in re.finditer(declaration_pattern(dimension), live):
            key, declared = match.group(1), int(match.group(2))
            if declared > ceiling:
                offences.append(f"{label}: {key} = {declared}, over this account's {ceiling}")
        for fallback in re.finditer(
            rf"([A-Za-z0-9_]*{dimension}[A-Za-z0-9_]*)\s*=\s*try\([^()]*?,\s*\"?(\d+)\"?\s*\)", live
        ):
            declared = int(fallback.group(2))
            if declared > ceiling:
                offences.append(
                    f"{label}: {fallback.group(1)} falls back to {declared}, "
                    f"over this account's {ceiling}"
                )
        for typed in re.finditer(
            rf"([A-Za-z0-9_]*{dimension}[A-Za-z0-9_]*)\s*=\s*optional\(\s*number\s*,\s*(\d+)\s*\)", live
        ):
            declared = int(typed.group(2))
            if declared > ceiling:
                offences.append(
                    f"{label}: {typed.group(1)} defaults to {declared}, over this account's {ceiling}"
                )
        for header in re.finditer(rf'variable\s+"([A-Za-z0-9_]*{dimension}[A-Za-z0-9_]*)"\s*\{{', live):
            body = span(live, header.end() - 1)[1:-1]
            try:
                default = argument(body, "default").strip('"')
            except ValueError:
                continue
            if default.isdigit() and int(default) > ceiling:
                offences.append(
                    f"{label}: variable {header.group(1)} defaults to {default}, "
                    f"over this account's {ceiling}"
                )
    return offences


def test_no_module_declares_more_memory_than_this_account_will_create() -> None:
    """The apply is the only thing that knows an account's quota, and the apply is too late.

    Nothing local can see this: `tofu validate` type-checks, `docker-lambda`'s own validation
    block enforces Lambda's DOCUMENTED range, and a plan does not call CreateFunction. So a
    number above the account's ceiling reaches `main`, fails the apply, and leaves the trunk red
    with half a plane deployed — which is exactly what happened.

    It is a fleet-wide sweep rather than a rule on the one module that hit it, because the next
    function to want more memory will be in a different module and its author will have the same
    information available: none. Fleet-wide means every ``.tf`` in a module that DEPLOYS a Lambda,
    plus the root's — ``declaration_files`` decides it — not the per-module fleet maps: a module
    deploying one function passes its size to ``docker-lambda`` in its own ``lambda.tf`` and builds
    no map to read.
    """
    offenders = []
    for path in declaration_files():
        offenders.extend(
            over_account_limits(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
        )
    assert offenders == [], (
        "these exceed what this account is known to create, and only the apply would say so: "
        f"{offenders}. Raise the AWS quota first, then this constant, then the declaration"
    )


#: The two ways a size is wired, by the file each lives in: a plane's verb map in its root file
#: (``plane-<slug>.tf``), and a single function's own ``lambda.tf``. Named rather than counted,
#: because a COUNT cannot see this regression and a shape can: narrowing the population to one
#: shape drops a whole family of declarations and can still clear a floor. The floor is the wrong
#: instrument for a whole shape going missing.
DECLARING_FILES = ("plane-*.tf", "lambda.tf")


def test_the_population_carries_both_ways_a_size_is_wired() -> None:
    """Both wiring shapes are present, so losing one is a red gate rather than a smaller number.

    This is the guard on the fix rather than on the fleet. The population began at the fleet maps
    alone and was blind to every module deploying a single function; a narrowing back to that glob
    passes every count-based check in this file, because the ten it drops are fewer than the slack
    any honest floor has to leave.
    """
    names = {path.name for path in declaration_files()}
    missing = [shape for shape in DECLARING_FILES if not fnmatch.filter(names, shape)]
    assert not missing, (
        f"the population no longer reaches {missing} — a whole way of declaring a size is "
        "unread, and every count in this file is still large enough to pass"
    )
    sources = {
        path.name
        for path in declaration_files()
        for _ in re.finditer(
            declaration_pattern("memory"), strip_comments(path.read_text(encoding="utf-8"))
        )
    }
    assert all(fnmatch.filter(sources, shape) for shape in DECLARING_FILES), (
        f"memory declarations are being read from {sorted(sources)} only; the sweep reaches a "
        "file shape it finds nothing in, which is how the narrowing looked last time"
    )


#: How few declarations each dimension may find before the sweep is presumed broken rather than
#: the fleet presumed compliant. Written down, not counted from the tree: a floor derived from
#: what the sweep just found is satisfied by finding nothing, which is the failure it exists to
#: catch. Memory is one per function across the whole fleet, spread over `locals.tf` maps and
#: single-function `lambda.tf` blocks; the floor sits under that count so retiring a module is not
#: a red gate. The count itself is not written here — `declaration_files` decides it and a number
#: beside it would go stale.
#:
#: **What this floor does NOT do, stated because it used to claim otherwise:** it does not catch
#: one file's worth of declarations going missing. The fleet's largest file holds 18 and its
#: smallest 1, so most single-file losses land above the floor and pass. That is not a slack
#: problem with a bigger number as the answer — a floor tight enough to catch the smallest file
#: reddens the moment anything is retired. The guards that actually catch a shrinking population
#: are `test_the_population_carries_both_ways_a_size_is_wired`, which is a SHAPE test, and
#: `max(found) == ceiling`, which fires the moment the file holding the largest value drops out.
#: This floor's job is narrower: it catches the sweep matching NOTHING.
#:
#: Ephemeral is declared only where a function needs more than Lambda's 512 MB default, which today
#: is one — so 1 is not a comfortable population, it is the number that still makes a renamed key
#: visible.
DECLARATIONS_AT_LEAST = {"memory": 70, "ephemeral": 1}


@pytest.mark.parametrize(("dimension", "ceiling"), ACCOUNT_LIMITS, ids=[d for d, _ in ACCOUNT_LIMITS])
def test_each_dimension_sweep_reads_the_declarations_it_claims_to(dimension: str, ceiling: int) -> None:
    """The positive control, once per dimension rather than once for the fleet.

    The sweep is a regex over files that may stop matching — a renamed key or a reformatted map
    makes it find nothing and pass forever. Memory had this control from the start; ephemeral did
    not, and its population is ONE declaration, which is precisely the case where a rename is
    invisible. Parametrising over the same table the sweep reads means a third dimension arrives
    with its control already attached instead of needing somebody to remember.
    """
    found = [
        int(match.group(2))
        for path in declaration_files()
        for match in re.finditer(
            declaration_pattern(dimension),
            strip_comments(path.read_text(encoding="utf-8")),
        )
    ]
    assert len(found) >= DECLARATIONS_AT_LEAST[dimension], (
        f"the {dimension} sweep found only {len(found)} declarations, under the "
        f"{DECLARATIONS_AT_LEAST[dimension]} this fleet has — the key was renamed, or the map "
        "reformatted, and the gate is now reading an empty set"
    )
    assert max(found) == ceiling, (
        f"the largest declared {dimension} is {max(found)}, not the {ceiling} this gate is "
        "written against, so either the declaration at the ceiling moved or the ceiling did"
    )


#: The gate's own corpus: one Terraform fragment per case, with what it must produce. Both DECLARING
#: SHAPES appear — the `locals.tf` fleet map and the `module` block a single-function module writes
#: in its own `lambda.tf` — because the sweep reads both and a corpus sampling one shape is a claim
#: about a population it never saw. Half of
#: these assert SILENCE, because half of a gate's regressions are false positives — a check that
#: refuses the value it was written to allow is as broken as one that allows what it must refuse,
#: and only a boundary pair can tell the two apart.
#:
#: Each offending case names its DIMENSION and its CEILING rather than only failing, because a
#: gate that says "something is over" sends the next reader to the wrong file.
ACCOUNT_LIMIT_CORPUS = (
    ("memory at the ceiling is allowed", '"a" = { memory = 3008 }', []),
    ("memory one over is refused", '"a" = { memory = 3009 }', ["memory = 3009, over this account's 3008"]),
    ("memory far over is refused", '"a" = { memory = 10240 }', ["memory = 10240, over this account's 3008"]),
    ("the old default is allowed", '"a" = { memory = 256 }', []),
    ("ephemeral at the proven value is allowed", '"a" = { ephemeral = 2048 }', []),
    ("ephemeral one over is refused", '"a" = { ephemeral = 2049 }', ["ephemeral = 2049, over this account's 2048"]),
    ("ephemeral at Lambda's documented max is refused", '"a" = { ephemeral = 10240 }', ["ephemeral = 10240, over this account's 2048"]),
    ("lambda's own default is allowed", '"a" = { ephemeral = 512 }', []),
    (
        "an optional attribute's default at the proven value is allowed",
        "type = object({ ephemeral_storage_mb = optional(number, 512) })",
        [],
    ),
    (
        "an optional attribute's default over the ceiling is refused",
        "type = object({ ephemeral_storage_mb = optional(number, 4096) })",
        ["ephemeral_storage_mb defaults to 4096, over this account's 2048"],
    ),
    (
        "both dimensions over are both reported",
        '"a" = { memory = 4096, ephemeral = 4096 }',
        ["memory = 4096, over this account's 3008", "ephemeral = 4096, over this account's 2048"],
    ),
    (
        "one offender among many compliant rows is the only one named",
        '"a" = { memory = 256 }\n"b" = { memory = 3008, ephemeral = 2048 }\n"c" = { memory = 5000 }',
        ["memory = 5000, over this account's 3008"],
    ),
    ("a module declaring neither is silent", 'requests_queue_name = "x-requests.fifo"', []),
    (
        "a suffixed spelling is not a way past the gate",
        '"a" = { ephemeral_storage_mb = 10240 }',
        ["ephemeral_storage_mb = 10240, over this account's 2048"],
    ),
    (
        "a prefixed spelling is not either, and the offence quotes the key as written",
        '"a" = { max_memory = 10240 }',
        ["max_memory = 10240, over this account's 3008"],
    ),
    ("a suffixed spelling under the ceiling is silent", '"a" = { ephemeral_storage_mb = 512 }', []),
    (
        "the OTHER declaring shape: a module block, aligned with spaces, is read the same way",
        'module "api" {\n  timeout_seconds = 29\n  memory_mb       = 10240\n}',
        ["memory_mb = 10240, over this account's 3008"],
    ),
    (
        "and is silent under the ceiling, so the shape is not what decides it",
        'module "api" {\n  timeout_seconds = 29\n  memory_mb       = 256\n}',
        [],
    ),
    (
        "a QUOTED value is not a way past it — HCL converts the string and only the apply refuses",
        '"a" = { memory = "10240" }',
        ["memory = 10240, over this account's 3008"],
    ),
    ("a quoted value under the ceiling is silent", '"a" = { memory = "256" }', []),
    (
        "a try() FALLBACK is a real declaration — it is what every verb omitting the key gets",
        "  ephemeral_storage_mb = try(each.value.ephemeral, 10240)",
        ["ephemeral_storage_mb falls back to 10240, over this account's 2048"],
    ),
    (
        "the fleet's own try() fallback is under the ceiling and silent",
        "  ephemeral_storage_mb = try(each.value.ephemeral, 512)",
        [],
    ),
    (
        "a variable DEFAULT is read, because the key on that line is the word default",
        'variable "ephemeral_storage_mb" {\n  type    = number\n  default = 10240\n}',
        ["variable ephemeral_storage_mb defaults to 10240, over this account's 2048"],
    ),
    (
        "a variable default under the ceiling is silent",
        'variable "ephemeral_storage_mb" {\n  type    = number\n  default = 512\n}',
        [],
    ),
    (
        "a COMMENTED-OUT declaration is silent in the two forms this tree uses",
        (
            '# was: memory = 10240 until CreateFunction refused it\n'
            '// memory = 10240\n'
            '"a" = { memory = 256 }'
        ),
        [],
    ),
    (
        "a BLOCK comment is silent too, since the shared parser blanks it like the other two",
        '/* memory = 10240 */\n"a" = { memory = 256 }',
        [],
    ),
    (
        "two offenders of the SAME dimension are both named, not just the first",
        '"a" = { memory = 4096 }\n"b" = { memory = 5000 }',
        [
            "memory = 4096, over this account's 3008",
            "memory = 5000, over this account's 3008",
        ],
    ),
    (
        "the widening's cost, stated rather than hidden: a word merely CONTAINING the token trips it",
        '"a" = { rememory = 10240, preephemeralism_seconds = 10240 }',
        [
            "rememory = 10240, over this account's 3008",
            "preephemeralism_seconds = 10240, over this account's 2048",
        ],
    ),
)


@pytest.mark.parametrize(
    ("case", "fragment", "expected"),
    ACCOUNT_LIMIT_CORPUS,
    ids=[case for case, _, _ in ACCOUNT_LIMIT_CORPUS],
)
def test_the_account_ceiling_gate_fires_and_stays_silent_where_it_should(
    case: str, fragment: str, expected: list[str]
) -> None:
    """A gate owes a corpus, not a green run against the tree it guards.

    Running this gate over today's modules proves the modules pass and says nothing about whether
    the check fires — and a gate whose checks have gone quiet is indistinguishable from a healthy
    repo. This drives the checker against text, at both boundaries of both dimensions, and asserts
    the REASON rather than a count: the message has to name which dimension and which ceiling, or
    it sends the next reader to the wrong place.
    """
    offences = over_account_limits(fragment, "fixture/locals.tf")
    assert len(offences) == len(expected), f"{case}: got {offences}"
    for offence, wanted in zip(offences, expected, strict=True):
        assert wanted in offence, f"{case}: {offence!r} does not say {wanted!r}"
        assert offence.startswith("fixture/locals.tf: "), f"{case}: the offence names no file"


_SIZE_KEY = re.compile(r"([A-Za-z0-9_]*(?:memory|ephemeral)[A-Za-z0-9_]*)\s*=\s*")


def _size_assignments(text: str) -> list[tuple[str, str]]:
    """Every ``<size key> = <value>`` in one file, with the value read to its real end.

    A regex cannot do this alone. Stopping the value at the next comma truncates
    ``try(each.value.ephemeral, 512)`` to something that matches no wiring form and reads as an
    unknown expression; not stopping at a comma swallows the neighbour in
    ``{ memory = 3008, ephemeral = 2048 }``. So the value is scanned with a paren depth: a comma
    ends it only at depth zero, and so does a brace or a newline.

    Args:
      text: One Terraform file's contents, comments already stripped.

    Returns:
      One ``(key, value)`` pair per assignment, values stripped of surrounding space.

    Raises:
      None.
    """
    found = []
    for match in _SIZE_KEY.finditer(text):
        depth, end = 0, match.end()
        while end < len(text):
            char = text[end]
            if char == "(":
                depth += 1
            elif char == ")" and depth:
                depth -= 1
            elif depth == 0 and char in ",}\n":
                break
            end += 1
        found.append((match.group(1), text[match.end() : end].strip()))
    return found


#: The wiring forms a size may reach the shared module through WITHOUT carrying a literal this
#: gate can read. Matched as FORMS rather than listed as files or counted: a new plane wiring
#: itself up the ordinary way adds no new form and this stays green, while a genuinely new kind of
#: indirection — ``memory = local.heavy_tier`` — is not in the set and reddens.
#:
#: This is the structural answer to a class of finding that recurred across two review frames.
#: Each round widened the matcher and the next found another spelling past it; a text sweep over
#: HCL has no last escape. So the blind spot is BOUNDED and named here instead: the gate cannot
#: tell what these resolve to, and the check that could reads the plan's own values from CI —
#: recorded in ``docs/testing/owed.md``.
UNVERIFIABLE_WIRING = (
    re.compile(r"^each\.value\.(?:memory|ephemeral|ephemeral_storage_mb)$"),
    re.compile(r"^number$"),
    re.compile(r"^optional\(number,\s*\d+\)$"),
    re.compile(r"^try\(each\.value\.(?:memory|ephemeral),\s*\d+\)$"),
    re.compile(r"^var\.[A-Za-z0-9_]+$"),
)

#: Expressions that must NOT be covered by the forms above — the positive control on an ALLOWLIST,
#: which fails in the widening direction. A list of exemptions has no natural red state: broadening
#: one entry to ``.*`` silences the guard completely and every other test here still passes, which
#: is the same "a check that cannot fire" shape this spec removed from production code.
UNCOVERED_WIRING = (
    "local.heavy_tier",
    "local.memory_tier",
    "one_of(var.a, var.b)",
    "3008 + 1",
    # These four are the TARGETED widenings, not the total ones. Deleting a single trailing `$`
    # from a form makes it a prefix test, and every string above is still refused while an
    # arithmetic or member expression built on the legitimate prefix walks straight through. A
    # control that only rejects `.*` catches the widening nobody would make by accident.
    "each.value.memory * local.multiplier",
    "each.value.ephemeral + 1024",
    "try(each.value.memory, 512) * 2",
    "var.memory_mb == null ? 10240 : var.memory_mb",
)


def test_the_wiring_allowlist_still_refuses_an_unknown_expression() -> None:
    """The control on the exemption list, because an allowlist has no natural failure.

    Every other assertion in this file gets stricter as the tree grows. This one gets LOOSER: a
    form broadened by one character stops refusing anything and nothing goes red. So the refusals
    are asserted directly.
    """
    for expression in UNCOVERED_WIRING:
        assert not any(form.match(expression) for form in UNVERIFIABLE_WIRING), (
            f"{expression!r} is accepted as known wiring; a form here has been widened past the "
            "three the fleet actually uses, and the blind-spot guard now permits anything"
        )


def test_every_size_the_gate_cannot_read_is_a_known_wiring_form() -> None:
    """The gate's blind spot is bounded and named, rather than unbounded and unmentioned.

    A value assigned through an expression carries no literal, so the sweep is silent on it — and
    silence from a gate is indistinguishable from compliance. What keeps that honest is not
    resolving the expression, which needs the plan, but refusing to let a NEW kind of expression
    appear without anybody noticing.

    A file list or a count would not do this. Both grow legitimately every time a plane is added,
    so both get raised, and raising them is exactly how a new indirection slips in behind the
    ordinary ones. The forms do not grow: every module wires a size the same three ways.
    """
    unknown = []
    for path in declaration_files():
        live = strip_comments(path.read_text(encoding="utf-8"))
        for key, value in _size_assignments(live):
            if re.fullmatch(r'"?\d+"?', value):
                continue
            if any(form.match(value) for form in UNVERIFIABLE_WIRING):
                continue
            unknown.append(f"{path.relative_to(ROOT)}: {key} = {value}")
    assert not unknown, (
        "these declare a size through an expression this gate has never seen, so it cannot read "
        f"the number and nothing else will until the apply: {unknown}. Either wire it the way the "
        "fleet already does, or add the form above and say why it is safe"
    )


def test_an_offence_names_a_path_a_reader_can_open() -> None:
    """The label the sweep passes is a repo-relative PATH, not a basename.

    The corpus can only see the label it supplies itself, so nothing there constrains what the
    sweep hands over. With a fleet-wide population that matters: fifteen modules have a
    ``lambda.tf``, and an offence reading ``lambda.tf: memory_mb = 10240`` names all of them.
    Planted by labelling with ``path.name``, which every other test in this file survives — so
    this OBSERVES the label the sweep passes rather than recomputing it. A test that derives the
    expected label from the same expression the sweep uses agrees with the sweep by construction
    and cannot see the plant at all; the first draft of this did exactly that and passed.
    """
    seen: list[str] = []
    original = globals()["over_account_limits"]
    globals()["over_account_limits"] = lambda text, label: seen.append(label) or []
    try:
        test_no_module_declares_more_memory_than_this_account_will_create()
    finally:
        globals()["over_account_limits"] = original

    assert seen, "the sweep called the checker for no file at all"
    bare = [label for label in seen if "/" not in label]
    assert not bare, (
        "the sweep labels a file by its basename; fifteen modules have a lambda.tf, so an "
        f"offence would not say which one: {bare[:3]}"
    )
    assert all(label.startswith("infra/") for label in seen), (
        "a label is not relative to the repo root, so it does not resolve from where the reader "
        "of the message is standing"
    )


def test_the_gate_covers_every_dimension_an_account_quota_can_bite() -> None:
    """The gate is two checks, and both are listed in one table the sweep and the corpus share.

    A third dimension added to the sweep and not the corpus — or to neither, while the constants
    grow one — is how this goes half-quiet while still reading as installed. Naming the covered
    set out loud is also the honest scope: it covers what this account has actually refused or
    accepted, and nothing about dimensions nobody has tested.
    """
    assert [dimension for dimension, _ in ACCOUNT_LIMITS] == ["memory", "ephemeral"]
    covered = {
        dimension
        for dimension, _ in ACCOUNT_LIMITS
        for case, _, expected in ACCOUNT_LIMIT_CORPUS
        if expected and dimension in expected[0]
    }
    assert covered == {"memory", "ephemeral"}, (
        f"the corpus exercises {covered}; a dimension the sweep checks and the corpus does not "
        "is a check that can go quiet without anything noticing"
    )
