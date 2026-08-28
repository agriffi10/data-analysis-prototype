"""The deploy role's policies must fit IAM's budgets, and a wildcard must be forced.

Neither failure is visible in a plan. The aggregate inline limit, the managed-policy budgets, and
how the non-scopable action set was measured with ``simulate-custom-policy`` rather than assembled
by eye, are in ``infra/info/deploy-role-iam.md``.

Attributes:
  POLICY_DIR: Where every deploy-role policy template lives.
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
    # An AUTHORIZATION-CONTEXT ARN, not a resource that will exist — the created task
    # definition is `:1`. It is here because `RegisterTaskDefinition` requires a
    # `task-definition` resource type (the Service Reference marks it required) while the ARN
    # ECS passes at register time is undocumented: the revision does not exist yet. So the
    # grant is written to cover BOTH forms, which one pattern does because IAM's `*` spans `:`.
    # This row is what fails if that pattern is ever narrowed back to a revision-suffixed one.
    #
    # Note what is NOT claimed. A policy simulate answers "does this pattern match this string",
    # never "what resource does the service pass" — so no measurement here establishes which
    # form ECS uses, and none is needed.
    "task definition, register-time authorization context": (
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
        # The one action a `docker push` needs that takes no resource type at all: the AWS
        # Service Reference lists NO resources for it, and the pair that says so was measured —
        # `implicitDeny` scoped to the repository ARN, `allowed` on `"*"`. Its five layer and
        # manifest siblings are all scoped to the repository, which is why this sits alone.
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
