"""The deploy role's policies must fit IAM's budgets, and a wildcard must be forced.

Neither failure is visible in a plan. The aggregate inline limit, the managed-policy budgets, and
how the non-scopable action set was measured with ``simulate-custom-policy`` rather than assembled
by eye, are in ``infra/info/deploy-role-iam.md``.

Attributes:
  POLICY_DIR: Where every deploy-role policy template lives.
  INLINE_POLICY: The role's one inline policy, measured against the 10,240 aggregate.
  MANAGED_LIMIT: IAM's character budget for one customer-managed policy.
  INLINE_AGGREGATE_LIMIT: IAM's character budget for all of a role's inline policies together.
  MANAGED_POLICIES: Every template that becomes a customer-managed policy, derived from the
    directory rather than listed, so a new one is measured the day it lands.
  PLATFORM_POLICIES: The two container-platform templates, which the grant-coverage and registry
    assertions are about. The wildcard rules are NOT limited to these — see ``POLICIES``.
  POLICIES: Every deploy-role policy document the wildcard rules judge: the inline one and each
    managed one. The rules ran over ``PLATFORM_POLICIES`` alone until a plant showed the other
    fifteen documents were unread, so the population is asserted against the directory rather
    than trusted.
  TRUST_POLICY: The one template in the directory the wildcard rules exempt, because it grants no
    actions on resources at all. Named so the exemption is visible rather than silent.
  BASE_IAM: The Terraform that renders every template and attaches every managed policy.
  PLANNED_RESOURCES: The ARN each platform resource will have, keyed by what it is. The grant is
    written against these names, so a module that names one differently is denied. One row is an
    authorization-context ARN rather than a resource that will exist — it is labelled as such.
    The Lambda container image's registry is a SECOND repository behind the SAME two registry
    statements rather than a second pair of them, because that document has a few hundred
    characters of its budget left and a policy of its own would also spend an attachment against
    a ceiling of twenty. Its scoping was measured with ``simulate-custom-policy`` before the
    statement was written, and the two legs are worth stating exactly, because the loose version
    of the sentence is false. Against a policy carrying the image repository's pattern ALONE, all
    22 registry actions read back ``allowed`` for the image repository and ``implicitDeny`` for
    the SPA's, which is what shows the pattern narrows rather than merely matching. Under the
    document that ships BOTH read ``allowed`` — and they must, since the SPA's grant is what the
    container pipeline pushes with every day. A simulate also caps its policy input at 2,000
    characters, so the shipped document cannot be handed to one whole.
  NON_SCOPABLE: Every action IAM defines no resource type for, and therefore the only actions an
    unconditioned ``Resource: "*"`` statement may hold anywhere in ``POLICIES``.
  CONDITION_NARROWED_ACTIONS: The second and ONLY other way a wildcard is forced — condition key
    to the actions measured to populate it. A key absent from here cannot narrow anything this
    suite can vouch for, which is what stops the carve-out becoming an escape hatch: a condition
    true on every AWS call would otherwise buy a bare wildcard. An action paired with a key it
    never supplies is denied at runtime by the very condition meant to narrow it, naming neither.
  UNNARROWED_WILDCARD_FIXTURES: Synthetic statements holding the unnarrowed-wildcard rule to what
    it reports.
  UNPOPULATED_CONDITION_FIXTURES: The same for the condition-pairing rule.
  DEAD_SCOPED_FIXTURES: The same for the dead-grant rule.
  SERVICE_LINKED_ROLE_TRIGGERS: Resource types whose creation makes AWS create a service-linked
    role, mapped to the service name the grant must name.
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

MANAGED_POLICIES = tuple(sorted(POLICY_DIR.glob("github-actions-deploy-*.json.tftpl")))

#: The glob above ends in ``-``, which excludes ``github-actions-deploy.json.tftpl`` — the
#: INLINE document, and the largest. Any check about ARNs has to walk both, or it silently
#: skips the Glue, Athena, Cognito and state-lock grants entirely.
ARN_BEARING_POLICIES = (*MANAGED_POLICIES, INLINE_POLICY)

ACCOUNT_ID = "696000197480"

#: The one account field in these documents that is legitimately not this account. AWS owns
#: every managed prefix list (``arn:aws:ec2:<region>:aws:prefix-list/…``) and this account
#: declares none of its own, so the owner is PINNED rather than wildcarded and this set holds
#: what a pin may say instead of the account id — not a list of patterns exempt from checking.
FOREIGN_OWNERS = frozenset({"aws"})

PLATFORM_POLICIES = (
    POLICY_DIR / "github-actions-deploy-platform.json.tftpl",
    POLICY_DIR / "github-actions-deploy-platform-frontdoor.json.tftpl",
)

POLICIES = (INLINE_POLICY, *MANAGED_POLICIES)

TRUST_POLICY = POLICY_DIR / "github-actions-trust.json.tftpl"

BASE_IAM = ROOT / "infra" / "modules" / "base" / "iam.tf"
#: The attach ceiling is asserted in ``test_feedback_deploy_grant.py``, against the role's own
#: attachment count. Two constants for it used to sit here, unused and disagreeing with each
#: other (20 and 25); a number that asserts nothing is a number nobody notices is wrong.

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
    "Lambda image repository": "arn:aws:ecr:us-east-1:696000197480:repository/dat-prod-lambda",
    "Lambda image repository, kind-suffixed": (
        "arn:aws:ecr:us-east-1:696000197480:repository/dat-prod-lambda-image"
    ),
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
        "cognito-idp:CreateUserPool",
        "cognito-idp:DescribeUserPoolDomain",
        "lakeformation:PutDataLakeSettings",
        "lakeformation:GetDataLakeSettings",
        "lakeformation:GrantPermissions",
        "lakeformation:RevokePermissions",
        "lakeformation:ListPermissions",
        "lakeformation:RegisterResource",
        "lakeformation:DeregisterResource",
        "lakeformation:DescribeResource",
        "lakeformation:ListResources",
        "lakeformation:CreateLFTag",
        "lakeformation:GetLFTag",
        "lakeformation:UpdateLFTag",
        "lakeformation:DeleteLFTag",
        "lakeformation:ListLFTags",
        "states:ValidateStateMachineDefinition",
        "lambda:CreateEventSourceMapping",
        "lambda:ListEventSourceMappings",
        "cloudtrail:DescribeTrails",
        "cloudtrail:ListTrails",
    }
)

CONDITION_NARROWED_ACTIONS = {
    "lambda:FunctionArn": frozenset(
        {
            "lambda:CreateEventSourceMapping",
            "lambda:GetEventSourceMapping",
            "lambda:UpdateEventSourceMapping",
            "lambda:DeleteEventSourceMapping",
        }
    )
}


def _render(path: pathlib.Path) -> str:
    """Substitutes the template's placeholders so the result parses as a policy document.

    Each placeholder becomes a value of the shape the real render produces, because a
    length measured against the literal ``$${name}`` is not the length IAM sees.

    ``route53_zone_id`` matches ``PLANNED_RESOURCES["hosted zone"]``: the Route 53 grant is
    scoped to the one zone, so an id substituted here that differed from the one simulated
    against would make the scoping assertions pass on a document nothing is measured against.

    The substitution table is hand-maintained and nothing ties it to the templates, so a
    template naming a variable it does not carry is refused rather than rendered: the literal
    placeholder is shorter than the value it stands for, and a length measured from it is short
    by that difference on every occurrence.

    Args:
      path: The ``.tftpl`` template to render.

    Returns:
      The rendered document as text.

    Raises:
      AssertionError: When the template interpolates a variable this suite cannot render.
    """
    substitutions = {
        "aws_region": "us-east-1",
        "account_id": ACCOUNT_ID,
        "project_name": "dat",
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
    assert "${" not in text, (
        f"{path.name} interpolates a variable this suite does not render, so every length "
        "measured from it is short by the difference between the placeholder and the value. "
        "Add it to the substitution table with a value of the shape the real render produces."
    )
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


@pytest.mark.parametrize("path", MANAGED_POLICIES, ids=lambda p: p.name)
def test_every_managed_deploy_policy_stays_under_the_managed_limit(path: pathlib.Path) -> None:
    """Each customer-managed policy must fit its own 6,144-character budget.

    Enforced at ``CreatePolicy``, so a document over the line renders, validates and plans
    green and fails on the apply. The budget is not adjustable, so the answer to a policy over
    it is to split it, never to request a quota raise.

    Args:
      path: One deploy-role managed policy template.

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


