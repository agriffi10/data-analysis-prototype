"""The fleet is container-packaged, and nothing that names a function rebuilds its ARN.

Four claims, each an ABSENCE, which is what a review reads worst and a sweep answers completely:
no zip-packaged function survives, no placeholder artefact survives, no `.tf` constructs a Lambda
ARN, and no permission binds to a name.

**The last of those is the one that would have shipped green.** `package_type` is ForceNew, so
every function is destroyed and recreated. A permission bound to `.function_name` is a
config-known literal, identical either side of that replacement, so Terraform plans NO DIFF — and
meanwhile `DeleteFunction` has taken the function's resource policy with it. The API 500s on every
request, sign-up breaks, and every plane's timeout notifier goes silent, behind a green apply, a
green deploy and a green cold-start probe (a probe invokes through IAM, which never consults the
resource policy). Binding to the module's `function_arn` output fixes it because the ARN is
COMPUTED, therefore unknown during a replacement, and `aws_lambda_permission.function_name` is
itself ForceNew.

These are TEXT assertions over the configuration. The plan-side half — that every planned function
is Image-packaged, that its command equals the handler the frozen fixture recorded, and that no
permission carries a bare name — is `.github/scripts/lambda_plan_guard.py`, which runs against a
rendered plan in CI.

Attributes:
  INFRA: The IaC tree.
  FLEET_MODULE: The module source that makes a call one of the fleet's functions.
  ARN_EXEMPT: The ONE local that may still build a Lambda ARN from a template, and the module it
    lives in. Named as a specific local in a specific module rather than as a class of location:
    "inside a templatefile() input" was tried and is worthless, because every ASL definition in
    this repo is a templatefile() call, so it admits the whole surface this rule protects.
"""

import json
import pathlib
import re

import pytest
from tf_blocks import argument, blocks, map_entries, module_calls, span, strip_comments

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
MODULES = INFRA / "modules"
CONTAINER_MODULE = MODULES / "docker-lambda"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "pre_cutover_plan.json"
FLEET_MODULE = '"../docker-lambda"'

ARN_EXEMPT = ("shared-spaces", "shared_space_function_arns")


def _tf_files() -> list[pathlib.Path]:
    """Every `.tf` file under `infra/`, the container module excluded where it is the subject.

    Args:
      None.

    Returns:
      The paths, sorted.

    Raises:
      None.
    """
    return sorted(INFRA.rglob("*.tf"))


def _fleet_calls() -> dict[pathlib.Path, dict[str, str]]:
    """Every call to the container module, by the file that makes it.

    Identified by `source` rather than by call name: a plane could reasonably call some other
    module one day, and a name-based filter would either miss a function or read a stranger as
    one.

    Args:
      None.

    Returns:
      Each `lambda.tf` mapped to its fleet calls, name to body.

    Raises:
      None.
    """
    found = {}
    for path in sorted(MODULES.glob("*/lambda.tf")):
        calls = {
            name: body
            for name, body in module_calls(path.read_text(encoding="utf-8")).items()
            if argument(body, "source") == FLEET_MODULE
        }
        if calls:
            found[path] = calls
    return found


def _moved_blocks(text: str) -> list[tuple[str, str]]:
    """The `from`/`to` pairs of every `moved` block in one file.

    Args:
      text: Terraform source.

    Returns:
      One pair per block, in file order.

    Raises:
      None.
    """
    pairs = []
    for match in re.finditer(r"(?m)^moved\s*\{", strip_comments(text)):
        block = span(text, match.start())
        source = re.search(r"^\s*from\s*=\s*(.+)$", block, re.MULTILINE)
        target = re.search(r"^\s*to\s*=\s*(.+)$", block, re.MULTILINE)
        assert source and target, f"a moved block sets no from/to: {block!r}"
        pairs.append((source.group(1).strip(), target.group(1).strip()))
    return pairs


def blocks_declared(path: pathlib.Path, kind: str) -> str:
    """`kind` if that file declares a resource of that type, otherwise the empty string.

    Read through `tf_blocks.blocks`, which scans the RAW source. `strip_noise` was tried and is
    exactly wrong here: it blanks string CONTENTS, so `resource "aws_lambda_function"` becomes
    `resource "                   "` and the sweep matches nothing — a guard that reports the
    tree clean whatever the tree holds.

    Args:
      path: The file to read.
      kind: The resource type to look for.

    Returns:
      `kind` when at least one such resource is declared, otherwise "".

    Raises:
      None.
    """
    return kind if blocks(path.read_text(encoding="utf-8"), kind) else ""


