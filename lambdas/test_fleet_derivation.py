"""The fleet's Terraform-derived membership, and the two lists that must not drift from it.

**This file is the bridge that makes deleting the deploy table safe.** `.github/lambda-functions.json`
is the fleet's declaration today and `lambdas/fleet.py` is its replacement; the first test asserts
they are the same 86 names in both directions, so the replacement is proven against the thing it
replaces *before* that thing is deleted. It goes when the table does, having done its job.

The other two guard the replacement's own soft spot. The root output aggregates fourteen module
outputs by hand in a `concat`, which is a new hand-maintained list of exactly the kind this spec
exists to remove — a plane added to `main.tf` and forgotten there would contribute no functions,
CI would shard over a fleet one plane short, and every set comparison downstream derives from the
same output and would agree with the shortfall.

Attributes:
  ROOT: The repository root.
  TABLE: The deploy table being retired.
  ROOT_TF: The root module's Terraform, where the aggregation lives.
  MODULES: The bounded-context module directory.
  AGGREGATE: The local the root output reads.
"""

import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
TABLE = ROOT / ".github" / "lambda-functions.json"
ROOT_TF = ROOT / "infra" / "outputs.tf"
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


def test_the_derivation_and_the_deploy_table_are_the_same_fleet() -> None:
    """The replacement is proven against the thing it replaces, both directions.

    One direction alone is not enough and the asymmetry is the point: a derivation that finds
    FEWER functions than the table ships a fleet with an un-deployed function in it, and one that
    finds MORE points at a function Terraform never created, where `point-lambda.sh` waits five
    minutes per name before failing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two disagree in either direction.
    """
    derived = set(fleet.function_names(ROOT))
    declared = {entry["name"] for entry in json.loads(TABLE.read_text(encoding="utf-8"))}

    assert derived == declared, (
        f"the Terraform derivation finds {len(derived)} functions and {TABLE.name} declares "
        f"{len(declared)}. Only derived: {sorted(derived - declared)}. Only in the table: "
        f"{sorted(declared - derived)}. The table is deleted against this agreement, so it must "
        "hold before the deletion, not after."
    )


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