@pytest.mark.parametrize("path", MANAGED_POLICIES, ids=lambda p: p.name)
def test_every_managed_deploy_policy_is_printable_ascii(path: pathlib.Path) -> None:
    """IAM rejects a non-ASCII character at ``CreatePolicy``, and nothing earlier sees it.

    An em dash pasted into a ``Sid`` survives ``tofu validate`` and the plan untouched. The rule
    was held for one policy of sixteen, which is the one that gets written most carefully.

    Args:
      path: One deploy-role managed policy template.

    Returns:
      None.

    Raises:
      AssertionError: When the rendered document carries a non-ASCII character.
    """
    rendered = _render(path)
    offenders = sorted({character for character in rendered if not character.isascii()})
    assert not offenders, (
        f"{path.name} carries the non-ASCII character(s) {offenders}. IAM rejects the document "
        "at CreatePolicy, and neither validate nor plan can see it."
    )


def test_every_attached_managed_policy_is_one_this_suite_measures() -> None:
    """The measured population and the wired one are two derived sets, never a list.

    The glob is what the budget assertion above walks; ``iam.tf`` is what IAM will actually be
    asked to create. A template wired as a managed policy but named outside the glob would ship
    unmeasured, which is the same silence the budget guard itself sat in.

    A block whose document comes from somewhere other than a ``policies/*.tftpl`` file is
    reported rather than skipped: it would otherwise escape both sets and the budget guard with
    it, which is the one way this comparison could agree while measuring nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When either set names a template the other does not, or when a policy
        block names no template.
    """
    blocks = re.findall(
        r'^resource "aws_iam_policy" "([A-Za-z0-9_-]+)" \{(.*?)^\}',
        BASE_IAM.read_text(),
        re.DOTALL | re.MULTILINE,
    )
    assert blocks, "Found no aws_iam_policy blocks — the parse went trivial rather than passing."

    wired = set()
    unresolved = []
    for name, body in blocks:
        match = re.search(r"policies/([A-Za-z0-9._\-]+\.tftpl)", body)
        if match:
            wired.add(match.group(1))
        else:
            unresolved.append(name)
    assert not unresolved, (
        f"{sorted(unresolved)} are customer-managed policies whose document comes from no "
        "policies/*.tftpl file, so nothing measures them against the 6,144 budget."
    )

    measured = {path.name for path in MANAGED_POLICIES}
    assert wired == measured, (
        f"{sorted(wired - measured)} are attached as customer-managed policies but fall outside "
        f"the glob this suite measures, and {sorted(measured - wired)} are measured but attached "
        "nowhere. Both halves must name the same templates."
    )


def _condition_keys(statement: dict) -> set[str]:
    """Collects every condition key a statement constrains, across all its operators.

    Args:
      statement: One policy statement.

    Returns:
      The condition keys named under any operator, empty when the statement has no Condition.

    Raises:
      None.
    """
    return {key for operands in statement.get("Condition", {}).values() for key in operands}


def _grants(statement: dict) -> bool:
    """Whether a statement is an Allow, which is the only kind these rules reason about.

    A ``Deny`` on ``Resource: "*"`` is a tightening, not a grant nobody narrowed, and running the
    scopability rules over one inverts their meaning — worse, the remedy those rules print would
    have the author add the action to ``NON_SCOPABLE``, silently weakening the rule for that
    action in every Allow statement in the tree.

    Args:
      statement: One policy statement.

    Returns:
      Whether the statement's Effect is Allow.

    Raises:
      None.
    """
    return statement.get("Effect") == "Allow"


def _unnarrowed_wildcard_actions(statement: dict) -> list[str]:
    """Scopable actions sitting in a wildcard statement that narrows them by nothing at all.

    The exemption is per ACTION, not per statement, and that is the whole of its safety. Exempting
    a whole statement because it carries some condition makes any condition an escape hatch, and
    the cheapest one narrows nothing at all: ``{"Bool": {"aws:SecureTransport": "true"}}`` is true
    on every AWS API call, and behind it an account-wide ``iam:PassRole`` on a bare wildcard read
    as forced with the whole suite green. So an action is excused only where a key the statement
    actually tests is recorded as narrowing THAT action; everything else in the statement is still
    judged. The pairing failure is ``_unpopulated_condition_actions``' business, because the two
    are different: this one is a grant nobody narrowed, that one denies at runtime.

    Args:
      statement: One policy statement.

    Returns:
      The actions IAM accepts an ARN for and no recorded condition key narrows, or empty when the
      statement is scoped or holds nothing unnarrowed.

    Raises:
      None.
    """
    if not _grants(statement) or "*" not in _resources(statement):
        return []
    narrowed: set[str] = set()
    for key in _condition_keys(statement) & CONDITION_NARROWED_ACTIONS.keys():
        narrowed |= CONDITION_NARROWED_ACTIONS[key]
    return [
        action
        for action in _actions(statement)
        if action not in NON_SCOPABLE and action not in narrowed
    ]


