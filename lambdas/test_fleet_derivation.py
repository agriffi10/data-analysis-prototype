"""The fleet's Terraform-derived membership, and the two lists that must not drift from it.

**The deploy table is gone, and the bridge that proved this replacement against it went with it.**
That test asserted the two were the same 86 names in both directions, and it landed and ran green
before a single deletion — which is what made the deletion safe rather than hopeful. It is not
kept: a test comparing the derivation against a file that no longer exists is not a weaker guard,
it is a broken one.

What remains guards the replacement's own soft spot. The root output aggregates fourteen module
outputs by hand in a `concat`, which is a new hand-maintained list of exactly the kind this spec
exists to remove — a plane added to `main.tf` and forgotten there would contribute no functions,
CI would shard over a fleet one plane short, and every set comparison downstream derives from the
same output and would agree with the shortfall.

Attributes:
  ROOT: The repository root.
  ROOT_TF: The root module's Terraform, where the aggregation lives.
  WORKFLOW: The deploy, whose shard filter is read out and run rather than restated.
  MODULES: The bounded-context module directory.
  AGGREGATE: The local the root output reads.
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROOT_TF = ROOT / "infra" / "outputs.tf"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-lambdas.yml"
MODULES = ROOT / "infra" / "modules"
AGGREGATE = "lambda_deployed_names"

sys.path.insert(0, str(ROOT / "lambdas"))
import fleet
from tf_blocks import argument, module_calls, output_blocks, strip_noise


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
    aggregated = {name.replace("_", "-") for name in _aggregated_modules()}
    declaring = _modules_declaring_functions()

    assert aggregated == declaring, (
        f"the root fleet aggregate concatenates {sorted(aggregated)} but the modules deploying "
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


def test_the_shards_cover_the_whole_fleet_exactly_once() -> None:
    """Every function lands in exactly one shard, and the union is the fleet.

    **A guard the tree claimed to have and never did.** `test_deploy_matrix.py`'s docstring said a
    shard expression selecting no functions was closed by
    `test_every_function_lands_in_exactly_one_shard` — a test that has never existed in any commit
    on any branch. What actually covers part of it is a runtime refusal in the workflow, and that
    fires only when a shard comes back EMPTY; a sharding expression that drops one function while
    leaving every shard non-empty was covered by nothing at all.

    **The workflow's own expression is EXTRACTED AND RUN, not restated.** Saying "the deploy uses
    the same modulo" is the kind of claim that is true when written and unchecked forever after —
    measured: mutating the workflow's `jq` filter to drop six of eighty-six functions, with every
    shard still non-empty so the runtime emptiness guard cannot fire, left the whole suite green.
    So the filter is read out of the YAML and executed against the real fleet, and its answer must
    equal `shard_of`'s for every shard.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a function is dropped, duplicated, or the shard count is wrong.
    """
    planned = fleet.plan(ROOT)
    names = planned["functions"]
    assert names, "the plan named no functions, so every assertion below would be vacuous"

    workflow = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"'(to_entries\[\][^']*)'", workflow)
    assert match, (
        f"no shard filter found in {WORKFLOW.name}. It was renamed or rewritten, and this test "
        "would otherwise go on checking a filter the deploy no longer runs."
    )
    selector = match.group(1)

    jq = shutil.which("jq")
    assert jq, (
        "jq is not installed, so the workflow's own filter cannot be run. Skipping would make this "
        "test silently stop guarding the expression the deploy uses, which is the whole point of "
        "reading it out of the YAML — CI has jq, and a laptop without it should say so."
    )

    collected: list[str] = []
    for shard in planned["shards"]:
        expected = fleet.shard_of(names, shard, planned["shard_count"])
        actual = subprocess.run(  # noqa: S603 — resolved binary, arguments built here
            [jq, "-r", "--argjson", "s", str(shard),
             "--argjson", "n", str(planned["shard_count"]), selector],
            input=json.dumps(names), capture_output=True, text=True, check=True,
        ).stdout.split()
        assert actual == expected, (
            f"shard {shard}: the workflow's filter selects {actual} and `shard_of` selects "
            f"{expected}. The test would be guarding an expression the deploy does not run."
        )
        collected.extend(expected)

    assert sorted(collected) == sorted(names), (
        f"the shards do not cover the fleet: dropped {sorted(set(names) - set(collected))}, "
        f"unexpected {sorted(set(collected) - set(names))}"
    )
    assert len(collected) == len(names), (
        f"{len(collected)} slots for {len(names)} functions — a function lands in more than one "
        "shard, so two jobs race `update-function-code` on it"
    )
    assert len(planned["shards"]) == planned["shard_count"], (
        "the shard list and the shard count disagree, so the matrix would spawn a different "
        "number of jobs than the selection expression divides by — which silently drops functions"
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
#: function and its numbers answer to a different service entirely — ``spa`` sizes a Fargate task,
#: where 4,096 MB is ordinary and this gate's Lambda ceiling would be a false refusal of a correct
#: value. The population is derived from that fact rather than from a list of module names, so a
#: new plane joins it by wiring itself up and nobody has to remember.
_SHARED_LAMBDA_MODULE = "docker-lambda"


def declaration_files() -> list[pathlib.Path]:
    """Every Terraform file an account-quota number can reach ``CreateFunction`` through.

    The population this gate sweeps, and getting it wrong is how the gate stays green over a
    function it never read. It began as ``infra/modules/*/locals.tf`` — the per-module fleet map —
    and that missed TEN declarations: a module with one function passes ``memory_mb`` straight to
    the shared block in its own ``lambda.tf`` and never builds a map. ``fleet.py``'s
    ``_locals_bodies`` states the same lesson for its own sweep, naming ``api`` and ``auth``; both
    were among the ten.

    **The gate's known ceiling is INDIRECTION, and it is not closeable from here.** A value
    assigned through a local or a variable — ``memory = local.heavy_tier`` — leaves no literal for
    any text sweep to read. Refusing non-literal assignment is not open either: indirection is how
    this fleet is wired, with seven legitimate ``memory_mb = each.value.memory`` sites. Resolving
    it needs the plan's own values, which is a CI-side check beside the apply that already knows,
    and it is recorded in ``docs/testing/owed.md`` rather than left as a silent limit.

    It is scoped to modules that SOURCE the shared Lambda module, plus that module itself for its
    variable defaults. Sweeping every ``.tf`` under ``infra/`` instead is one line shorter and
    wrong in the expensive direction: it reaches ``spa``'s Fargate task memory, which this ceiling
    does not govern, and a gate that refuses a correct value teaches the next person to route
    around it.

    ``.terraform`` is excluded rather than merely absent today: it holds nothing after a
    provider-only ``init``, but a registry module would put third-party HCL under it, and a
    population that changes depending on whether somebody has run ``init`` is a gate that
    disagrees with itself between machines.

    Args:
      None.

    Returns:
      Every ``.tf`` file in a module that deploys a Lambda, sorted.

    Raises:
      None.
    """
    modules = {MODULES / _SHARED_LAMBDA_MODULE}
    for path in MODULES.rglob("*.tf"):
        if ".terraform" in path.parts:
            continue
        if f'"../{_SHARED_LAMBDA_MODULE}"' in path.read_text(encoding="utf-8"):
            modules.add(path.parent)
    return sorted(
        path
        for module in modules
        for path in module.rglob("*.tf")
        if ".terraform" not in path.parts
    )


#: HCL's three comment forms. Stripped before the sweep reads a file, because a commented-out
#: declaration is the opposite of a deployed one and a gate that refuses
#: ``# was: memory = 10240 until CreateFunction refused it`` punishes the person documenting this
#: very trap. Applied to a population of many files, where commented HCL is ordinary.
_HCL_COMMENT = re.compile(r"/\*.*?\*/|(?<!:)//[^\n]*|#[^\n]*", re.DOTALL)


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
    live = _HCL_COMMENT.sub("", text)
    offences = []
    for dimension, ceiling in ACCOUNT_LIMITS:
        for match in re.finditer(declaration_pattern(dimension), live):
            key, declared = match.group(1), int(match.group(2))
            if declared > ceiling:
                offences.append(f"{label}: {key} = {declared}, over this account's {ceiling}")
        for block in re.finditer(
            rf'variable\s+"([A-Za-z0-9_]*{dimension}[A-Za-z0-9_]*)"\s*\{{(.*?)\n\}}', live, re.DOTALL
        ):
            default = re.search(r'\n\s*default\s*=\s*"?(\d+)"?', block.group(2))
            if default and int(default.group(1)) > ceiling:
                offences.append(
                    f"{label}: variable {block.group(1)} defaults to {default.group(1)}, "
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
    information available: none. Fleet-wide means every ``.tf`` under ``infra/`` — see
    ``declaration_files`` — not the per-module fleet maps: a module deploying one function passes
    its size to ``docker-lambda`` in its own ``lambda.tf`` and builds no map to read.
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


#: The two ways a size is wired, by the file each lives in. Named rather than counted, because a
#: COUNT cannot see this regression and a shape can: reverting the population to
#: ``modules/*/locals.tf`` drops the ten single-function declarations and leaves 71, which clears
#: a floor of 70 by one. The floor is the wrong instrument for a whole shape going missing.
DECLARING_FILES = ("locals.tf", "lambda.tf")


def test_the_population_carries_both_ways_a_size_is_wired() -> None:
    """Both wiring shapes are present, so losing one is a red gate rather than a smaller number.

    This is the guard on the fix rather than on the fleet. The population began at the fleet maps
    alone and was blind to every module deploying a single function; a narrowing back to that glob
    passes every count-based check in this file, because the ten it drops are fewer than the slack
    any honest floor has to leave.
    """
    names = {path.name for path in declaration_files()}
    missing = [name for name in DECLARING_FILES if name not in names]
    assert not missing, (
        f"the population no longer reaches {missing} — a whole way of declaring a size is "
        "unread, and every count in this file is still large enough to pass"
    )
    sources = {
        path.name
        for path in declaration_files()
        for _ in re.finditer(
            declaration_pattern("memory"), _HCL_COMMENT.sub("", path.read_text(encoding="utf-8"))
        )
    }
    assert set(DECLARING_FILES) <= sources, (
        f"memory declarations are being read from {sorted(sources)} only; the sweep reaches a "
        "file shape it finds nothing in, which is how the narrowing looked last time"
    )


#: How few declarations each dimension may find before the sweep is presumed broken rather than
#: the fleet presumed compliant. Written down, not counted from the tree: a floor derived from
#: what the sweep just found is satisfied by finding nothing, which is the failure it exists to
#: catch. Memory is one per function across the whole fleet, spread over `locals.tf` maps and
#: single-function `lambda.tf` blocks; the floor sits well under that count on purpose, so that
#: retiring a module is not a red gate while losing a whole file's worth still is. The count itself
#: is not written here — `declaration_files` decides it and this number would go stale beside it.
#: Ephemeral is declared only where a
#: function needs more than Lambda's 512 MB default, which today is one — so 1 is not a comfortable
#: population, it is the number that still makes a renamed key visible.
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
            _HCL_COMMENT.sub("", path.read_text(encoding="utf-8")),
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
        "a COMMENTED-OUT declaration is silent, in all three of HCL's comment forms",
        (
            '# was: memory = 10240 until CreateFunction refused it\n'
            '// memory = 10240\n'
            '/* memory = 10240 */\n'
            '"a" = { memory = 256 }'
        ),
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
