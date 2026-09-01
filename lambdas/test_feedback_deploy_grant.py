"""The deploy role's feedback grant, checked against the resources it will have to create.

The grant lands in its own PR, ahead of the module — which means for one merge there is nothing
in the tree that uses it, and nothing that would go red if it were wrong. This file is what
stands in for that: it reads the policy as JSON and asserts the grant covers each resource family
the module is going to declare, by the NAME PATTERN the resource will actually carry.

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

    The patterns here are the ones ``infra/modules/feedback/locals.tf`` constructs. A grant that
    named ``feedback-requests`` rather than ``feedback-*`` would authorize the queue and not its
    dead-letter queue, and the apply would fail halfway through creating the pair.
    """
    statement = _statements()[sid]

    assert statement["Effect"] == "Allow"
    assert statement["Resource"] == resource, (
        f"{sid} is scoped to {statement['Resource']!r}, which does not cover the names the "
        f"feedback module constructs"
    )


def test_the_only_wildcards_are_the_two_that_cannot_be_scoped() -> None:
    """``Resource: "*"`` is for an action IAM defines no resource type for, and nothing else.

    Both wildcards here are inherited from the notifications grant, which measured them: an
    event-source mapping does not exist when ``CreateEventSourceMapping`` is called, so the
    statement is conditioned on the FUNCTION's ARN instead, and ``ListEventSourceMappings`` is a
    list over the account. A scopable action parked in a wildcard reads in a diff exactly like
    one that could not be.
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