def _unpopulated_condition_actions(statement: dict) -> list[tuple[str, str]]:
    """Actions that do not populate a measured condition key their own statement tests.

    A condition on a key the caller never supplies fails CLOSED, and the refusal names neither
    the key nor the action — so this is the failure that reads as a missing grant on a statement
    that visibly grants it. Scoped statements are judged too, not only wildcards: the tempting
    tightening is to add a condition to an already-scoped statement, and an action supporting no
    condition keys at all is denied outright by it.

    Args:
      statement: One policy statement.

    Returns:
      ``(action, condition key)`` for each pairing the recorded measurement says cannot work.

    Raises:
      None.
    """
    if not _grants(statement):
        return []
    return [
        (action, key)
        for key in sorted(_condition_keys(statement) & CONDITION_NARROWED_ACTIONS.keys())
        for action in _actions(statement)
        if action not in CONDITION_NARROWED_ACTIONS[key]
    ]


def _dead_scoped_actions(statement: dict) -> list[str]:
    """Non-scopable actions sitting under an ARN, where they authorize nothing.

    Args:
      statement: One policy statement.

    Returns:
      The actions IAM defines no resource type for, or empty when the statement is a wildcard.

    Raises:
      None.
    """
    if not _grants(statement) or "*" in _resources(statement):
        return []
    return [action for action in _actions(statement) if action in NON_SCOPABLE]


def _label(path: pathlib.Path, statement: dict) -> str:
    """Names a statement in a failure message, whether or not it carries a ``Sid``.

    ``Sid`` is optional in IAM, and interpolating it directly turned an offending statement into a
    ``KeyError`` — which fails closed, but throws away the action list and the remedy along with
    the name, leaving the file as the only surviving clue.

    Args:
      path: The template the statement came from.
      statement: One policy statement.

    Returns:
      The file name and the statement's Sid, or a positional stand-in where it has none.

    Raises:
      None.
    """
    return f"{path.name} statement {statement.get('Sid', '<no Sid>')!r}"


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_a_wildcard_resource_holds_nothing_unnarrowed(path: pathlib.Path) -> None:
    """Every action on a ``Resource: "*"`` must be narrowed by something, or take no ARN at all.

    Not "only actions IAM defines no resource type for" — that was the rule before the
    event-source-mapping statements, and they falsify it: three of their actions DO accept an
    ARN and sit on a wildcard, narrowed by a measured condition key instead. A scopable action
    narrowed by neither is a grant nobody narrowed, and it reads in a diff exactly like one that
    could not be.

    Every deploy-role document is walked, the inline one included. Held for the two platform
    templates alone, this rule inspected two documents of seventeen: planting a member of
    ``NON_SCOPABLE`` into a plane policy, and into the inline document, left the suite green
    both times, while the same plant in a platform template reddened it.

    Args:
      path: One deploy-role policy template.

    Returns:
      None.

    Raises:
      AssertionError: When an unconditioned wildcard statement holds an action that accepts an ARN.
    """
    for statement in _statements(path):
        scopable = _unnarrowed_wildcard_actions(statement)
        assert not scopable, (
            f"{_label(path, statement)} grants {scopable} on Resource \"*\", "
            "but IAM accepts an ARN for each. Scope it, or measure it with "
            "simulate-custom-policy and add it to NON_SCOPABLE with the evidence."
        )


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_a_conditioned_wildcard_tests_a_key_its_actions_populate(path: pathlib.Path) -> None:
    """The other way a wildcard is forced: narrowed by a condition rather than by an ARN.

    Two statements are shaped this way, and both are right to be. Three of their four actions do
    accept an ``event-source-mapping`` ARN, but its UUID is generated at create time, so the only
    available pattern is the whole resource type — and ``lambda:FunctionArn`` already pins the
    function and, since a mapping shares its function's region, the region with it. That is
    everything the pattern could have added, which is why the condition stands in for it.
    Splitting the statement is not impossible, only pointless: it was built and measured, and
    costs a couple of hundred characters against roughly 3,600 of remaining budget.

    What can go wrong is the pairing: an action added here that does not populate the key is
    denied at runtime by the condition meant to protect it.

    Args:
      path: One deploy-role policy template.

    Returns:
      None.

    Raises:
      AssertionError: When a conditioned wildcard holds an action that never supplies the key.
    """
    for statement in _statements(path):
        unpopulated = _unpopulated_condition_actions(statement)
        assert not unpopulated, (
            f"{_label(path, statement)} narrows a wildcard with a condition "
            f"its own actions cannot satisfy: {unpopulated}. A condition on a key the caller "
            "does not populate fails closed, naming neither the key nor the action."
        )


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_every_statement_is_a_shape_these_rules_can_judge(path: pathlib.Path) -> None:
    """``NotAction`` and ``NotResource`` inverse a statement, and no rule here reasons about one.

    Each rule reads ``Action`` and ``Resource`` directly, so an inverted statement raises rather
    than reporting — the right polarity by luck, with none of the reason. Refusing the shape
    outright is the honest version: these documents use neither, and a rule that cannot judge a
    construct must not appear to have judged it.

    Args:
      path: One deploy-role policy template.

    Returns:
      None.

    Raises:
      AssertionError: When a statement inverts its actions or resources, or declares an Effect
        that is neither Allow nor Deny.
    """
    for statement in _statements(path):
        inverted = sorted({"NotAction", "NotResource"} & statement.keys())
        assert not inverted, (
            f"{_label(path, statement)} uses {inverted}, which inverts what it grants. No rule "
            "in this file reasons about that shape; rewrite it as Action/Resource."
        )
        assert statement.get("Effect") in {"Allow", "Deny"}, (
            f"{_label(path, statement)} declares Effect {statement.get('Effect')!r}. IAM accepts "
            "only Allow and Deny, and the scopability rules judge Allow alone."
        )


