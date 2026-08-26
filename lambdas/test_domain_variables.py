"""The front door's domain is an environment fact, and an empty one must not reach ACM.

Every failure this file guards against **plans green**. The variables carry no default on
purpose, but a missing default only fails when the variable is genuinely absent — and an unset
GitHub repo variable does not arrive absent. ``$${{ vars.X }}`` renders as the EMPTY STRING, which
satisfies a required variable and overrides a defaulted one alike. Measured on OpenTofu: with
``TF_VAR_spa_subdomain=""`` the origin plans as ``https://.example.com``, which is plausible
enough to be requested and is refused only at apply, by ACM, in a message that does not name the
repo variable behind it.

**The two halves are one guard.** The zone id's shape is checked here for the same reason the
grant is scoped: the id is rendered into the deploy role's Route 53 statement as well as into the
records, and IAM matches ARNs literally. The ``/hostedzone/``-prefixed form the API returns names
the right zone, reads correct to a human, and yields a grant that matches nothing — so every
record write is denied for a reason the value does not look like it could cause.

**What this file cannot prove.** These are text assertions over Terraform source. That the
certificate issues, that the validation record resolves, and that the delegated zone answers are
live checks; the acceptance script owns them.

Attributes:
  INFRA: The IaC tree.
  VARIABLES: The root variable declarations.
  MAIN: The root locals that build the origins and hosts.
  OUTPUTS: The root outputs re-exporting them.
  CERTIFICATES: The two certificates, their validation records and their validations.
  TFVARS_EXAMPLE: The documented example, which is outside validate_docs.py's comment sweep.
  WORKFLOW: The infrastructure workflow carrying both env blocks.
  DOMAIN_VARIABLES: The four variables that must each carry a validation block.
  REQUIRED_DOMAIN_VARIABLES: The two that must additionally carry no default.
  ENVIRONMENT_LITERALS: Values that are environment facts and may appear in no Terraform source.
  ACCEPTED: Values each variable's validation must admit.
  REFUSED: Values it must refuse. The empty string leads every row on purpose — it is what an
    unset repo variable actually produces, and the one value the absent default was wrongly
    believed to stop.
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


def test_the_required_domain_variables_carry_no_default() -> None:
    """The two environment facts must not acquire a plausible-looking fallback.

    A default here would be worse than an empty string: it would build a real certificate
    for somebody else's domain and apply green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either declares a default.
    """
    for name in REQUIRED_DOMAIN_VARIABLES:
        assert not re.search(r"^\s*default\s*=", _variable_block(name), re.MULTILINE), (
            f"{name} must have no default — it is an environment fact"
        )


def test_equal_subdomains_are_refused_by_a_precondition() -> None:
    """The one bad pairing no single variable's validation can see.

    Equal subdomains put both hosts on one name: two certificates for it, then two
    validation records with the same name and type, each overwriting the other's token.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If nothing compares the two subdomains.
    """
    text = CERTIFICATES.read_text()
    assert "precondition {" in text, "a precondition must compare the two subdomains"
    assert re.search(
        r"var\.spa_subdomain\s*!=\s*var\.api_subdomain|var\.api_subdomain\s*!=\s*var\.spa_subdomain",
        text,
    ), "the precondition must require the two subdomains to differ"


def test_each_certificate_names_its_own_host_and_the_variable_zone() -> None:
    """A certificate pointed at the wrong host applies green and fails at the listener.

    Nothing else in this file would notice: the literal sweep blocks only the two known
    environment values, so a hard-coded foreign zone id passes it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either certificate names the wrong host, or any validation record
        takes its zone from anything but the variable.
    """
    text = CERTIFICATES.read_text()
    for resource, host in (("spa", "local.spa_host"), ("api", "local.api_host")):
        block = re.search(
            r'resource\s+"aws_acm_certificate"\s+"' + resource + r'"\s*\{(.+?)\n\}',
            text,
            re.DOTALL,
        )
        assert block, f"the {resource} certificate must be declared"
        assert re.search(r"domain_name\s*=\s*" + re.escape(host), block.group(1)), (
            f"the {resource} certificate must name {host}"
        )

    zone_assignments = re.findall(r"^\s*zone_id\s*=\s*(.+)$", text, re.MULTILINE)
    assert len(zone_assignments) == 2, "both validation records must set a zone"
    for assignment in zone_assignments:
        assert assignment.strip() == "var.route53_zone_id", (
            f"a validation record takes its zone from {assignment.strip()}, not the variable"
        )


def test_both_workflow_env_blocks_carry_all_four_variables() -> None:
    """Adding to one block leaves the plan gate evaluating what will never be applied.

    The env KEY must be lowercase-suffixed. ``vars.X`` lookup is case-insensitive, but
    Terraform parses the key: ``TF_VAR_PARENT_DOMAIN`` declares ``var.PARENT_DOMAIN`` and
    leaves ``var.parent_domain`` unset.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any variable appears in fewer than both blocks.
    """
    text = WORKFLOW.read_text()
    for name in DOMAIN_VARIABLES:
        occurrences = len(re.findall(r"^\s*TF_VAR_" + name + r":", text, re.MULTILINE))
        assert occurrences == 2, (
            f"TF_VAR_{name} appears in {occurrences} env blocks, expected both plan and apply"
        )


def test_the_defaulted_subdomains_fall_back_in_the_workflow() -> None:
    """A default is dead code in CI without this, because an empty env var overrides it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either subdomain is passed without a fallback.
    """
    text = WORKFLOW.read_text()
    for name, fallback in (("spa_subdomain", "portal"), ("api_subdomain", "api")):
        assert (
            len(re.findall(r"TF_VAR_" + name + r":.*\|\|\s*'" + fallback + r"'", text)) == 2
        ), f"TF_VAR_{name} must fall back to '{fallback}' in both env blocks"


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


def test_the_origins_and_hosts_are_re_exported() -> None:
    """The consumers are other specs' modules, which read them from root outputs.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any is not exported.
    """
    text = OUTPUTS.read_text()
    for name in ("spa_origin", "api_origin", "spa_host", "api_host"):
        block = re.search(
            r'output\s+"' + name + r'"\s*\{(.+?)\n\}', text, re.DOTALL
        )
        assert block, f"{name} must be re-exported from root"
        assert re.search(r"value\s*=\s*local\." + name + r"\b", block.group(1)), (
            f"output {name} must carry local.{name} — a name alone can front any value"
        )


def test_no_terraform_source_names_the_environment() -> None:
    """The domain and the zone id reach Terraform as variables and nowhere else.

    A literal would survive every plan and be found only when the value changed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any .tf or .tftpl carries either literal.
    """
    for path in list(INFRA.rglob("*.tf")) + list(INFRA.rglob("*.tftpl")):
        text = path.read_text()
        for literal in ENVIRONMENT_LITERALS:
            assert literal not in text, (
                f"{path.relative_to(INFRA)} names the environment fact {literal!r} — "
                "it must arrive as a variable"
            )


def test_both_certificates_validate_by_dns_and_replace_before_destroy() -> None:
    """A certificate a live listener references must not be destroyed before its successor.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either certificate omits either property.
    """
    text = CERTIFICATES.read_text()
    assert len(re.findall(r'validation_method\s*=\s*"DNS"', text)) == 2, (
        "both certificates validate by DNS"
    )
    assert len(re.findall(r"create_before_destroy\s*=\s*true", text)) == 2, (
        "both certificates replace before destroying"
    )


def test_both_validations_cap_their_create_timeout_under_the_job_budget() -> None:
    """The provider's 75-minute default outlives the job, which is the damaging outcome.

    Both workflow jobs cap at 30 minutes, so a validation left at the default is killed by
    the runner mid-apply rather than failing as a Terraform error — stranding the backend's
    state lock and blocking every later apply until somebody clears it by hand.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either validation omits a create timeout, or one is not under the
        job's own cap.
    """
    text = CERTIFICATES.read_text()
    timeouts = re.findall(r'create\s*=\s*"(\d+)m"', text)
    assert len(timeouts) == 2, "both validations must set an explicit create timeout"

    budget = re.findall(r"^\s*timeout-minutes:\s*(\d+)", WORKFLOW.read_text(), re.MULTILINE)
    assert budget, "the workflow must declare a job timeout to measure against"
    cap = min(int(value) for value in budget)
    for value in timeouts:
        assert int(value) < cap, (
            f"a {value}m validation timeout is not under the {cap}m job budget"
        )


def test_the_route53_grant_is_scoped_to_the_one_zone() -> None:
    """A wildcard here would let the deploy role write records in any zone on the account.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the grant still names every hosted zone.
    """
    grant = (
        INFRA
        / "modules"
        / "base"
        / "policies"
        / "github-actions-deploy-platform-frontdoor.json.tftpl"
    ).read_text()
    assert "arn:aws:route53:::hostedzone/*" not in grant, (
        "the Route 53 grant must name the zone, not every zone on the account"
    )
    assert "arn:aws:route53:::hostedzone/${route53_zone_id}" in grant, (
        "the grant must render the zone id from the same variable the records read"
    )


def test_the_example_documents_the_domain_variables() -> None:
    """The example is where somebody standing up a second environment looks first.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the four is undocumented.
    """
    text = TFVARS_EXAMPLE.read_text()
    for name in DOMAIN_VARIABLES:
        assert name in text, f"{name} is undocumented in terraform.tfvars.example"
