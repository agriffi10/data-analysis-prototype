"""The deploy role's feedback grant, checked against the resources it will have to create.

The grant lands in its own PR, ahead of the module — which means for one merge there is nothing
in the tree that uses it, and nothing that would go red if it were wrong. This file is what
stands in for that: it reads the policy as JSON and asserts the grant covers each resource family
the module is going to declare, by the name pattern each resource is INTENDED to carry, and joins
the policy to the Terraform resource that renders it.

**What it cannot do, said plainly:** the intended names are literals here, so this file cannot tell
you the module actually constructs them. That join arrives with the module, in a test over its
``locals.tf``. Until then a shared misunderstanding about a name passes every gate in the repo.

Both budgets are asserted here rather than left to the apply. IAM enforces them at
``CreatePolicy`` and ``AttachRolePolicy``, on a document that rendered, validated and planned
green — the failure arrives after every gate has passed.

Attributes:
  POLICY: The feedback grant's template.
  MANAGED_LIMIT: IAM's per-document budget for a customer-managed policy, in non-whitespace
    characters.
  MAX_ATTACHED_MANAGED_POLICIES: How many managed policies one role may carry. The feedback grant
    is one more, so the count is asserted rather than assumed to be far from the ceiling.
  SUBSTITUTIONS: What ``templatefile()`` will put in, so the document can be parsed as JSON.
"""

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"
POLICY = INFRA / "modules" / "base" / "policies" / "github-actions-deploy-feedback.json.tftpl"

MANAGED_LIMIT = 6_144
MAX_ATTACHED_MANAGED_POLICIES = 20

SUBSTITUTIONS = {"aws_region": "us-east-1", "project_name": "dat"}


def _rendered() -> str:
    """Renders the template the way ``templatefile()`` will.

    Args:
      None.

    Returns:
      The rendered document.

    Raises:
      AssertionError: If the template still carries an unsubstituted variable, which would mean
        the root passes a name this file does not know about.
    """
    text = POLICY.read_text(encoding="utf-8")
    for name, value in SUBSTITUTIONS.items():
        text = text.replace("${" + name + "}", value)
    assert "${" not in text, f"{POLICY.name} interpolates a variable this test does not render"
    return text


def _statements() -> dict[str, dict]:
    """The rendered policy's statements, keyed by Sid.

    Args:
      None.

    Returns:
      Sid to statement.

    Raises:
      None.
    """
    return {s["Sid"]: s for s in json.loads(_rendered())["Statement"]}


def test_the_document_is_printable_ascii_and_fits_the_managed_budget() -> None:
    """Both are enforced at ``CreatePolicy``, on a document that already planned green.

    An IAM policy must be printable ASCII — an em dash in a comment key is rejected there and is
    invisible to ``tofu validate`` and to the plan.
    """
    rendered = _rendered()

    assert rendered.isascii(), (
        f"{POLICY.name} carries a non-ASCII character; IAM rejects the document at CreatePolicy "
        "and neither validate nor plan can see it"
    )
    length = len(re.sub(r"\s", "", rendered))
    assert length <= MANAGED_LIMIT, (
        f"{POLICY.name} renders to {length:,} non-whitespace characters against IAM's "
        f"{MANAGED_LIMIT:,} budget for one customer-managed policy"
    )


def test_the_policy_resource_renders_THIS_template_and_not_a_neighbours() -> None:
    """The join nothing else makes, and the likeliest way a copied block goes wrong.

    ``iam.tf`` names the template as a STRING, and every other check here reads the ``.tftpl``
    from disk — so a ``deploy_feedback`` policy pointing at the notifications template satisfies
    all of them. Measured: with that one word changed, `pytest lambdas/`, `tofu validate`,
    `tofu fmt -check` and `validate_docs.py` are all green on a branch that grants the feedback
    families nothing at all, and the symptom is `sqs:CreateQueue` denied in a later apply.
    """
    iam = (INFRA / "modules" / "base" / "iam.tf").read_text(encoding="utf-8")
    block = iam[iam.index('resource "aws_iam_policy" "deploy_feedback"') :]
    block = block[: block.index("\n}\n")]

    assert POLICY.name in block, (
        f"aws_iam_policy.deploy_feedback does not render {POLICY.name}; it renders "
        f"{[line.strip() for line in block.splitlines() if 'templatefile' in line]}"
    )
    assert '"${var.project_name}-deploy-feedback"' in block, (
        "the policy is not named for the family it grants, so two policies could collide"
    )


