"""The front door's domain is an environment fact, and an empty one must not reach ACM.

Every failure here plans green: an unset repo variable renders as the empty string, which
satisfies a required variable and overrides a defaulted one alike. That, and the zone id's
literal-ARN half, are in ``infra/info/deploy-role-iam.md``. Whether the certificate issues and
the delegated zone answers are live checks.

Attributes:
  INFRA: The IaC tree.
  VARIABLES: The root variable declarations.
  MAIN: The root locals that build the origins and hosts.
  OUTPUTS: The root outputs re-exporting them.
  CERTIFICATES: The two certificates, their validation records and their validations.
  TFVARS_EXAMPLE: The documented example, outside validate_docs.py's comment sweep.
  WORKFLOW: The infrastructure workflow carrying both env blocks.
  DOMAIN_VARIABLES: The four variables that must each carry a validation block.
  REQUIRED_DOMAIN_VARIABLES: The two that must additionally carry no default.
"""

import pathlib
import re

INFRA = pathlib.Path(__file__).resolve().parent.parent / "infra"
VARIABLES = INFRA / "variables.tf"
MAIN = INFRA / "main.tf"
OUTPUTS = INFRA / "outputs.tf"
CERTIFICATES = INFRA / "certificates.tf"
TFVARS_EXAMPLE = INFRA / "terraform.tfvars.example"
WORKFLOW = (
    pathlib.Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "deploy-infra.yml"
)

DOMAIN_VARIABLES = ("parent_domain", "route53_zone_id", "spa_subdomain", "api_subdomain")
REQUIRED_DOMAIN_VARIABLES = ("parent_domain", "route53_zone_id")

ENVIRONMENT_LITERALS = ("dataquarry", "Z10330063QJICF0JG35VO")


def _variable_block(name: str) -> str:
    """Extracts one top-level variable block from the root variable declarations.

    A brace-counting walk rather than a regex, because a variable body contains nested
    ``validation`` blocks whose braces a non-greedy pattern stops at.

    Args:
      name: The variable's name.

    Returns:
      The block's source, from the opening brace to its match.

    Raises:
      AssertionError: If the variable is not declared.
    """
    text = VARIABLES.read_text()
    match = re.search(r'variable\s+"' + re.escape(name) + r'"\s*\{', text)
    assert match, f"root variable {name} is not declared"
    depth = 0
    for index in range(match.end() - 1, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[match.end() - 1 : index + 1]
    raise AssertionError(f"variable {name} has no closing brace")


def _validation_pattern(name: str) -> re.Pattern[str]:
    """Extracts a variable's validation regex and un-escapes it back to what HCL sees.

    The raw source carries HCL's own escaping — a regex ``\\.`` is written ``\\\\.`` in the
    file. Compiled straight from the file text that reads as "a literal backslash then any
    character", so a pattern that accepts ``example.com`` in Terraform rejects it in Python and
    every table row below would assert against a regex the deployment never uses.

    Args:
      name: The variable's name.

    Returns:
      The compiled pattern, escaped the way Terraform reads it.

    Raises:
      AssertionError: If the variable declares no regex-based validation.
    """
    block = _variable_block(name)
    match = re.search(r'can\(regex\("(.+?)",\s*var\.', block, re.DOTALL)
    assert match, f"{name} must validate with a regex over the value's shape"
    return re.compile(match.group(1).replace("\\\\", "\\"))


ACCEPTED = {
    "parent_domain": ("example.com", "dat.example.com", "my-site.co.uk", "xn--e1afmkfd.xn--p1ai"),
    "route53_zone_id": ("Z10330063QJICF0JG35VO", "Z2FDTNDATAQYW2"),
    "spa_subdomain": ("portal", "my-portal", "app2"),
    "api_subdomain": ("api", "api-v2"),
}

REFUSED = {
    "parent_domain": ("", "example.com.", "-bad.com", "com", "example.com/foo", "10.0.0.1", "Example.COM"),
    "route53_zone_id": ("", "/hostedzone/Z10330063QJICF0JG35VO", "hostedzone/Z123", "z10330063qjicf0jg35vo"),
    "spa_subdomain": ("", "Portal", "-portal", "a.b", "*"),
    "api_subdomain": ("", "API", "a.b", "api."),
}


def test_every_domain_variable_validates_against_real_values() -> None:
    """Asserting a validation block EXISTS proves nothing about what it refuses.

    A presence-only check passes against ``regex("^.*$")``, which is the exact defect this
    file was written to prevent — so each pattern is run against values instead.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a pattern admits a value it must refuse, or refuses one it must admit.
    """
    for name in DOMAIN_VARIABLES:
        pattern = _validation_pattern(name)
        for value in ACCEPTED[name]:
            assert pattern.fullmatch(value), f"{name} must accept {value!r}"
        for value in REFUSED[name]:
            assert not pattern.fullmatch(value), f"{name} must refuse {value!r}"


def test_the_origins_are_built_from_the_variables_at_root() -> None:
    """Presentation of the origin is settled in one place, and it is not a module.

    Matched whitespace-tolerantly: ``tofu fmt`` aligns the ``=`` across a locals block, so an
    exact-spacing assertion breaks on the next local somebody adds beside these.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the four locals is missing or not variable-derived.
    """
    text = MAIN.read_text()
    for local_name, expected in (
        ("spa_host", "${var.spa_subdomain}.${var.parent_domain}"),
        ("api_host", "${var.api_subdomain}.${var.parent_domain}"),
        ("spa_origin", "https://${var.spa_subdomain}.${var.parent_domain}"),
        ("api_origin", "https://${var.api_subdomain}.${var.parent_domain}"),
    ):
        assert re.search(
            r"^\s*" + local_name + r"\s*=\s*" + re.escape(f'"{expected}"'),
            text,
            re.MULTILINE,
        ), f"local.{local_name} must be built from the domain variables at root"
