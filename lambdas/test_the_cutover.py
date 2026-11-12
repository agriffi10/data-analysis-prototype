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
"""

import pathlib
import re

import pytest
from tf_blocks import argument, blocks, module_calls, strip_comments

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
MODULES = INFRA / "modules"
CONTAINER_MODULE = MODULES / "docker-lambda"
FLEET_MODULE = '"../docker-lambda"'


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
    """No `.tf` builds a Lambda ARN from a template, and there is no exemption any more.

    Every state-machine role is fed its verbs' ARNs from the functions' own outputs. Constructed is
    exactly what makes such a grant survive a replacement unchanged. Shared spaces once kept a
    constructed list, because one role served both its machine and its verbs and reading the
    outputs was a cycle; its machine now has its own role, so the exemption went with the cycle.

    Scoped to `.tf`. The deploy role's own `.tftpl` policies legitimately name Lambda wildcards,
    and widening this to reach them would need an exemption list — a coupling that reddens on a
    correct change.
    """
    offenders = []
    for path in _tf_files():
        for line in strip_comments(path.read_text()).splitlines():
            if "arn:aws:lambda:" not in line:
                continue
            offenders.append(f"{path.relative_to(INFRA)}: {line.strip()}")

    assert not offenders, (
        "a constructed Lambda ARN stays KNOWN while the function it names is replaced, so "
        f"whatever consumes it plans no diff at all: {offenders}"
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


