"""The file-ops role can list its OWN plan prefix, which is what makes absence answerable.

``focommon.plan._read`` treats ``NoSuchKey``/``404`` as "no plan yet". S3 only answers ``NoSuchKey``
for a missing object when the caller can list the bucket; without that it answers ``AccessDenied``,
and this role had no list grant at all. The plan never exists on a first submission, so every
folder copy, move and delete failed with *"the working list for that could not be read back."*
Measured live: the plane's first execution failed at ``InspectSource`` on exactly that denial.

**The grant is conditioned, and the condition is why there is a probe in the code.** A ``GetObject``
request carries no ``s3:prefix``, so a conditioned list grant does nothing for the read — measured,
``implicitDeny`` with no prefix supplied and ``allowed`` with one. The unconditioned form would fix
the read directly and was rejected: this role already holds ``GetObject`` on
``${admin_bucket_arn}/shared-spaces/*``, so a bucket-wide list would let it enumerate every shared
space's registry entry and read every roster — the disclosure the project declines by not
publishing a shared-space directory at all. So the grant stays inside the plan prefix, and
``plan._absent`` asks the question with a LIST, which does carry the prefix.

That split is what keeps the fix from failing open. A denial is never read as absence on its own;
only a list that comes back without the key is, so a real denial on an object that exists still
raises rather than planning over a run already copying.

Attributes:
  EXECUTION_POLICY: The file-ops execution role's policy.
  MODULE_LOCALS: Where Terraform's own value for the plan prefix is set.
  LIFECYCLE_RULE: The admin bucket's expiry rule, which carries the prefix a third time.
  ADMIN_BUCKET_ARN: The template variable naming the admin bucket, unexpanded.
  PLAN_PREFIX_VAR: The template variable naming the plan prefix, unexpanded.
  LIST_ACTION: The action whose presence decides whether a missing object can be shown missing.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXECUTION_POLICY = ROOT / "infra" / "modules" / "file-ops" / "policies" / "execution.json.tftpl"
MODULE_LOCALS = ROOT / "infra" / "modules" / "file-ops" / "locals.tf"
LIFECYCLE_RULE = ROOT / "infra" / "modules" / "analytics" / "s3.tf"
ADMIN_BUCKET_ARN = "@{admin_bucket_arn}"
PLAN_PREFIX_VAR = "@{plan_prefix}"
LIST_ACTION = "s3:ListBucket"

sys.path.insert(0, str(ROOT / "lambdas" / "file-ops-common"))


def _statements() -> list[dict]:
    """Every statement in the execution policy, with ``${`` rewritten so JSON parsing survives.

    Args:
      None.

    Returns:
      The statement list.

    Raises:
      None.
    """
    return json.loads(EXECUTION_POLICY.read_text().replace("${", "@{"))["Statement"]


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


def _list_grants() -> list[dict]:
    """Every Allow of ``s3:ListBucket`` naming the admin bucket.

    Args:
      None.

    Returns:
      The matching statements.

    Raises:
      None.
    """
    return [
        statement
        for statement in _statements()
        if statement.get("Effect") == "Allow"
        and LIST_ACTION in _as_list(statement.get("Action", []))
        and ADMIN_BUCKET_ARN in _as_list(statement.get("Resource", []))
    ]


def test_the_role_can_list_the_admin_bucket_and_only_inside_the_plan_prefix() -> None:
    """The grant exists, names the bucket itself, and is confined by an ``s3:prefix`` condition.

    Each half fails differently. Without the statement, ``plan._absent`` cannot run and every
    first-time folder operation fails. Named on ``.../*`` instead of the bucket, ``ListBucket``
    matches nothing — IAM accepts the policy and the behaviour is unchanged. Unconditioned, the
    role can enumerate ``shared-spaces/`` and read every roster it finds there, which is a
    disclosure this project declines to publish deliberately.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the grant is missing, scoped to objects rather than the bucket, or not
        confined to the plan prefix.
    """
    granting = _list_grants()

    assert granting, (
        f"no statement allows {LIST_ACTION} on {ADMIN_BUCKET_ARN}. focommon.plan._absent then "
        "cannot answer, a missing plan stays indistinguishable from a denial, and every "
        "first-time folder operation fails as 'the working list for that could not be read back'"
    )
    for statement in granting:
        prefixes = _as_list(
            statement.get("Condition", {}).get("StringLike", {}).get("s3:prefix", [])
        )
        assert prefixes, (
            f"{statement.get('Sid')!r} allows {LIST_ACTION} on the whole admin bucket. This role "
            f"reads {ADMIN_BUCKET_ARN}/shared-spaces/*, so a bucket-wide list hands it every "
            "shared space's name and then every roster"
        )
        assert all(prefix.startswith(f"{PLAN_PREFIX_VAR}/") for prefix in prefixes), (
            f"{statement.get('Sid')!r} admits prefixes outside the plan prefix: {prefixes}"
        )


def test_the_list_condition_names_the_same_prefix_the_plan_statements_do() -> None:
    """The condition and the object grants are pinned to one template variable, not two spellings.

    ``plan._absent`` lists exactly the key ``plan._read`` failed to get. If the condition were
    written against a literal, or against a second variable, renaming the plan prefix would move
    the objects and leave the list behind — and the failure returns in its original form, with
    this file still green because each half is individually well-formed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If no object statement uses the plan-prefix variable, or if the list
        condition is written against anything else.
    """
    object_resources = [
        resource
        for statement in _statements()
        if statement.get("Effect") == "Allow"
        for resource in _as_list(statement.get("Resource", []))
        if resource.startswith(f"{ADMIN_BUCKET_ARN}/{PLAN_PREFIX_VAR}/")
    ]
    assert object_resources, (
        f"no statement grants an object action under {ADMIN_BUCKET_ARN}/{PLAN_PREFIX_VAR}/ — the "
        "comparison below would hold vacuously against a prefix nothing else uses"
    )

    for statement in _list_grants():
        for prefix in _as_list(
            statement.get("Condition", {}).get("StringLike", {}).get("s3:prefix", [])
        ):
            assert prefix.startswith(f"{PLAN_PREFIX_VAR}/"), (
                f"{statement.get('Sid')!r} conditions on {prefix!r}, which is not the "
                f"{PLAN_PREFIX_VAR} the object grants use — a rename moves one and not the other"
            )


def test_the_plan_prefix_agrees_across_python_terraform_and_the_lifecycle_rule() -> None:
    """Three literals, one value, and until now nothing compared them.

    ``focommon.config.PLAN_PREFIX`` says it is mirrored in the module's locals and in the admin
    bucket's expiry rule and that a test holds all three equal. No test did. It matters more since
    the list grant landed: the condition is rendered from Terraform's value and the key the probe
    sends is built from Python's, so a divergence stops the condition matching the very list that
    decides whether a plan is absent — and it does so without either side looking wrong.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the three do not agree, or if either Terraform literal cannot be found —
        an unparsed file would otherwise make the comparison vacuous.
    """
    from focommon import config

    terraform = re.search(r'plan_prefix\s*=\s*"([^"]+)"', MODULE_LOCALS.read_text())
    lifecycle = re.search(
        r'id\s*=\s*"expire-file-ops-plans".*?prefix\s*=\s*"([^"]+)"',
        LIFECYCLE_RULE.read_text(),
        re.DOTALL,
    )

    assert terraform, f"no plan_prefix local in {MODULE_LOCALS.name}"
    assert lifecycle, f"no expire-file-ops-plans rule prefix in {LIFECYCLE_RULE.name}"
    assert terraform.group(1) == config.PLAN_PREFIX, (
        f"Terraform grants on {terraform.group(1)!r} and Python writes under "
        f"{config.PLAN_PREFIX!r}"
    )
    assert lifecycle.group(1) == f"{config.PLAN_PREFIX}/", (
        f"the expiry rule covers {lifecycle.group(1)!r}, not {config.PLAN_PREFIX + '/'!r} — plans "
        "are either never expired or an unrelated prefix is"
    )
