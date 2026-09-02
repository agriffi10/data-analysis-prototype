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

import pathlib
import re

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


def test_the_module_creates_the_function_s_log_group(function: str) -> None:
    """A function and its log group cannot be declared in two places and disagree.

    Args:
      function: The resource body.

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
    assert "aws_cloudwatch_log_group.this" in function, (
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
    assert re.search(r"regex\(.*\\\\\.", command) or "\\\\." in command, (
        "nothing constrains the command's shape; it must be <module>.<handler>, the same string "
        "the zip-packaged function carried as its handler"
    )


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
    pattern = re.search(r'regex\("([^"]+)"', body)
    assert pattern, "the validation does not constrain the tag's shape"
    assert not re.match(pattern.group(1).replace("\\\\", "\\"), ""), (
        "the validation pattern accepts the empty string, which is what an unset repository "
        "variable renders as"
    )


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
