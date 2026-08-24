"""The deploy role's policies must fit IAM's budgets, and a wildcard must be forced.

Two different failures live here, and neither is visible in a plan.

**The budgets.** IAM's 10,240-character limit is the AGGREGATE of a role's inline policies,
not a per-policy allowance, and ``github-actions-deploy.json.tftpl`` already measures 9,256
stripped. A customer-managed policy has its own separate 6,144-character budget. Both ceilings
are enforced at ``CreatePolicy``/``PutRolePolicy`` — an apply-time ``LimitExceeded`` on a
document that rendered, validated and planned green. The container platform's grants are two
managed policies rather than one for exactly this reason, and the next person to extend either
one should discover the ceiling here rather than in a deploy.

**The wildcard.** ``Resource: "*"`` on a deploy grant is sometimes forced and sometimes
laziness, and the two read identically in a diff. IAM defines no resource type at all for the
actions in ``NON_SCOPABLE`` below, so a narrower ARN on one of them is an implicit deny that
presents as a missing grant; every other action accepts an ARN and must carry one. The set was
not assembled by eye — each entry was measured with ``aws iam simulate-custom-policy``, reading
``implicitDeny`` under a scoped ARN of its own service and ``allowed`` under ``"*"``. The
``implicitDeny`` leg alone proves nothing, because a wrong ARN reads exactly the same; the
``allowed`` control is what makes the pair evidence.

The set is a literal rather than a live read of the AWS Service Reference, deliberately: a test
that reaches the network fails on a runner with no egress and passes by finding nothing when
the endpoint changes shape. It is a recorded measurement, and
``test_every_non_scopable_action_is_actually_granted`` keeps it from rotting into a list of
actions nobody grants any more.

Attributes:
  POLICY_DIR: Where every deploy-role policy template lives.
  INLINE_POLICY: The role's one inline policy, measured against the 10,240 aggregate.
  MANAGED_LIMIT: IAM's character budget for one customer-managed policy.
  INLINE_AGGREGATE_LIMIT: IAM's character budget for all of a role's inline policies together.
  PLATFORM_POLICIES: The two templates this spec adds.
  NON_SCOPABLE: Every action IAM defines no resource type for, and therefore the only actions
    a ``Resource: "*"`` statement in those two templates may hold.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "infra" / "modules" / "base" / "policies"
INLINE_POLICY = POLICY_DIR / "github-actions-deploy.json.tftpl"

MANAGED_LIMIT = 6_144
INLINE_AGGREGATE_LIMIT = 10_240

PLATFORM_POLICIES = (
    POLICY_DIR / "github-actions-deploy-platform.json.tftpl",
    POLICY_DIR / "github-actions-deploy-platform-frontdoor.json.tftpl",
)

NON_SCOPABLE = frozenset(
    {
        "ec2:DescribeVpcs",
        "ec2:DescribeSubnets",
        "ec2:DescribeRouteTables",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSecurityGroupRules",
        "ec2:DescribeVpcEndpoints",
        "ec2:DescribeVpcEndpointServices",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeNetworkAcls",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeAccountAttributes",
        "ec2:DescribeFlowLogs",
        "ec2:DescribeManagedPrefixLists",
        "ec2:DescribePrefixLists",
        "ec2:DescribeTags",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetGroupAttributes",
        "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeListenerAttributes",
        "elasticloadbalancing:DescribeTags",
        "ecs:DescribeTaskDefinition",
        "ecs:DeregisterTaskDefinition",
        "ecs:ListTaskDefinitions",
        "ecr:GetAuthorizationToken",
        "acm:RequestCertificate",
        "acm:ListCertificates",
        "logs:CreateLogDelivery",
        "logs:GetLogDelivery",
        "logs:UpdateLogDelivery",
        "logs:DeleteLogDelivery",
        "logs:ListLogDeliveries",
        "logs:PutResourcePolicy",
        "logs:DescribeResourcePolicies",
        "logs:DescribeLogGroups",
    }
)


def _render(path: pathlib.Path) -> str:
    """Substitutes the template's placeholders so the result parses as a policy document.

    Each placeholder becomes a value of the shape the real render produces, because a
    length measured against the literal ``$${name}`` is not the length IAM sees.

    Args:
      path: The ``.tftpl`` template to render.

    Returns:
      The rendered document as text.

    Raises:
      None.
    """
    substitutions = {
        "aws_region": "us-east-1",
        "project_name": "dat",
        "static_bucket_arn": "arn:aws:s3:::dat-prod-static-assets",
        "user_space_bucket_arn": "arn:aws:s3:::dat-prod-user-space",
        "portal_role_arn": "arn:aws:iam::696000197480:role/dat-portal-user-role",
        "lambda_artifacts_bucket_arn": "arn:aws:s3:::dat-lambda-artifacts-696000197480",
        "athena_admin_bucket_arn": "arn:aws:s3:::dat-prod-athena-admin",
        "deploy_role_arn": "arn:aws:iam::696000197480:role/dat-deploy-role",
        "oidc_provider_arn": "arn:aws:iam::696000197480:oidc-provider/token.actions.githubusercontent.com",
        "state_bucket": "dat-prod-tf-state",
        "state_lock_table": "dat-prod-tf-state-lock",
        "shared_space_bucket_arn": "arn:aws:s3:::dat-prod-shared-space",
        "archive_bucket_name": "dat-prod-archive",
        "trail_bucket_name": "dat-prod-archive-audit",
        "verification_trail_bucket_name": "dat-prod-archive-audit",
    }
    text = path.read_text()
    for name, value in substitutions.items():
        text = text.replace("${" + name + "}", value)
    return text


def _statements(path: pathlib.Path) -> list[dict]:
    """Parses a rendered policy template into its statement list.

    Args:
      path: The ``.tftpl`` template to read.

    Returns:
      Every statement in the document.

    Raises:
      None.
    """
    return json.loads(_render(path))["Statement"]


def _actions(statement: dict) -> list[str]:
    """Normalises a statement's ``Action`` to a list.

    Args:
      statement: One policy statement.

    Returns:
      The statement's actions, whether it declared one or many.

    Raises:
      None.
    """
    action = statement["Action"]
    return action if isinstance(action, list) else [action]


def _stripped_length(text: str) -> int:
    """Measures a policy the way IAM measures it: without whitespace.

    Args:
      text: A rendered policy document.

    Returns:
      The count of non-whitespace characters.

    Raises:
      None.
    """
    return len(re.sub(r"\s", "", text))


def test_the_inline_deploy_policy_stays_under_the_iam_aggregate() -> None:
    """The role's inline policy must fit the 10,240-character aggregate.

    It measured 9,256 when the platform grants were written, which is why they went into
    managed policies instead. Appending to the inline document is the tempting move and the
    one that fails at ``PutRolePolicy`` — after the plan is green.
    """
    length = _stripped_length(_render(INLINE_POLICY))
    assert length <= INLINE_AGGREGATE_LIMIT, (
        f"{INLINE_POLICY.name} renders to {length:,} non-whitespace characters against IAM's "
        f"{INLINE_AGGREGATE_LIMIT:,} aggregate for a role's inline policies. Put new grants in "
        "a customer-managed policy, which has its own separate budget."
    )


@pytest.mark.parametrize(
    "path",
    sorted(p for p in POLICY_DIR.glob("github-actions-deploy-*.json.tftpl")),
    ids=lambda p: p.name,
)
def test_every_managed_deploy_policy_stays_under_the_managed_limit(path: pathlib.Path) -> None:
    """Each customer-managed policy must fit its own 6,144-character budget.

    Enforced at ``CreatePolicy``, so a document over the line renders, validates and plans
    green and fails on the apply.

    Args:
      path: One deploy-role policy template.
    """
    length = _stripped_length(_render(path))
    assert length <= MANAGED_LIMIT, (
        f"{path.name} renders to {length:,} non-whitespace characters against IAM's "
        f"{MANAGED_LIMIT:,} limit for one customer-managed policy. Split it rather than "
        "trimming until it fits."
    )


@pytest.mark.parametrize("path", PLATFORM_POLICIES, ids=lambda p: p.name)
def test_a_wildcard_resource_holds_only_non_scopable_actions(path: pathlib.Path) -> None:
    """``Resource: "*"`` is for actions IAM defines no resource type for, and nothing else.

    A scopable action parked in a wildcard statement is a grant nobody narrowed, and it reads
    in a diff exactly like one that could not be.

    Args:
      path: One of the two platform policy templates.
    """
    for statement in _statements(path):
        if statement["Resource"] != "*":
            continue
        scopable = [a for a in _actions(statement) if a not in NON_SCOPABLE]
        assert not scopable, (
            f"{path.name} statement {statement['Sid']!r} grants {scopable} on Resource \"*\", "
            "but IAM accepts an ARN for each. Scope it, or measure it with "
            "simulate-custom-policy and add it to NON_SCOPABLE with the evidence."
        )


def test_a_scoped_statement_holds_no_non_scopable_action() -> None:
    """The other half: a non-scopable action under an ARN is a dead grant.

    It authorizes nothing and denies implicitly, so the symptom is a missing permission on an
    action the policy visibly grants — the slowest kind of IAM failure to read.
    """
    for path in PLATFORM_POLICIES:
        for statement in _statements(path):
            if statement["Resource"] == "*":
                continue
            dead = [a for a in _actions(statement) if a in NON_SCOPABLE]
            assert not dead, (
                f"{path.name} statement {statement['Sid']!r} scopes {dead} to an ARN, but IAM "
                "defines no resource type for them — the grant is an implicit deny."
            )


def test_every_non_scopable_action_is_actually_granted() -> None:
    """Guard the guard: ``NON_SCOPABLE`` must not rot into a list of actions nobody uses.

    Without this the set could accumulate entries long after the grant that needed them was
    removed, and a future wildcard would be waved through by a line that describes nothing.
    """
    granted = {
        action
        for path in PLATFORM_POLICIES
        for statement in _statements(path)
        for action in _actions(statement)
    }
    stale = sorted(NON_SCOPABLE - granted)
    assert not stale, (
        f"NON_SCOPABLE names {stale}, which the platform policies no longer grant. Delete the "
        "entries rather than leaving a set that permits a wildcard for an action nobody asks for."
    )


def test_pass_role_names_its_roles_and_its_service() -> None:
    """Every ``iam:PassRole`` names role ARNs and the one service they may be passed to.

    ``PassRole`` on ``"*"`` hands the deploy role the ability to give any role to any service,
    which is the privilege-escalation shape the whole scoping exercise exists to avoid. The
    four roles here go to three different services, so this is three statements rather than
    one — a single ``iam:PassedToService`` listing all three would let the flow-logs role be
    handed to ECS.
    """
    seen = 0
    for path in PLATFORM_POLICIES:
        for statement in _statements(path):
            if "iam:PassRole" not in _actions(statement):
                continue
            seen += 1
            assert statement["Resource"] != "*", f"{path.name}: iam:PassRole on Resource \"*\"."
            services = statement.get("Condition", {}).get("StringEquals", {}).get("iam:PassedToService")
            assert isinstance(services, str), (
                f"{path.name} statement {statement['Sid']!r} must carry exactly one "
                f"iam:PassedToService value, not {services!r}."
            )
    assert seen == 3, f"Expected three iam:PassRole statements across the platform policies, found {seen}."


@pytest.mark.parametrize("path", PLATFORM_POLICIES, ids=lambda p: p.name)
def test_a_policy_document_is_printable_ascii(path: pathlib.Path) -> None:
    """IAM rejects a policy document containing a non-ASCII character.

    Recorded because it has already cost an apply: a template carrying explanatory ``"//"``
    keys with em dashes in them was refused at ``CreatePolicy``, which neither ``tofu
    validate`` nor the plan can see. Prose belongs in the ``.tf`` beside the resource.

    Args:
      path: One of the two platform policy templates.
    """
    text = _render(path)
    offenders = sorted({c for c in text if not (32 <= ord(c) <= 126 or c in "\n\r\t")})
    assert not offenders, (
        f"{path.name} contains non-ASCII characters {offenders}. IAM refuses the document at "
        "CreatePolicy; move the prose into infra/modules/base/iam.tf."
    )
