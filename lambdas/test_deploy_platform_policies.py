"""The deploy role's policies must fit IAM's budgets, and a wildcard must be forced.

Two different failures live here, and neither is visible in a plan.

**The budgets.** IAM's 10,240-character limit is the AGGREGATE of a role's inline policies,
not a per-policy allowance, and ``github-actions-deploy.json.tftpl`` already renders to 9,289.
A customer-managed policy has its own separate 6,144-character budget, and a role may carry at
most twenty of them. All three ceilings are enforced at ``CreatePolicy``/``PutRolePolicy``/
``AttachRolePolicy`` — an apply-time ``LimitExceeded`` on a document that rendered, validated
and planned green. The container platform's grants are two managed policies rather than one for
exactly this reason, and the next person to extend either one should discover the ceiling here
rather than in a deploy.

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
  BASE_IAM: The Terraform that attaches every one of them to the deploy role.
  DEFAULT_ATTACHED_MANAGED_POLICIES: The default quota for managed policies per role.
  MAX_ATTACHED_MANAGED_POLICIES: The highest that quota can be raised to.
  PLANNED_RESOURCES: The ARN each platform resource will have, keyed by what it is. The grant is
    written against these names, so a module that names one differently is denied.
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

BASE_IAM = ROOT / "infra" / "modules" / "base" / "iam.tf"
DEFAULT_ATTACHED_MANAGED_POLICIES = 20
MAX_ATTACHED_MANAGED_POLICIES = 25

PLANNED_RESOURCES = {
    "VPC": "arn:aws:ec2:us-east-1:696000197480:vpc/vpc-0abc",
    "subnet": "arn:aws:ec2:us-east-1:696000197480:subnet/subnet-0abc",
    "route table": "arn:aws:ec2:us-east-1:696000197480:route-table/rtb-0abc",
    "internet gateway": "arn:aws:ec2:us-east-1:696000197480:internet-gateway/igw-0abc",
    "security group": "arn:aws:ec2:us-east-1:696000197480:security-group/sg-0abc",
    "VPC endpoint": "arn:aws:ec2:us-east-1:696000197480:vpc-endpoint/vpce-0abc",
    "flow log": "arn:aws:ec2:us-east-1:696000197480:vpc-flow-log/fl-0abc",
    "load balancer": (
        "arn:aws:elasticloadbalancing:us-east-1:696000197480:loadbalancer/app/dat-prod-spa/50dc6c495c0c9188"
    ),
    "load balancer, kind-suffixed": (
        "arn:aws:elasticloadbalancing:us-east-1:696000197480"
        ":loadbalancer/app/dat-prod-spa-alb/50dc6c495c0c9188"
    ),
    "target group": (
        "arn:aws:elasticloadbalancing:us-east-1:696000197480:targetgroup/dat-prod-spa-tg/73e2d6bc24d8a067"
    ),
    "listener": (
        "arn:aws:elasticloadbalancing:us-east-1:696000197480:listener/app/dat-prod-spa"
        "/50dc6c495c0c9188/f2f7dc8efc522ab2"
    ),
    "ECS cluster": "arn:aws:ecs:us-east-1:696000197480:cluster/dat-prod-spa",
    "ECS cluster, kind-suffixed": "arn:aws:ecs:us-east-1:696000197480:cluster/dat-prod-spa-cluster",
    "ECS service": "arn:aws:ecs:us-east-1:696000197480:service/dat-prod-spa/dat-prod-spa",
    "ECS service, kind-suffixed": (
        "arn:aws:ecs:us-east-1:696000197480:service/dat-prod-spa-cluster/dat-prod-spa-service"
    ),
    "task definition": "arn:aws:ecs:us-east-1:696000197480:task-definition/dat-prod-spa:1",
    # The BARE FAMILY, with no revision, and it is not a duplicate of the row above. A
    # RegisterTaskDefinition CREATES revision 1, so at the moment of the call there is no
    # revision for an ARN to carry and the authorising resource is the family alone. Measured
    # against the live role: the family read implicitDeny while `:1` read allowed, so the grant
    # covered every case except the one an apply actually makes.
    "task definition, unregistered family": (
        "arn:aws:ecs:us-east-1:696000197480:task-definition/dat-prod-spa"
    ),
    "task definition, kind-suffixed": (
        "arn:aws:ecs:us-east-1:696000197480:task-definition/dat-prod-spa-task:1"
    ),
    "ECR repository": "arn:aws:ecr:us-east-1:696000197480:repository/dat-prod-spa",
    "ECR repository, kind-suffixed": "arn:aws:ecr:us-east-1:696000197480:repository/dat-prod-spa-repo",
    "API function": "arn:aws:lambda:us-east-1:696000197480:function:dat-prod-api",
    "API function role": "arn:aws:iam::696000197480:role/dat-prod-api-role",
    "SPA task role": "arn:aws:iam::696000197480:role/dat-prod-spa-task-role",
    "SPA task execution role": "arn:aws:iam::696000197480:role/dat-prod-spa-task-execution-role",
    "flow-logs role": "arn:aws:iam::696000197480:role/dat-prod-vpc-flow-logs-role",
    "API function log group": (
        "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api"
    ),
    "API access log group": (
        "arn:aws:logs:us-east-1:696000197480:log-group:/aws/apigateway/dat-prod-api"
    ),
    "flow-log group": "arn:aws:logs:us-east-1:696000197480:log-group:/aws/vpc/dat-prod-flow-logs",
    "ECS task log group": "arn:aws:logs:us-east-1:696000197480:log-group:/ecs/dat-prod-spa",
    "ECS task log group, kind-suffixed": (
        "arn:aws:logs:us-east-1:696000197480:log-group:/ecs/dat-prod-spa-task"
    ),
    "certificate": (
        "arn:aws:acm:us-east-1:696000197480:certificate/8d0e0a1e-0000-0000-0000-000000000000"
    ),
    "hosted zone": "arn:aws:route53:::hostedzone/Z0123456789ABCDEFGHIJ",
    "DNS change": "arn:aws:route53:::change/C0123456789ABC",
    "HTTP API": "arn:aws:apigateway:us-east-1::/apis/abcdef1234",
    "API custom domain": "arn:aws:apigateway:us-east-1::/domainnames/api.example.com",
}

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

    ``route53_zone_id`` matches ``PLANNED_RESOURCES["hosted zone"]``: the Route 53 grant is
    scoped to the one zone, so an id substituted here that differed from the one simulated
    against would make the scoping assertions pass on a document nothing is measured against.

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
        "route53_zone_id": "Z0123456789ABCDEFGHIJ",
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


def test_the_deploy_role_carries_exactly_one_inline_policy() -> None:
    """The 10,240 budget is an AGGREGATE, and the test below measures one document.

    That is sound only while there is exactly one inline policy on this role. A second one would
    make the measurement below an understatement, and the overflow would land at
    ``PutRolePolicy`` on whichever of the two Terraform happened to write second.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the deploy role gains a second inline policy.
    """
    inline = re.findall(
        r'resource\s+"aws_iam_role_policy"\s+"([^"]+)"[^{]*\{(?:[^{}]|\{[^{}]*\})*?'
        r'role\s*=\s*aws_iam_role\.github_actions_deploy',
        BASE_IAM.read_text(),
    )
    assert inline == ["github_actions_deploy"], (
        f"Expected exactly one inline policy on the deploy role, found {inline}. The 10,240-character "
        "limit is the SUM of them, so a second one makes the length guard below understate the total."
    )


def test_the_inline_deploy_policy_stays_under_the_iam_aggregate() -> None:
    """The role's inline policy must fit the 10,240-character aggregate.

    It rendered to 9,289 when the platform grants were written — the template measures 9,256
    before substitution, and IAM sees the rendered document — which is why those grants went
    into managed policies instead. Appending to the inline document is the tempting move and the
    one that fails at ``PutRolePolicy`` — after the plan is green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the rendered inline policy exceeds the aggregate.
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

    Returns:
      None.

    Raises:
      AssertionError: When the rendered document exceeds the managed-policy limit.
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

    Returns:
      None.

    Raises:
      AssertionError: When a wildcard statement holds an action that accepts an ARN.
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

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a scoped statement holds an action IAM cannot scope.
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

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the set names an action the platform policies no longer grant.
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

    Returns:
      None.

    Raises:
      AssertionError: When the rendered document holds a character IAM will refuse.
    """
    text = _render(path)
    offenders = sorted({c for c in text if not (32 <= ord(c) <= 126 or c in "\n\r\t")})
    assert not offenders, (
        f"{path.name} contains non-ASCII characters {offenders}. IAM refuses the document at "
        "CreatePolicy; move the prose into infra/modules/base/iam.tf."
    )


def _iam_match(pattern: str, arn: str) -> bool:
    """Applies IAM's wildcard semantics to one resource pattern.

    IAM's ``*`` matches any run of characters including ``/`` and ``:``, which is why an ECS
    service ARN of ``service/{cluster}/{service}`` matches a pattern naming one segment. ``?``
    matches exactly one character.

    Args:
      pattern: The ``Resource`` entry from a statement.
      arn: A concrete ARN to test it against.

    Returns:
      Whether IAM would consider the pattern to cover the ARN.

    Raises:
      None.
    """
    expression = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(expression, arn) is not None


def test_the_grant_covers_every_resource_the_platform_will_create() -> None:
    """Each planned resource must be matched by a SCOPED pattern, not merely by a wildcard.

    The wildcard statements match everything by construction, so counting them would make this
    pass for a name nothing actually grants — the shape of a test that passes by finding
    nothing. Only the ARN-scoped statements count here.

    This is the half of the grant no offline check could otherwise reach: a name pattern that
    matches nothing applies green, plans green, and denies on first use.

    **What it does NOT do is bind the modules.** This table and the patterns it checks were
    written together, so on its own the pair is self-consistent and says nothing about what
    Terraform will actually name. What makes it useful is that it carries each resource under
    BOTH naming shapes the repo uses — the bare ``dat-prod-spa`` a Lambda-style name would take
    and the ``dat-prod-spa-cluster`` kind-suffixed form every other plane uses — so a pattern
    that admits only one of them fails here rather than on the apply that uses the other.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a planned resource is covered by no scoped pattern.
    """
    scoped = [
        (statement["Sid"], pattern)
        for path in PLATFORM_POLICIES
        for statement in _statements(path)
        if statement["Resource"] != "*"
        for pattern in (
            statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        )
    ]
    assert scoped, "No scoped statements found — the templates did not parse."

    unmatched = sorted(
        label
        for label, arn in PLANNED_RESOURCES.items()
        if not any(_iam_match(pattern, arn) for _, pattern in scoped)
    )
    assert not unmatched, (
        f"No scoped grant matches {unmatched}. A pattern that matches nothing applies green and "
        "denies on first use — check the ARN format for that resource type, not just the name."
    )


def test_the_deploy_role_stays_under_the_attached_managed_policy_ceiling() -> None:
    """A role carries twenty managed policies by default, and this one is filling up.

    The same class of apply-time ``LimitExceeded`` as the character budgets above, and the one
    with the least warning: every per-plane grant since the inline policy filled up has taken a
    managed policy, so the count only ever rises.

    Twenty is the DEFAULT quota, not a hard limit — it is raisable to twenty-five in Service
    Quotas, and requests up to that maximum are auto-approved. So the message this fails with
    offers the raise as well as consolidation, because sending the next person to consolidate a
    quota they could simply raise is its own kind of wrong answer.

    The count is file-scoped: attachments declared outside ``infra/modules/base/iam.tf``, or made
    out of band in the console, are invisible to it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the deploy role's attachments reach the default quota.
    """
    attachments = re.findall(
        r'resource\s+"aws_iam_role_policy_attachment"\s+"([^"]+)"', BASE_IAM.read_text()
    )
    assert len(attachments) > 1, "Found no attachments — the parse went trivial rather than passing."
    assert len(attachments) <= DEFAULT_ATTACHED_MANAGED_POLICIES, (
        f"The deploy role carries {len(attachments)} attached managed policies against a default "
        f"quota of {DEFAULT_ATTACHED_MANAGED_POLICIES}: {sorted(attachments)}. Either raise the "
        f"quota in Service Quotas (IAM -> 'Managed policies per role', auto-approved up to "
        f"{MAX_ATTACHED_MANAGED_POLICIES}) and raise this bound with it, or consolidate."
    )

# Resource types whose creation makes AWS create a SERVICE-LINKED ROLE in the account, mapped
# to the service name `iam:CreateServiceLinkedRole` is conditioned on. A missing entry is a 403
# at apply — "Caller does not have permissions to create a Service Linked Role" — naming neither
# the resource nor the service, and it is invisible at plan because the plan does not call the
# creating API. Measured: a regional API Gateway custom domain does this, which AWS documents
# ("the service-linked role is required to attach your ACM certificate to your Regional
# endpoint") and which this repo discovered by reddening main instead.
SERVICE_LINKED_ROLE_TRIGGERS = {
    "aws_apigatewayv2_domain_name": "ops.apigateway.amazonaws.com",
    "aws_ecs_service": "ecs.amazonaws.com",
    "aws_lb": "elasticloadbalancing.amazonaws.com",
}


def _declared_resource_types() -> set[str]:
    """Every resource type the IaC tree declares.

    Args:
      None.

    Returns:
      The set of `resource "<type>"` names across infra/.

    Raises:
      None.
    """
    types: set[str] = set()
    for path in (ROOT / "infra").rglob("*.tf"):
        types.update(re.findall(r'^resource\s+"([a-z0-9_]+)"', path.read_text(), re.MULTILINE))
    return types


def test_every_resource_that_needs_a_service_linked_role_can_create_one():
    """The grant must name a service BEFORE the resource that triggers it is declared.

    This is the one class of deploy-role gap a plan cannot reveal: the creating API is never
    called, so the plan is green and the apply is a 403 whose message names neither the
    resource nor the missing service name. Tying the condition list to the declared resource
    types is what makes the next one fail here instead of on main.
    """
    document = json.loads(_render(POLICY_DIR / "github-actions-deploy-platform.json.tftpl"))
    granted: set[str] = set()
    for statement in document["Statement"]:
        actions = statement.get("Action", [])
        actions = [actions] if isinstance(actions, str) else actions
        if "iam:CreateServiceLinkedRole" in actions:
            granted.update(
                statement.get("Condition", {})
                .get("StringEquals", {})
                .get("iam:AWSServiceName", [])
            )

    declared = _declared_resource_types()
    for resource_type, service_name in SERVICE_LINKED_ROLE_TRIGGERS.items():
        if resource_type in declared:
            assert service_name in granted, (
                f"infra declares {resource_type}, whose creation makes AWS create a "
                f"service-linked role, but the deploy role may not create one for "
                f"{service_name}. This applies green at plan and 403s at apply."
            )


def test_the_platform_grant_pause_sits_after_the_attachments_and_re_fires_on_change():
    """Both halves are load-bearing, and each looks correct alone while protecting nothing.

    A `time_sleep` placed BEFORE the attachments is done long before the grant it is meant to
    guard is written. One carrying no `triggers` is created once and never returns, so it
    protects the first apply and no later one — which is how a grant written at 14:56:08.95
    came to be refused at 14:56:10.67, on a module whose sleep had existed for months.

    Neither failure is visible in a plan: the pause is present either way, and the race it
    loses is decided inside AWS.
    """
    text = BASE_IAM.read_text()
    start = text.index('resource "time_sleep" "wait_for_platform_grant"')
    block = text[start : text.index("\n}", start)]

    # The triggers MAP, not the block. Three substring searches over the whole resource pass
    # while the map holds a static nonce and the two policy references sit in a comment beside
    # it — measured, that mutation survived. Same trap as the attachment check below, one field
    # up: closing it there and leaving it open here is how a guard half-works.
    triggers = re.search(r"triggers\s*=\s*\{(.*?)\n  \}", block, re.DOTALL)
    assert triggers, (
        "the pause must carry a triggers map keyed to the policy bodies — without one it is "
        "created once and gives a later grant change zero delay"
    )
    keyed_on = set(re.findall(r"=\s*(aws_iam_policy\.\w+\.policy)\s*$", triggers.group(1), re.MULTILINE))
    assert keyed_on == {
        "aws_iam_policy.deploy_platform.policy",
        "aws_iam_policy.deploy_platform_frontdoor.policy",
    }, (
        f"the triggers map is keyed on {sorted(keyed_on)} — it must key on both policy BODIES. "
        "An ARN never changes when a grant is widened, so keying on one is a pause that never "
        "returns"
    )

    # Anchored to whole entries, not substrings: `…deploy_platform` occurs inside
    # `…deploy_platform_frontdoor`, so a containment check is satisfied by the wrong line and
    # stays green with one of the two dependencies deleted. Measured — that mutation survived.
    depended_on = set(re.findall(r"\b(aws_iam_role_policy_attachment\.\w+)\b", block))
    assert depended_on == {
        "aws_iam_role_policy_attachment.deploy_platform",
        "aws_iam_role_policy_attachment.deploy_platform_frontdoor",
    }, (
        f"the pause depends on {sorted(depended_on)} — it must wait for BOTH platform "
        "attachments, or it completes before the grant it exists to guard is written"
    )

    duration = re.search(r'create_duration\s*=\s*"(\d+)s"', block)
    assert duration and int(duration.group(1)) >= 30, (
        "the pause must be a real floor on eventual consistency"
    )