@pytest.mark.parametrize("path", POLICIES, ids=lambda p: p.name)
def test_a_scoped_statement_holds_no_non_scopable_action(path: pathlib.Path) -> None:
    """The other half: a non-scopable action under an ARN is a dead grant.

    It authorizes nothing and denies implicitly, so the symptom is a missing permission on an
    action the policy visibly grants — the slowest kind of IAM failure to read.

    Args:
      path: One deploy-role policy template.

    Returns:
      None.

    Raises:
      AssertionError: When a scoped statement holds an action IAM cannot scope.
    """
    for statement in _statements(path):
        dead = _dead_scoped_actions(statement)
        assert not dead, (
            f"{_label(path, statement)} scopes {dead} to an ARN, but IAM "
            "defines no resource type for them — the grant is an implicit deny."
        )


def test_the_wildcard_rules_walk_every_deploy_policy_template() -> None:
    """The population is a claim, and a glob that quietly stops matching makes it a false one.

    The rules above ran over two templates of seventeen for as long as they existed, and nothing
    said so — every one of them passed, on the two documents they read. So the file set is
    asserted against the directory: a new deploy policy is measured the day it lands, and the
    trust template is named as the one deliberate exclusion rather than silently absent.

    What this does NOT catch is a deleted managed template, because ``POLICIES`` is derived from
    the same glob and both sides of the count shrink together. That half belongs to
    ``test_every_attached_managed_policy_is_one_this_suite_measures``, which compares against
    ``iam.tf`` — an independent source. Said here because the reverse was written down first, and
    a guard vouched for by a reason it does not deliver is worse than one with no reason at all.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a template in the policy directory is neither measured nor the
        trust template.
    """
    on_disk = set(POLICY_DIR.glob("*.json.tftpl"))
    assert INLINE_POLICY in POLICIES, (
        "the inline deploy document is outside the measured population, which is where two of "
        "the wildcard rules' blind spot was. Asserted before the count below so this specific "
        "diagnosis wins over a bare arithmetic mismatch."
    )
    assert len(on_disk) == len(POLICIES) + 1, (
        f"the policy directory holds {len(on_disk)} templates against {len(POLICIES)} measured "
        "plus the trust template. Something was added outside the glob, or the inline or trust "
        "document was deleted. A DELETED MANAGED template is invisible here — both sides of this "
        "count come from the same directory, so they shrink together — and is caught instead by "
        "test_every_attached_managed_policy_is_one_this_suite_measures, against iam.tf."
    )
    unmeasured = sorted(path.name for path in on_disk - set(POLICIES) - {TRUST_POLICY})
    assert not unmeasured, (
        f"{unmeasured} are deploy policy templates the wildcard rules never read. Add them to "
        "POLICIES, or name the reason they are exempt the way the trust template is."
    )

#: Where the non-scopable rule is written in PROSE, and therefore where a count of the set would
#: rot. Derived by searching these trees for the rule's own vocabulary rather than listed, because
#: a list of sites is the thing that went stale three times running. Prose means ``.md`` and the
#: comments in ``.tf``; this file is deliberately outside it, since the set is defined here and a
#: number beside its definition can be read against it.
SCOPABILITY_PROSE_TREES = (
    ROOT / "infra",
    ROOT / "docs" / "decisions",
)

SCOPABILITY_PHRASES = ("non-scopable", "NON_SCOPABLE", "resource-scopable", "scopability")

#: Same line only — ``\s+`` spans newlines, which matched a loop counter followed by a variable
#: named ``actions`` and made the first version of this guard fire on Python it does not police.
COUNT_OF_ACTIONS = re.compile(r"\b\d+[ ]+actions\b")


def _scopability_prose() -> list[pathlib.Path]:
    """Every prose file that states the non-scopable rule.

    Args:
      None.

    Returns:
      The ``.md`` and ``.tf`` files whose text uses the rule's vocabulary.

    Raises:
      None.
    """
    return sorted(
        path
        for tree in SCOPABILITY_PROSE_TREES
        for path in tree.rglob("*")
        if path.suffix in {".md", ".tf"}
        and path.is_file()
        and ".terraform" not in path.parts
        and any(phrase in path.read_text() for phrase in SCOPABILITY_PHRASES)
    )


def test_no_prose_site_writes_down_a_count_of_the_non_scopable_set() -> None:
    """The set's SIZE belongs to the suite, never to prose that cannot be re-measured.

    A structural answer to a defect that recurred in three consecutive review rounds: the rule is
    written in several places, and each round found another copy stale. The concrete instance was
    a hardcoded count of the set — wrong by one the day it was written, wrong by twenty-two by the
    time it was found, and surviving in a second file after the first sweep deleted it from the
    first.

    A count is the one part of this rule that cannot be kept true by care, so it is the part
    forbidden outright; everything else the copies say is prose a reader can check. Matched over
    the whole FILE rather than the line, because the count and the rule it belongs to sit in the
    same paragraph and never on the same line — the line-scoped first draft passed both plants.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a prose site carries a count, or when the search finds nothing.
    """
    prose = _scopability_prose()
    assert len(prose) >= 5, (
        f"the scopability rule was found in only {len(prose)} prose files, which means the search "
        "stopped matching rather than the tree going quiet — a guard that finds nothing passes."
    )
    offenders = []
    for path in prose:
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if COUNT_OF_ACTIONS.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "these sites write down a count of the non-scopable set, which goes stale silently and "
        f"has twice: {offenders}. State the principle and let the suite hold the number."
    )


