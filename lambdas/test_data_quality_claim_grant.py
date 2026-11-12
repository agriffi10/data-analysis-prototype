"""The data-quality role can write its request-id claims, and nothing expires them.

``dqcommon.run_claim`` writes a claim under ``dqcommon.config.CLAIM_PREFIX`` in the admin bucket,
and the execution policy grants that prefix from the module's own local. Two literals for one value,
rendered on opposite sides of a deploy: a divergence denies every claim, and every check is refused
before it lists a file, with nothing on either side looking wrong.

The claim must also outlive every run that could reuse its id, which is forever. The admin bucket
expires several prefixes, one rule each, and a later rule whose prefix reached the claims would
quietly hand every expired id to the next execution that sent it.

Attributes:
  ROOT: The repository root.
  EXECUTION_POLICY: The data-quality execution role's policy template.
  PLANE: The plane's root call, which renders the template and passes the claim prefix to it.
  LIFECYCLE: The admin bucket's lifecycle configuration.
  ROOT_MAIN: Where the one variable prefix in that configuration is given its value.
  CLAIM_RESOURCE: The object resource the grant must name, with ``${`` rewritten for JSON parsing.
"""

import json
import pathlib
import re
import sys

import pytest
from tf_blocks import argument, module_calls, span

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXECUTION_POLICY = ROOT / "infra" / "planes" / "data-quality" / "execution.json.tftpl"
PLANE = ROOT / "infra" / "plane-data-quality.tf"
LIFECYCLE = ROOT / "infra" / "modules" / "analytics" / "s3.tf"
ROOT_MAIN = ROOT / "infra" / "main.tf"
CLAIM_RESOURCE = "@{admin_bucket_arn}/@{claim_prefix}/*"

sys.path.insert(0, str(ROOT / "lambdas" / "control-plane-common"))
sys.path.insert(0, str(ROOT / "lambdas" / "data-quality-common"))


def _as_list(value) -> list:
    """One value or many, always as a list.

    Args:
      value: A policy field that IAM allows in either form.

    Returns:
      The value as a list.

    Raises:
      None.
    """
    return value if isinstance(value, list) else [value]


def _blocks(text: str, opener: str) -> list[str]:
    """Every brace-delimited block in HCL text that opens with a given header.

    Args:
      text: The HCL text.
      opener: A regular expression matching the header up to, and including, its opening brace.

    Returns:
      Each block's text, from its header to the brace that closes it.

    Raises:
      AssertionError: When a block never closes, which would otherwise drop a rule unread.
    """
    blocks = []
    for match in re.finditer(opener, text):
        depth = 0
        for index in range(match.end() - 1, len(text)):
            depth += {"{": 1, "}": -1}.get(text[index], 0)
            if depth == 0:
                blocks.append(text[match.start() : index + 1])
                break
        else:
            raise AssertionError(f"a block opened by {opener!r} never closes")
    return blocks


def _rule_can_expire_a_claim(rule: str, claim_prefix: str, alb_prefix: str) -> bool:
    """Whether one lifecycle rule deletes objects and can match a claim key.

    A rule with no prefix matches every key in the bucket, and so does one filtered only by size or
    an empty prefix, which is why an absent prefix is read as the empty one rather than skipped.

    Args:
      rule: The rule block's text.
      claim_prefix: The claim prefix, without a trailing slash.
      alb_prefix: The value of the one variable a rule's prefix interpolates.

    Returns:
      True when the rule expires objects and its prefix reaches the claims.

    Raises:
      AssertionError: When a prefix interpolates a value this cannot resolve.
    """
    if not re.search(r"expiration\s*\{", rule):
        return False
    found = re.search(r'prefix\s*=\s*"([^"]*)"', rule)
    prefix = found.group(1).replace("${var.alb_access_log_prefix}", alb_prefix) if found else ""
    assert "${" not in prefix, f"unresolved lifecycle prefix {prefix!r}"
    return _reaches(prefix, claim_prefix)


def _execution_policy_vars() -> tuple[str, str]:
    """The template the plane's execution policy renders, and the literal map merged into its vars.

    Args:
      None.

    Returns:
      ``(template path as written, the braced map passed beside the shared ARNs)``.

    Raises:
      AssertionError: If the call does not render its policy with ``templatefile`` over a
        ``merge``, which would otherwise leave nothing to read the prefix from.
      ValueError: If the call or its ``execution_policy`` argument is missing.
    """
    expression = argument(module_calls(PLANE.read_text())["data_quality"], "execution_policy")
    template = re.match(r'templatefile\(\s*"\$\{path\.root\}/([^"]+)"\s*,\s*merge\(', expression)
    assert template, f"the data-quality execution policy is not a templatefile over a merge: {expression}"
    return template.group(1), span(expression, template.end())


def _admin_lifecycle_rules() -> list[str]:
    """Every rule in the admin bucket's lifecycle configuration.

    Args:
      None.

    Returns:
      Each rule block's text.

    Raises:
      AssertionError: When the configuration is missing.
    """
    text = LIFECYCLE.read_text()
    (configuration,) = _blocks(text, r'resource "aws_s3_bucket_lifecycle_configuration" "athena_admin" \{')
    return _blocks(configuration, r"\n\s*rule\s*\{")


def _alb_prefix() -> str:
    """The value the admin bucket's access-log rule interpolates.

    Args:
      None.

    Returns:
      The prefix.

    Raises:
      AssertionError: When the local is not found.
    """
    alb = re.search(r'alb_access_logs_prefix\s*=\s*"([^"]+)"', ROOT_MAIN.read_text())
    assert alb, f"no alb_access_logs_prefix local in {ROOT_MAIN.name}"
    return alb.group(1)