def test_the_grant_is_gated_on_the_self_grant_propagation_sleep() -> None:
    """The deploy role writes the permission this same apply then uses.

    Every control-plane grant beside this one carries the same edge. Without it the attachment
    can land before the role's own ``iam:CreatePolicy`` has propagated, which fails the FIRST
    apply and is invisible in a plan.
    """
    iam = (INFRA / "modules" / "base" / "iam.tf").read_text(encoding="utf-8")
    block = iam[iam.index('resource "aws_iam_policy" "deploy_feedback"') :]
    block = block[: block.index("\n}\n")]

    assert "depends_on = [time_sleep.wait_for_self_grant]" in block


#: Every statement's Sid to the exact action set it must grant. Asserted WHOLE rather than by
#: spot-checking a few names: a dropped action is a resource family that cannot be created, and
#: it reads in a diff as a shorter list rather than as a missing capability. Measured against
#: the notifications grant, which provisions the same families and is proven by live applies.
EXPECTED_ACTIONS = {
    # The FR-006 cold-start probe, scoped to this one function. Separate from the manage
    # statement beside it so the sweep in test_invoke_grant_population.py reads one
    # purpose per statement.
    "FeedbackProbeInvoke": {
        "lambda:InvokeFunction",
    },
    "FeedbackQueuesManage": {
        "sqs:CreateQueue",
        "sqs:DeleteQueue",
        "sqs:GetQueueUrl",
        "sqs:GetQueueAttributes",
        "sqs:SetQueueAttributes",
        "sqs:ListQueueTags",
        "sqs:TagQueue",
        "sqs:UntagQueue",
        "sqs:AddPermission",
        "sqs:RemovePermission",
    },
    "FeedbackWriterLambdaManage": {
        "lambda:CreateFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetFunctionConcurrency",
        "lambda:GetRuntimeManagementConfig",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:PublishVersion",
        "lambda:DeleteFunction",
        "lambda:ListVersionsByFunction",
        "lambda:GetPolicy",
        "lambda:AddPermission",
        "lambda:RemovePermission",
        "lambda:TagResource",
        "lambda:UntagResource",
        "lambda:ListTags",
    },
    "FeedbackEventSourceMappingManage": {
        "lambda:CreateEventSourceMapping",
        "lambda:GetEventSourceMapping",
        "lambda:UpdateEventSourceMapping",
        "lambda:DeleteEventSourceMapping",
    },
    "FeedbackEventSourceMappingList": {"lambda:ListEventSourceMappings"},
    "FeedbackEventSourceMappingTags": {"lambda:ListTags"},
    "FeedbackRolesManage": {
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:ListRoleTags",
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:UpdateAssumeRolePolicy",
        "iam:PassRole",
    },
    "FeedbackLogs": {
        "logs:CreateLogGroup",
        "logs:DeleteLogGroup",
        "logs:PutRetentionPolicy",
        "logs:DeleteRetentionPolicy",
        "logs:ListTagsForResource",
        "logs:TagResource",
        "logs:UntagResource",
    },
}


def test_every_statement_grants_exactly_the_actions_its_family_needs() -> None:
    """Set equality per statement, and the statement SET itself.

    Equality both ways is the point. A missing action is a resource the apply cannot create; an
    extra one is a grant nobody narrowed, and the two are indistinguishable in a diff of a
    copied block.
    """
    statements = _statements()

    assert set(statements) == set(EXPECTED_ACTIONS), (
        "the statement set moved; a whole family can vanish without any other check noticing"
    )
    for sid, expected in EXPECTED_ACTIONS.items():
        actions = statements[sid]["Action"]
        granted = set(actions if isinstance(actions, list) else [actions])
        assert granted == expected, (
            f"{sid} grants {sorted(granted ^ expected)} differently from what the feedback "
            f"module needs"
        )


