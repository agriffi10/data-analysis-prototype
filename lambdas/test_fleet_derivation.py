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