def _reaches(rule_prefix: str, claim_prefix: str) -> bool:
    """Whether an expiring rule's prefix matches any claim object.

    A lifecycle prefix anchors at the start of the key. A rule reaches the claims when every claim
    key starts with its prefix, and also when its prefix is narrower but still inside the claims,
    since that expires some of them.

    Args:
      rule_prefix: The rule's filter prefix.
      claim_prefix: The claim prefix, without a trailing slash.

    Returns:
      True when the rule can expire a claim.

    Raises:
      None.
    """
    claims = f"{claim_prefix}/"
    return claims.startswith(rule_prefix) or rule_prefix.startswith(claims)


def test_the_role_may_write_and_read_back_a_claim_under_the_prefix_python_writes() -> None:
    """The grant names the templated prefix, and both sides give that prefix the same value.

    Reading a claim back is what tells an execution's own retry from a different execution, so
    the read is asserted with the write.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the grant, the variable passed to the template, or the prefix's value on
        either side is missing or disagrees.
    """
    from dqcommon import config

    statements = json.loads(EXECUTION_POLICY.read_text().replace("${", "@{"))["Statement"]
    granted = {
        action
        for statement in statements
        if statement.get("Effect") == "Allow" and CLAIM_RESOURCE in _as_list(statement.get("Resource", []))
        for action in _as_list(statement.get("Action", []))
    }
    rendered, variables = _execution_policy_vars()
    terraform = re.fullmatch(r'"([^"$%]+)"', argument(variables[1:-1], "claim_prefix"))

    assert {"s3:PutObject", "s3:GetObject"} <= granted, f"{CLAIM_RESOURCE} is granted only {granted}"
    assert ROOT / "infra" / rendered == EXECUTION_POLICY, f"{PLANE.name} renders {rendered}, not this template"
    assert terraform, f"{PLANE.name} does not pass a literal claim_prefix to the execution policy"
    assert terraform.group(1) == config.CLAIM_PREFIX, (
        f"Terraform grants {terraform.group(1)!r} and Python claims under {config.CLAIM_PREFIX!r}"
    )


def test_no_expiring_lifecycle_rule_reaches_the_claims() -> None:
    """A claim is never expired, so its id is never handed to a later execution.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an expiring rule can match a claim key, or the parse did not find rules
        the bucket is known to hold.
    """
    from dqcommon import config

    rules = _admin_lifecycle_rules()

    assert any('"file-ops/"' in rule for rule in rules) and any("abort_incomplete_multipart_upload" in rule for rule in rules), (
        f"the lifecycle parse found {len(rules)} rules without ones the bucket is known to hold — "
        "the comparison below would hold over nothing"
    )
    assert not [rule for rule in rules if _rule_can_expire_a_claim(rule, config.CLAIM_PREFIX, _alb_prefix())], (
        f"an expiring admin-bucket rule reaches {config.CLAIM_PREFIX}/"
    )


_EXPIRE = "expiration {\n  days = 30\n}"
_ABORT = "abort_incomplete_multipart_upload {\n  days_after_initiation = 7\n}"


@pytest.mark.parametrize(
    ("rule", "expires_a_claim"),
    [
        (f'rule {{\n filter {{\n prefix = "data-quality/"\n }}\n {_EXPIRE}\n}}', True),
        (f'rule {{\n filter {{\n prefix = "data-quality/claims/0000"\n }}\n {_EXPIRE}\n}}', True),
        (f"rule {{\n filter {{}}\n {_EXPIRE}\n}}", True),
        (f'rule {{\n filter {{\n prefix = ""\n }}\n {_EXPIRE}\n}}', True),
        (f"rule {{\n filter {{\n object_size_greater_than = 1\n }}\n {_EXPIRE}\n}}", True),
        ('rule {\n filter {\n prefix = "data-quality/"\n }\n noncurrent_version_expiration {\n noncurrent_days = 1\n }\n}', True),
        (f'rule {{\n filter {{\n prefix = "file-ops/"\n }}\n {_EXPIRE}\n}}', False),
        (f'rule {{\n filter {{\n prefix = "data-quality/claimsets/"\n }}\n {_EXPIRE}\n}}', False),
        (f'rule {{\n filter {{\n prefix = "${{var.alb_access_log_prefix}}/"\n }}\n {_EXPIRE}\n}}', False),
        (f"rule {{\n filter {{}}\n {_ABORT}\n}}", False),
        (f'rule {{\n filter {{\n prefix = "data-quality/"\n }}\n {_ABORT}\n}}', False),
    ],
    ids=[
        "broader-prefix",
        "narrower-prefix",
        "no-filter",
        "empty-prefix",
        "size-only-filter",
        "noncurrent-versions",
        "other-prefix",
        "similar-prefix",
        "interpolated-prefix",
        "abort-only-unfiltered",
        "abort-only-on-the-prefix",
    ],
)
def test_a_rule_expires_a_claim_when_it_deletes_and_its_prefix_can_match(rule, expires_a_claim) -> None:
    """Every shape that deletes from the claims is flagged, and nothing that cannot delete is.

    Args:
      rule: A lifecycle rule block.
      expires_a_claim: Whether that rule can expire a claim.

    Returns:
      None.

    Raises:
      AssertionError: If the predicate misjudges the rule.
    """
    assert _rule_can_expire_a_claim(rule, "data-quality/claims", "alb-access-logs") is expires_a_claim