def test_the_log_group_grant_carries_BOTH_arn_forms() -> None:
    """``logs:ListTagsForResource`` authorizes against the bare ARN; the others use the ``:*`` one.

    Named in ``infra/info/deploy-role-iam.md`` as a recurring trap, and it is a single-line
    deletion away — with only one form, an apply fails on a tag read of a log group the same
    statement visibly grants.
    """
    resources = _statements()["FeedbackLogs"]["Resource"]

    assert resources == [
        "arn:aws:logs:us-east-1:*:log-group:/aws/lambda/dat-*-feedback-writer",
        "arn:aws:logs:us-east-1:*:log-group:/aws/lambda/dat-*-feedback-writer:*",
    ], f"the log-group grant carries {resources}, not both ARN forms"


def test_the_role_stays_under_the_attached_managed_policy_ceiling() -> None:
    """One more managed policy, and the ceiling is a hard one.

    Counted from the filesystem rather than from a number in a doc: the README's own count had
    already rotted by one before this grant was added, which is why it no longer states one.
    """
    iam = (INFRA / "modules" / "base" / "iam.tf").read_text(encoding="utf-8")
    attached = re.findall(
        r'^resource "aws_iam_role_policy_attachment" "([a-z_]+)"', iam, re.MULTILINE
    )

    assert "deploy_feedback" in attached, "the feedback policy is declared but never attached"
    assert len(attached) <= MAX_ATTACHED_MANAGED_POLICIES, (
        f"the deploy role would carry {len(attached)} managed policies against IAM's ceiling of "
        f"{MAX_ATTACHED_MANAGED_POLICIES}; AttachRolePolicy fails after a green plan"
    )


@pytest.mark.parametrize(
    ("sid", "resource"),
    [
        ("FeedbackQueuesManage", "arn:aws:sqs:us-east-1:*:dat-*-feedback-*"),
        (
            "FeedbackWriterLambdaManage",
            "arn:aws:lambda:us-east-1:*:function:dat-*-feedback-writer",
        ),
        ("FeedbackRolesManage", "arn:aws:iam::*:role/dat-*-feedback-*"),
    ],
)
def test_each_family_is_scoped_to_the_name_the_module_will_use(sid: str, resource: str) -> None:
    """The grant is written before the resources, so nothing else pins the two together.

    **These literals are the names the module is INTENDED to construct, and until that module
    exists they are pinned to nothing but themselves.** Both halves of the pair are written here,
    so a typo in one is caught and a shared misunderstanding is not — the real join lands with
    ``infra/modules/feedback/locals.tf``, where a test reads each constructed name and matches it
    against these patterns. Measured, before that test existed: renaming the writer function to
    ``…-feedback-writer-fn`` — which neither the function ARN nor the log-group ARN matches, so
    ``CreateFunction`` would be denied at apply — left this whole suite green.

    What it does catch today is the commoner error: a grant that named ``feedback-requests``
    rather than ``feedback-*`` would authorize the queue and not its dead-letter queue, and the
    apply would fail halfway through creating the pair.
    """
    statement = _statements()[sid]

    assert statement["Effect"] == "Allow"
    assert statement["Resource"] == resource, (
        f"{sid} is scoped to {statement['Resource']!r}, which does not cover the names the "
        f"feedback module constructs"
    )


def test_the_only_wildcards_are_the_two_that_must_be_wildcards() -> None:
    """``Resource: "*"`` is forced here two different ways, and neither is laziness.

    Both wildcards are inherited from the notifications grant, which measured them.
    ``ListEventSourceMappings`` is the unnarrowable one: IAM defines no resource type and no
    condition key for it, so a bare wildcard is all there is. The Manage statement is the other
    kind — Get, Update and Delete DO accept an ``event-source-mapping`` ARN, but its UUID does not
    exist when the policy is written, and ``lambda:FunctionArn`` pins the function and with it the
    region, which is everything that ARN pattern could have added. So it narrows by condition.

    A scopable action parked in a wildcard reads in a diff exactly like one that could not be;
    which of the two applies to every deploy document is ``test_deploy_platform_policies.py``.
    """
    wildcards = {sid for sid, s in _statements().items() if s["Resource"] == "*"}

    assert wildcards == {
        "FeedbackEventSourceMappingManage",
        "FeedbackEventSourceMappingList",
    }, f"an unexpected statement reaches a wildcard: {sorted(wildcards)}"
    condition = _statements()["FeedbackEventSourceMappingManage"]["Condition"]
    assert condition["ArnLike"]["lambda:FunctionArn"].endswith("-feedback-writer"), (
        "the mapping grant is unconditioned, so it would authorize a mapping onto any function"
    )