def _call_instances(module: str) -> dict[str, set[str]]:
    """The instance keys each of a module's fleet calls actually expands to.

    A call with `for_each = local.X` expands to X's keys; a singleton call expands to the empty
    key. Read from the plane's own `locals`, because that is the population a `moved` block has to
    match — and a block naming a key the map does not hold is the silent half of this failure.

    Args:
      module: The module directory name.

    Returns:
      Each call name mapped to its instance keys, `{""}` for a singleton.

    Raises:
      AssertionError: If a `for_each` names a local this cannot resolve, rather than resolving to
        an empty set that every comparison would then pass over.
    """
    directory = MODULES / module
    locals_source = "\n".join(
        strip_comments(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.tf"))
    )
    instances = {}
    for name, body in _fleet_calls().get(directory / "lambda.tf", {}).items():
        try:
            each = argument(body, "for_each")
        except ValueError:
            instances[name] = {""}
            continue
        local = re.fullmatch(r"local\.([a-z_]+)", each.strip())
        assert local, f"{module}: {name} iterates {each!r}, which this cannot resolve"
        opening = re.search(rf"^\s*{local.group(1)}\s*=\s*\{{", locals_source, re.MULTILINE)
        assert opening, f"{module}: cannot resolve local.{local.group(1)}"
        instances[name] = set(map_entries(span(locals_source, opening.start())))
    return instances


def test_no_zip_packaged_function_survives_anywhere_in_the_tree() -> None:
    """Derived from the tree, not from a list: a plane left behind fails rather than being missed.

    The container module declares the fleet's ONE `aws_lambda_function`. Any other is a function
    still carrying a runtime, a handler and a placeholder zip.
    """
    declaring = [
        path.relative_to(INFRA)
        for path in _tf_files()
        if path.parent != CONTAINER_MODULE
        and "aws_lambda_function" in blocks_declared(path, "aws_lambda_function")
    ]

    assert not declaring, f"still declaring aws_lambda_function directly: {declaring}"


def test_no_placeholder_artefact_survives() -> None:
    """A source-level sweep, deliberately: a data source need not appear in a plan's
    `planned_values` at all, so a plan guard is the wrong instrument for this one.

    The placeholder existed because a zip function had to be valid at create time. A container
    function is valid from its image, so every one of these is dead weight that still runs
    `archive_file` on every plan.
    """
    declaring = [
        path.relative_to(INFRA)
        for path in _tf_files()
        if re.search(r'data\s+"archive_file"', strip_comments(path.read_text()))
    ]

    assert not declaring, f"placeholder artefacts still declared in: {declaring}"


def test_every_fleet_call_names_a_handler() -> None:
    """The image declares no CMD, deliberately, so a function that forgot its command cannot
    start — and an empty list is a container that fails at INIT rather than one that quietly
    does the wrong thing.

    That the command equals the handler the function ACTUALLY carried is checked against the
    frozen pre-cutover fixture by the plan guard; deriving it here from the new code would only
    agree with itself.
    """
    calls = _fleet_calls()
    assert calls, "no call to the container module was found at all — this test proves nothing"

    for path, module in calls.items():
        for name, body in module.items():
            command = argument(body, "command")
            assert command.startswith("[") and command.strip("[] \n") != "", (
                f"{path.relative_to(INFRA)}: {name} supplies {command!r} as its command"
            )


def test_no_terraform_file_builds_a_lambda_arn_from_a_template() -> None:
    """FR-003, and the exemption is one named local in one module.

    Six planes fed a constructed ARN list to their state-machine role. Constructed is exactly
    what makes such a grant survive a replacement unchanged, so they consume the module's output
    instead. `shared-spaces` keeps its local because ONE `orchestrator` role serves both the
    machine and the verbs there, so reading the output would be a genuine cycle — and splitting
    a privileged inline policy on the plane that owns the delete cascade, during the cutover, to
    buy a tidier test, is not a trade worth making.

    Scoped to `.tf`. The deploy role's own `.tftpl` policies legitimately name Lambda wildcards,
    and widening this to reach them would need an exemption list — a coupling that reddens on a
    correct change.
    """
    offenders = []
    for path in _tf_files():
        for line in strip_comments(path.read_text()).splitlines():
            if "arn:aws:lambda:" not in line:
                continue
            module = path.parent.name
            if module == ARN_EXEMPT[0] and ARN_EXEMPT[1] in path.read_text():
                continue
            offenders.append(f"{path.relative_to(INFRA)}: {line.strip()}")

    assert not offenders, (
        "a constructed Lambda ARN stays KNOWN while the function it names is replaced, so "
        f"whatever consumes it plans no diff at all: {offenders}"
    )


def test_the_one_exempt_local_is_still_exactly_one_local_in_one_module() -> None:
    """The exemption above is only safe while it is this narrow, so it is asserted rather than
    trusted — a second module quietly acquiring one would pass the test above by name."""
    module, local = ARN_EXEMPT
    source = "\n".join(
        strip_comments(path.read_text()) for path in sorted((MODULES / module).glob("*.tf"))
    )

    assert f"{local} = [" in source, (
        f"local.{local} is gone from {module}; the exemption now covers nothing and should be "
        "deleted rather than left standing"
    )
    assert source.count("arn:aws:lambda:") == 1, (
        f"{module} builds {source.count('arn:aws:lambda:')} Lambda ARNs from templates, not one"
    )


@pytest.mark.parametrize("kind", ["aws_lambda_permission", "aws_lambda_event_source_mapping"])
def test_everything_that_names_a_function_names_its_ARN(kind: str) -> None:
    """THE outage this cutover invites, and the guard that makes it unreachable.

    A permission bound to `.function_name` is config-known and identical either side of the
    replacement, so it is never recreated while `DeleteFunction` takes the resource policy away.
    Bound to the module's `function_arn` it is unknown during the replacement, and
    `function_name` is ForceNew on the permission, so it is planned for replacement alongside.
    """
    bindings = []
    for path in _tf_files():
        for name, body in blocks(path.read_text(encoding="utf-8"), kind).items():
            binding = re.search(
                r"^\s*function_name\s*=\s*(.+)$", strip_comments(body), re.MULTILINE
            )
            assert binding, f"{path.relative_to(INFRA)}: {name} sets no function_name"
            bindings.append((f"{path.relative_to(INFRA)}:{name}", binding.group(1)))

    assert bindings, f"no {kind} was found at all — this test proves nothing"

    wrong = [
        (where, value)
        for where, value in bindings
        if not re.fullmatch(r"module\.[a-z_]+(\[[^\]]+\])?\.function_arn", value.strip())
    ]
    assert not wrong, (
        "every one of these must take the module's function_arn output; a name or a constructed "
        f"ARN is config-known and survives the replacement undiffed: {wrong}"
    )


def test_every_function_and_its_log_group_has_a_moved_block() -> None:
    """Without them Terraform plans a create at the new address and a destroy at the old one with
    NO DEPENDENCY EDGE — CreateFunction racing DeleteFunction on one name, and for the log group
    a ResourceAlreadyExistsException or lost logs.

    The expected TOTAL comes from the frozen pre-cutover fixture, not from the module tree.
    Deriving it from the tree is the self-referential shape that passes on a shrink: delete a
    function from a plane's map and delete its `moved` block, and a tree-derived count agrees.
    """
    expected = len(json.loads(FIXTURE.read_text(encoding="utf-8"))["functions"])
    blocks = {
        path.parent.name: _moved_blocks(path.read_text(encoding="utf-8"))
        for path in sorted(MODULES.glob("*/moved.tf"))
    }
    total = sum(len(pairs) for pairs in blocks.values())

    assert total == expected * 2, (
        f"{total} moved blocks for {expected} captured functions; there must be one per captured function and one "
        "per log group, or an unmoved address is a create racing a destroy"
    )

    for module, pairs in blocks.items():
        declared = set(_fleet_calls().get(MODULES / module / "lambda.tf", {}))
        functions, groups = set(), set()
        for source, target in pairs:
            call = re.fullmatch(
                r"module\.([a-z_]+)(\[\"[a-z0-9-]+\"\])?\.aws_(lambda_function|cloudwatch_log_group)\.this",
                target,
            )
            assert call, f"{module}: {target} is not an address inside a container-module call"
            assert call.group(1) in declared, (
                f"{module}: moved to module.{call.group(1)}, which this module does not call"
            )
            instance = f"{call.group(1)}{call.group(2) or ''}"
            (functions if call.group(3) == "lambda_function" else groups).add(instance)

            # The `from` half is checked as hard as the `to` half, and it is the half whose
            # error is silent: a wrong OLD address matches nothing in state, so Terraform moves
            # nothing and then plans a create at the new address beside a destroy at the real old
            # one — with no edge between them, which for a function is CreateFunction racing
            # DeleteFunction on one name. The `to` half of a typo'd pair fails at plan; the `from`
            # half does not.
            moved_from = re.fullmatch(
                r"aws_(lambda_function|cloudwatch_log_group)\.[a-z_]+(\[\"[a-z0-9-]+\"\])?",
                source,
            )
            assert moved_from, f"{module}: {source} is not an old function or log-group address"
            assert moved_from.group(1) == call.group(3), (
                f"{module}: {source} moves to a {call.group(3)}"
            )
            assert (moved_from.group(2) or "") == (call.group(2) or ""), (
                f"{module}: {source} moves to a different instance key — {call.group(2)}. A move "
                "between keys matches nothing in state and silently becomes a create racing a "
                "destroy"
            )

        assert functions == groups, (
            f"{module}: these instances moved a function without its log group, or the reverse: "
            f"{functions ^ groups}"
        )

        # And the keys must be the ones the calls actually expand to. Terraform TOLERATES a
        # `moved` block whose `from` is not in state — no error, no warning — so a typo'd key is
        # a block that moves nothing, and the resource falls back to the unordered create-beside-
        # destroy this whole file exists to prevent. Measured on real state: the plan is
        # byte-identical to the one with no `moved` block at all. The count stays 172 and the
        # function/log-group pairing stays balanced, so nothing above can see it.
        expected = {
            f'{call}["{key}"]' if key else call
            for call, keys in _call_instances(module).items()
            for key in keys
        }
        assert functions == expected, (
            f"{module}: the moved blocks name {sorted(functions - expected)} which this module "
            f"declares no instance for, and omit {sorted(expected - functions)}"
        )