#: Synthetic statements for the four statement rules, each row a ``(label, statement, expected)``
#: triple. Running the rules over the shipped templates proves those templates pass; it cannot
#: prove a rule would still refuse anything, which is what a gate has to be held to. Half of these
#: rows assert SILENCE, because a rule that fires on a correct statement is the failure that gets
#: it deleted. Every statement carries an ``Effect``: the rules judge Allow alone, so a fixture
#: without one exercises the skip rather than the rule.
UNNARROWED_WILDCARD_FIXTURES = (
    (
        "a scopable action on a bare wildcard",
        {"Sid": "X", "Effect": "Allow", "Action": ["lambda:CreateFunction"], "Resource": "*"},
        ["lambda:CreateFunction"],
    ),
    (
        "a wildcard hidden in a one-element list",
        {"Sid": "X", "Effect": "Allow", "Action": "lambda:CreateFunction", "Resource": ["*"]},
        ["lambda:CreateFunction"],
    ),
    (
        "a scopable action beside a non-scopable one, reported alone",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["logs:DescribeLogGroups", "lambda:CreateFunction"],
            "Resource": "*",
        },
        ["lambda:CreateFunction"],
    ),
    (
        "a wildcard behind a condition that narrows nothing this suite measured",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["iam:PassRole"],
            "Resource": "*",
            "Condition": {"StringEquals": {"aws:RequestedRegion": "us-east-1"}},
        },
        ["iam:PassRole"],
    ),
    (
        "an unnarrowed action riding along in a statement a measured key DOES narrow",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:GetEventSourceMapping", "iam:PassRole"],
            "Resource": "*",
            "Condition": {"ArnLike": {"lambda:FunctionArn": "arn:aws:lambda:*:*:function:dat-*"}},
        },
        ["iam:PassRole"],
    ),
    (
        "a statement with no Sid is still judged",
        {"Effect": "Allow", "Action": ["lambda:CreateFunction"], "Resource": "*"},
        ["lambda:CreateFunction"],
    ),
    (
        "silence: a wildcard holding only non-scopable actions",
        {"Sid": "X", "Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": "*"},
        [],
    ),
    (
        "silence: a scopable action that carries an ARN",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:CreateFunction"],
            "Resource": "arn:aws:lambda:us-east-1:696000197480:function:dat-prod-api",
        },
        [],
    ),
    (
        "silence: a wildcard a MEASURED condition narrows, which the next rule judges",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:GetEventSourceMapping"],
            "Resource": "*",
            "Condition": {"ArnLike": {"lambda:FunctionArn": "arn:aws:lambda:*:*:function:dat-*"}},
        },
        [],
    ),
    (
        "silence: a Deny on a wildcard is a tightening, not a grant nobody narrowed",
        {"Sid": "X", "Effect": "Deny", "Action": ["iam:CreateRole"], "Resource": "*"},
        [],
    ),
)

#: The same for the condition rule. The failure it names is the one that reads as a missing
#: grant on a statement that visibly grants it.
UNPOPULATED_CONDITION_FIXTURES = (
    (
        "an action that never supplies the key the condition tests",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:ListEventSourceMappings"],
            "Resource": "*",
            "Condition": {"ArnLike": {"lambda:FunctionArn": "arn:aws:lambda:*:*:function:dat-*"}},
        },
        [("lambda:ListEventSourceMappings", "lambda:FunctionArn")],
    ),
    (
        "the same pairing on a SCOPED statement, which is the tempting tightening",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:ListTags"],
            "Resource": "arn:aws:lambda:us-east-1:696000197480:event-source-mapping:*",
            "Condition": {"ArnLike": {"lambda:FunctionArn": "arn:aws:lambda:*:*:function:dat-*"}},
        },
        [("lambda:ListTags", "lambda:FunctionArn")],
    ),
    (
        "silence: every action populates the key",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["lambda:CreateEventSourceMapping", "lambda:DeleteEventSourceMapping"],
            "Resource": "*",
            "Condition": {"ArnLike": {"lambda:FunctionArn": "arn:aws:lambda:*:*:function:dat-*"}},
        },
        [],
    ),
    (
        "silence: a key outside the recorded measurement, which the rule above refuses instead",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["iam:CreateServiceLinkedRole"],
            "Resource": "arn:aws:iam::*:role/aws-service-role/*",
            "Condition": {"StringEquals": {"iam:AWSServiceName": ["ecs.amazonaws.com"]}},
        },
        [],
    ),
)

#: And for the dead-grant rule, the mirror of the first.
DEAD_SCOPED_FIXTURES = (
    (
        "a non-scopable action pinned to an ARN",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["logs:DescribeLogGroups"],
            "Resource": "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api",
        },
        ["logs:DescribeLogGroups"],
    ),
    (
        "silence: the same action on a wildcard, where it belongs",
        {"Sid": "X", "Effect": "Allow", "Action": ["logs:DescribeLogGroups"], "Resource": "*"},
        [],
    ),
    (
        "silence: a scoped statement holding only scopable actions",
        {
            "Sid": "X",
            "Effect": "Allow",
            "Action": ["logs:PutRetentionPolicy"],
            "Resource": "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api",
        },
        [],
    ),
    (
        "silence: a Deny scoping a non-scopable action is not this rule's business",
        {
            "Sid": "X",
            "Effect": "Deny",
            "Action": ["logs:DescribeLogGroups"],
            "Resource": "arn:aws:logs:us-east-1:696000197480:log-group:/aws/lambda/dat-prod-api",
        },
        [],
    ),
)


@pytest.mark.parametrize(
    "label,statement,expected", UNNARROWED_WILDCARD_FIXTURES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_the_unnarrowed_wildcard_rule_fires_and_stays_quiet(
    label: str, statement: dict, expected: list[str]
) -> None:
    """Holds the rule to what it reports, not to an exit code.

    Args:
      label: What the fixture stands for, carried into the failure message.
      statement: The synthetic statement to judge.
      expected: The actions the rule must name, empty where it must say nothing.

    Returns:
      None.

    Raises:
      AssertionError: When the rule names something other than the fixture expects.
    """
    assert _unnarrowed_wildcard_actions(statement) == expected, label


@pytest.mark.parametrize(
    "label,statement,expected", UNPOPULATED_CONDITION_FIXTURES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_the_condition_rule_fires_and_stays_quiet(
    label: str, statement: dict, expected: list[tuple[str, str]]
) -> None:
    """Holds the condition rule to the exact action-and-key pairing it reports.

    Args:
      label: What the fixture stands for, carried into the failure message.
      statement: The synthetic statement to judge.
      expected: The pairings the rule must name, empty where it must say nothing.

    Returns:
      None.

    Raises:
      AssertionError: When the rule names something other than the fixture expects.
    """
    assert _unpopulated_condition_actions(statement) == expected, label


@pytest.mark.parametrize(
    "label,statement,expected", DEAD_SCOPED_FIXTURES, ids=lambda v: v if isinstance(v, str) else ""
)
def test_the_dead_grant_rule_fires_and_stays_quiet(
    label: str, statement: dict, expected: list[str]
) -> None:
    """Holds the dead-grant rule to what it reports.

    Args:
      label: What the fixture stands for, carried into the failure message.
      statement: The synthetic statement to judge.
      expected: The actions the rule must name, empty where it must say nothing.

    Returns:
      None.

    Raises:
      AssertionError: When the rule names something other than the fixture expects.
    """
    assert _dead_scoped_actions(statement) == expected, label


def test_the_fixture_corpus_carries_both_polarities() -> None:
    """Every rule owes a firing row and a silent one, or its corpus proves half a rule.

    A corpus that drifts to all-silent rows passes while the rule refuses nothing, and a corpus
    that drifts to all-firing rows says nothing about false positives — which are half of what
    gets a gate switched off.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any rule's fixtures are all of one polarity.
    """
    corpora = {
        name: value
        for name, value in sorted(globals().items())
        if name.endswith("_FIXTURES")
    }
    assert len(corpora) == 3, (
        f"expected one fixture corpus per statement rule, found {sorted(corpora)}. A hand-written "
        "list here would let a fifth corpus land with neither polarity checked."
    )
    for name, rows in corpora.items():
        polarities = {bool(expected) for _, _, expected in rows}
        assert polarities == {True, False}, (
            f"the {name} fixtures are all {'firing' if True in polarities else 'silent'} rows. "
            "A rule needs both: one polarity proves it refuses, the other that it does not "
            "refuse what it should allow."
        )


def _resources(statement: dict) -> list[str]:
    """Normalises a statement's ``Resource`` to a list.

    A statement may declare one resource or many, and until the Lambda image's registry joined
    the SPA's there were only single strings here. Three checks in this file decide whether a
    statement is a wildcard one by comparing that field, and a bare ``==`` against ``"*"`` reads
    a LIST holding ``"*"`` as scoped — so a wildcard hidden in a one-element list would skip the
    rule that exists to forbid it, and would read in a diff exactly like a narrowing.

    Args:
      statement: One policy statement.

    Returns:
      The statement's resources, whether it declared one or many.

    Raises:
      None.
    """
    resource = statement["Resource"]
    return resource if isinstance(resource, list) else [resource]


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
        if "*" not in _resources(statement)
        for pattern in _resources(statement)
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
      The set of ``resource "<type>"`` names across ``infra/``.

    Raises:
      None.
    """
    types: set[str] = set()
    for path in (ROOT / "infra").rglob("*.tf"):
        types.update(re.findall(r'^resource\s+"([a-z0-9_]+)"', path.read_text(), re.MULTILINE))
    return types


def test_every_resource_that_needs_a_service_linked_role_can_create_one() -> None:
    """The grant must name a service BEFORE the resource that triggers it is declared.

    This is the one class of deploy-role gap a plan cannot reveal: the creating API is never
    called, so the plan is green and the apply is a 403 whose message names neither the
    resource nor the missing service name. Tying the condition list to the declared resource
    types is what makes the next one fail here instead of on main.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When infra declares a trigger resource the role cannot create the role for.
    """
    document = json.loads(_render(POLICY_DIR / "github-actions-deploy-platform.json.tftpl"))
    granted: set[str] = set()
    for statement in document["Statement"]:
        actions = statement.get("Action", [])
        actions = [actions] if isinstance(actions, str) else actions
        if "iam:CreateServiceLinkedRole" in actions:
            granted.update(
                statement.get("Condition", {}).get("StringEquals", {}).get("iam:AWSServiceName", [])
            )

    declared = _declared_resource_types()
    assert declared, "Found no resource declarations — the parse went trivial rather than passing."
    for resource_type, service_name in SERVICE_LINKED_ROLE_TRIGGERS.items():
        if resource_type in declared:
            assert service_name in granted, (
                f"infra declares {resource_type}, whose creation makes AWS create a "
                f"service-linked role, but the deploy role may not create one for "
                f"{service_name}. This applies green at plan and 403s at apply."
            )


def _registry_statements() -> dict[tuple[str, str], list[str]]:
    """Finds every repository-scoped statement in BOTH platform documents, by its content.

    DERIVED FROM THE DOCUMENTS, never from a list of names, and that is the difference between a
    guard and a pair of guards. A hand-written tuple of ``Sid``s constrains the statements it
    names and says nothing about a THIRD one — so a new registry statement, which is exactly what
    a pull path would add, could grant ``repository/*`` and leave every test here green. A tuple
    that was emptied or shortened does the same silently, because an empty parametrize is a skip
    rather than a failure.

    BOTH documents are walked, not only the one holding the grants today. The registry statements
    are in the platform document, which has the least budget left of the two, so the natural home
    for the next registry grant is the document a one-file derivation could not see.

    Args:
      None.

    Returns:
      ``(document name, Sid)`` to resource patterns, for every statement whose resources are all
      ECR repository ARNs. Keyed by both, because a ``Sid`` is unique within a document rather
      than across them.

    Raises:
      AssertionError: When no such statement is found anywhere. A derived set that came back
        empty must not read as "nothing to check".
    """
    found = {
        (document.name, statement["Sid"]): _resources(statement)
        for document in PLATFORM_POLICIES
        for statement in _statements(document)
        if _resources(statement)
        and all(resource.startswith("arn:aws:ecr:") for resource in _resources(statement))
    }
    assert found, (
        "no repository-scoped statement found in either platform document. The registry grants "
        "are what the tests below are about, and a derived set that comes back empty would make "
        "every one of them pass without checking anything."
    )
    return found


#: The statements that must reach BOTH repositories, as opposed to merely being narrow. Named
#: because it is a claim about these two specifically: they are the create-and-push pair the SPA's
#: pipeline and the Lambda image's share. A statement added later — a pull path scoped to one
#: repository, say — is correctly narrow and correctly NOT here, and the narrowing test covers it
#: without this one demanding it be widened.
BOTH_REPOSITORY_STATEMENTS = ("PlatformRegistryManage", "PlatformRegistryPush")


def test_the_both_repository_statements_are_still_the_pair_this_file_names() -> None:
    """The named pair must exist, and must still be repository-scoped statements.

    Without this, trimming ``BOTH_REPOSITORY_STATEMENTS`` — the obvious response to the test
    below failing on a correctly-narrow new statement — silently removes a grant's only
    coverage. Measured: dropping one entry and then deleting the SPA's pattern from both shipped
    statements left the whole suite green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the pair has been shortened or renamed away.
    """
    named = {sid for (_, sid) in _registry_statements()}
    missing = [sid for sid in BOTH_REPOSITORY_STATEMENTS if sid not in named]
    assert not missing, (
        f"{missing} are named as the statements that must reach both repositories, but no "
        "platform document holds them. Either they were renamed, or this list was trimmed to "
        "silence a failure — and trimming it removes a grant's only coverage."
    )
    assert len(BOTH_REPOSITORY_STATEMENTS) == 2, (
        "the create-and-push pair is two statements. A shorter list here is a grant nothing "
        "checks reaches the repositories it is for."
    )


@pytest.mark.parametrize("sid", BOTH_REPOSITORY_STATEMENTS)
def test_the_registry_grants_reach_both_repositories(sid: str) -> None:
    """The create-and-push pair must cover the Lambda image's repository and the SPA's.

    The Lambda image rides these two statements rather than getting a pair of its own, so the
    thing that can go wrong is a pattern that stops matching one of the two while the document
    still renders, plans and applies. IAM matches ARNs literally, so a repository renamed on one
    side of that pattern is a grant that authorizes nothing, and the symptom is a `docker push`
    denied for a reason the policy visibly appears to allow.

    The SPA leg is asserted for the reason the trust template is asserted whole elsewhere: a
    change that edits a statement needs its own baseline, or "the existing grant is untouched"
    has nothing to compare against.

    Args:
      sid: The registry statement under test.

    Returns:
      None.

    Raises:
      AssertionError: When either repository is unmatched.
    """
    matches = [
        patterns for (_, found), patterns in _registry_statements().items() if found == sid
    ]
    assert len(matches) == 1, (
        f"expected exactly one registry statement named {sid!r} across the platform documents, "
        f"found {len(matches)}."
    )
    for label in (
        "ECR repository",
        "Lambda image repository",
        "Lambda image repository, kind-suffixed",
    ):
        arn = PLANNED_RESOURCES[label]
        assert any(_iam_match(pattern, arn) for pattern in matches[0]), (
            f"{sid} does not authorize {label} ({arn}). Its patterns are {matches[0]}."
        )


@pytest.mark.parametrize(
    "key", sorted(_registry_statements()), ids=lambda k: f"{k[0]}:{k[1]}"
)
def test_the_registry_grants_narrow_rather_than_merely_match(key: tuple[str, str]) -> None:
    """A registry statement must REFUSE a repository outside the two it is for.

    This is the negative control, and without it the test above is close to tautological: a
    pattern of ``*`` matches every ARN handed to it, so a statement widened to the whole registry
    would satisfy every positive assertion here while granting the deploy role push access to
    repositories nobody has reviewed. The pair mirrors how the non-scopable set was measured —
    the ``allowed`` leg alone proves nothing, and the refusal is what makes it evidence.

    It runs over EVERY repository-scoped statement, including ones this file does not name, which
    is the half of the guard that survives the arc adding a pull path.

    TWO strangers, and the second is the one that matters. A name inside the project prefix
    catches a widening to ``dat-*``; it does not catch one to ``*-lambda*``, which reaches every
    account's Lambda image repository and reads almost identical in a diff. Measured: that
    widening passed with one stranger.

    Args:
      key: The document name and ``Sid`` of the statement under test.

    Returns:
      None.

    Raises:
      AssertionError: When an unrelated repository ARN matches.
    """
    document, sid = key
    patterns = _registry_statements()[key]
    for stranger in (
        "arn:aws:ecr:us-east-1:696000197480:repository/dat-prod-unreviewed",
        "arn:aws:ecr:us-east-1:696000197480:repository/otherproject-prod-lambda",
    ):
        matched = [p for p in patterns if _iam_match(p, stranger)]
        assert not matched, (
            f"{document}:{sid} authorizes {stranger} through {matched}. The registry grants are "
            "scoped to this project's SPA repository and its Lambda image's; a pattern reaching "
            "anything else is a widening nobody asked for."
        )



#: The four registry actions AWS requires of the principal that CREATES an image-backed Lambda.
#: Documented under "Amazon ECR permissions" in the Lambda container-image guide, whose worked
#: example is exactly these four scoped to a repository ARN. Three of them were already here for
#: pushing an image; `GetDownloadUrlForLayer` arrived with the container fleet, and its absence
#: fails at CreateFunction after a green plan — so it is pinned rather than left to look like an
#: unused read beside BatchGetImage.
IMAGE_CREATOR_ECR_ACTIONS = frozenset(
    {
        "ecr:GetRepositoryPolicy",
        "ecr:SetRepositoryPolicy",
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
    }
)


def test_the_role_holds_every_ecr_action_creating_an_image_lambda_needs() -> None:
    """All four, on the Lambda image's repository, wherever in the document they live.

    Asserted against the union of the statements that reach that repository rather than against
    one Sid: the four are split across two statements today, and which statement holds which is
    not the claim — that the role holds all four on that repository is.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When any of the four is missing, or no statement reaches the repository.
    """
    document = json.loads(_render(POLICY_DIR / "github-actions-deploy-platform.json.tftpl"))

    held = set()
    reaching = 0
    for statement in document["Statement"]:
        resources = statement.get("Resource", [])
        resources = [resources] if isinstance(resources, str) else resources
        if not any("-lambda" in resource for resource in resources):
            continue
        reaching += 1
        actions = statement.get("Action", [])
        held |= set(actions if isinstance(actions, list) else [actions])

    assert reaching >= 2, (
        "no statement in the platform policy reaches the Lambda image repository; the assertion "
        "below would pass on an empty set"
    )
    missing = sorted(IMAGE_CREATOR_ECR_ACTIONS - held)
    assert missing == [], (
        f"the deploy role is missing {missing} on the Lambda image repository. AWS requires all "
        f"of {sorted(IMAGE_CREATOR_ECR_ACTIONS)} on the principal that calls CreateFunction with "
        "an image; the failure is at apply, after a green plan."
    )


def _arns(path: pathlib.Path) -> list[str]:
    """Collects every ARN in a rendered document, wherever it sits.

    Walks the parsed document rather than the ``Resource`` field, because two ARNs live in
    ``Condition`` values instead — the ``ArnLike`` on ``lambda:FunctionArn`` in the feedback
    and notifications event-source-mapping statements. A collector reading ``Resource`` alone
    reports those two clean forever.

    Args:
      path: The ``.tftpl`` template to read.

    Returns:
      Every string beginning ``arn:`` anywhere in the document, in document order.

    Raises:
      None.
    """
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, str):
            if node.startswith("arn:"):
                found.append(node)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value)

    walk(json.loads(_render(path)))
    return found


@pytest.mark.parametrize("path", ARN_BEARING_POLICIES, ids=lambda p: p.name)
def test_no_deploy_grant_wildcards_the_account(path: pathlib.Path) -> None:
    """An ARN in a deploy grant names one account, never any.

    An account wildcard is not inert for every service. Where a resource carries its own
    policy — SQS, ECR, ``lambda:InvokeFunction``, EventBridge, and the Glue catalog under Lake
    Formation — a foreign account holding a resource whose name matches the pattern and whose
    resource policy admits this role is reachable through the wildcard. For EC2, Logs, Lambda
    configuration, Step Functions and Pipes the request is evaluated in the owner's account
    with nothing to say yes, so the wildcard authorized nothing there; it is pinned anyway,
    because a reader cannot tell the two apart in a diff.

    The empty account field is a THIRD case and a legal one: S3 and Route 53 ARNs carry no
    account, and API Gateway's carry none in this document. Only ``*`` is refused.

    Args:
      path: The template to check.

    Returns:
      None.

    Raises:
      AssertionError: When an ARN's account field is ``*``.
    """
    offenders = [
        arn
        for arn in _arns(path)
        if len(arn.split(":")) > 4 and arn.split(":")[4] == "*"
    ]
    assert not offenders, (
        f"{path.name} wildcards the account on {len(offenders)} ARN(s): {offenders}. A grant "
        "names one account. Pin it to ${account_id}, or — if AWS owns the resource — to the "
        f"owner, as the prefix-list ARNs do: {sorted(FOREIGN_OWNERS)}."
    )


@pytest.mark.parametrize("path", ARN_BEARING_POLICIES, ids=lambda p: p.name)
def test_every_deploy_document_carries_arns_to_check(path: pathlib.Path) -> None:
    """The wildcard check must have seen something in every document.

    ``all()`` over an empty collection is true, so a collector that silently found nothing
    passes the test above in exactly the way a clean document does. This catches a collector
    that went dark, not the loss of one ARN — every document here carries several. The
    aggregate floor is asserted separately, over the whole population, in
    ``test_the_account_pin_is_what_makes_a_foreign_resource_denied``; between them a collector
    that half-works is caught too.

    Args:
      path: The template to check.

    Returns:
      None.

    Raises:
      AssertionError: When a document yields no ARNs at all.
    """
    assert _arns(path), (
        f"{path.name} yielded no ARNs, so the account-wildcard check over it asserted nothing. "
        "Either the document changed shape or the collector stopped reading it."
    )


def test_the_account_pin_is_what_makes_a_foreign_resource_denied() -> None:
    """A pinned pattern must refuse the same resource in another account.

    ``test_the_grant_covers_every_resource_the_platform_will_create`` matches every planned ARN
    against the patterns, and every planned ARN is in this account — so it passed before the
    pin and would pass again the day someone reverted it. This is the direction that would not:
    the identical resource, one account over, matched by nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a foreign-account ARN is still matched by some pattern.
    """
    patterns = [
        arn for path in ARN_BEARING_POLICIES for arn in _arns(path) if arn.startswith("arn:")
    ]
    intruder = "111122223333"
    assert intruder != ACCOUNT_ID
    reachable = []
    for name, arn in PLANNED_RESOURCES.items():
        fields = arn.split(":")
        if len(fields) <= 4 or fields[4] != ACCOUNT_ID:
            continue  # No account to swap: S3, Route 53, API Gateway.
        fields[4] = intruder
        foreign = ":".join(fields)
        if any(_iam_match(pattern, foreign) for pattern in patterns):
            reachable.append(name)
    assert not reachable, (
        f"a grant still reaches these resources in account {intruder}: {reachable}. The account "
        "pin is what stops it, so this failing means a pattern went back to ':*:'."
    )
    assert len(patterns) > 100, (
        f"only {len(patterns)} patterns collected; the sweep above proved nothing about a "
        "population this small."
    )


def test_the_terraform_passes_the_real_account_id() -> None:
    """Every rendered template must receive ``account_id``, and it must be the caller's.

    Nothing offline can check this: ``_render`` substitutes the suite's own literal, and
    ``PLANNED_RESOURCES`` carries the same one, so a template rendered with the WRONG account
    would satisfy every other test here. ``templatefile()`` errors on a key a template uses and
    the map omits, so an omission fails ``tofu validate`` — a wrong value does not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a template map omits ``account_id``, or the root passes something
        other than the caller identity.
    """
    iam = BASE_IAM.read_text()
    maps = re.findall(
        r'templatefile\("\$\{path\.module\}/policies/(github-actions-deploy[^"]*'
        r'\.json\.tftpl)", \{(.*?)\n  \}\)',
        iam,
        re.DOTALL,
    )
    rendered = {name for name, _ in maps}
    expected = {path.name for path in ARN_BEARING_POLICIES}
    assert rendered == expected, (
        f"iam.tf renders {sorted(rendered)} but this suite checks {sorted(expected)}; a "
        "template nobody renders is dead, and one nobody checks is unguarded."
    )
    # `tofu fmt` aligns the `=` in these maps, so the assignment is matched with the run of
    # spaces left free rather than as a literal.
    passes_account = re.compile(r"\n\s*account_id\s*=\s*var\.account_id\s*\n")
    missing = [name for name, body in maps if not passes_account.search(body + "\n")]
    assert not missing, (
        f"these templatefile maps do not pass account_id: {missing}. Every ARN in them renders "
        "with an empty account field, which is a valid ARN that matches nothing."
    )
    root = (ROOT / "infra" / "main.tf").read_text()
    # Scoped to module "base"'s own block. Eighteen modules take an account_id from the same
    # data source, so a search of the whole file reads it as satisfied while the one call this
    # test is about passes a literal.
    block = re.search(r'\nmodule "base" \{\n(.*?)\n\}\n', root, re.DOTALL)
    assert block, "infra/main.tf no longer declares module \"base\" in the expected shape"
    passes_root = re.compile(
        r"\n\s*account_id\s*=\s*data\.aws_caller_identity\.current\.account_id\s*(?:\n|$)"
    )
    assert passes_root.search(block.group(1)), (
        "infra/main.tf must pass module.base its account_id from aws_caller_identity; a "
        "hard-coded or variable-supplied id can disagree with the account being applied to."
    )
