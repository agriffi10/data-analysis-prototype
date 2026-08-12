"""The user-space bucket policy's principal allowlist is a registry, and it must not rot.

SPEC-164 FR-006. ``user-space-bucket-policy.json.tftpl`` is a ``"Principal": "*"`` Deny on
``GetObject``/``PutObject``/``DeleteObject``/``ListBucket``, conditioned ``StringNotLike
aws:PrincipalArn`` against a hand-maintained list of every principal permitted to touch
Bucket 1. **An explicit resource-policy Deny beats an identity-policy Allow**, so a control
plane whose execution role is not on that list is denied by the bucket no matter how correct
its own grants are.

The failure that makes this worth a test rather than a comment is its SHAPE. Nothing about
the omission is visible in a plan, in a render, or in any unit test of the policy that
grants the access — it appears on the first real run, and for a send it appears
*asymmetrically*: every ``space`` recipient succeeds, because the shared-space bucket has no
bucket policy at all, and every ``user`` recipient fails ``AccessDenied``. A half-working
feature reads like a code bug, and the search starts in the wrong file. #241 records that
this has already bitten the repo three times.

So the list is pinned three ways, and the three catch different mistakes:

* ``test_every_allowlisted_principal_is_actually_passed_in`` catches a placeholder that
  ``modules/data/s3.tf`` never fills — it renders as the literal string ``${foo}``, which
  matches no principal and silently denies one.
* ``test_every_principal_passed_in_reaches_the_allowlist`` catches the reverse and is the
  half a new plane actually trips: the variable and the ``templatefile()`` argument added,
  the allowlist line forgotten.
* ``test_the_expected_principals_are_all_present`` is the registry itself. Removing a plane
  from the bucket policy should take a deliberate edit in two places, not one.

Attributes:
  BUCKET_POLICY: The rendered-at-apply bucket-policy template.
  DATA_S3: The Terraform that renders it, and the only place its arguments are supplied.
  EXPECTED_PRINCIPALS: Every principal the allowlist must name, by placeholder. A new plane
    that reads or writes Bucket 1 adds itself here AND to the template; a plane that does
    neither is not listed at all.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUCKET_POLICY = ROOT / "infra" / "modules" / "data" / "policies" / "user-space-bucket-policy.json.tftpl"
DATA_S3 = ROOT / "infra" / "modules" / "data" / "s3.tf"

EXPECTED_PRINCIPALS = {
    "portal_role_arn",
    "deploy_role_arn",
    "lf_registration_role_arn",
    "shared_space_orchestrator_role_arn",
    "notifications_writer_role_arn",
    "table_builder_execution_role_arn",
    "table_share_execution_role_arn",
    "data_quality_execution_role_arn",
    "file_send_execution_role_arn",
    "archive_execution_role_arn",
    "user_directory_build_role_arn",
}


def _allowlist() -> list[str]:
    """Returns the allowlist's raw entries, placeholders included.

    Parses the template as JSON with ``${`` rewritten to ``@{`` — the same trick
    ``test_feature_flags_config.py`` uses — so the assertion is against the real document
    structure rather than a substring of the file.

    Args:
      None.

    Returns:
      The ``aws:PrincipalArn`` values of the Deny statement's condition.

    Raises:
      AssertionError: If the statement is not the Deny this test is about.
    """
    document = json.loads(BUCKET_POLICY.read_text().replace("${", "@{"))
    deny = document["Statement"][0]
    assert deny["Effect"] == "Deny", "the first statement is no longer the data-access Deny"
    return deny["Condition"]["StringNotLike"]["aws:PrincipalArn"]


def _placeholders() -> set[str]:
    """Returns the allowlist entries that are template placeholders, by name.

    Args:
      None.

    Returns:
      The placeholder names, without the ``@{}`` wrapper.

    Raises:
      None.
    """
    return {entry[2:-1] for entry in _allowlist() if entry.startswith("@{") and entry.endswith("}")}


def _templatefile_arguments() -> set[str]:
    """Returns the arguments s3.tf passes when rendering the bucket policy.

    Args:
      None.

    Returns:
      The argument names in the ``templatefile()`` call for the user-space bucket policy.

    Raises:
      None.
    """
    block = DATA_S3.read_text().split("user-space-bucket-policy.json.tftpl", 1)[1].split("\n}", 1)[0]
    return set(re.findall(r"^\s*([a-z_]+)\s*=", block, re.MULTILINE))


def test_the_parse_is_not_trivial():
    """Guards the guard: an allowlist that parsed to nothing would satisfy every test below."""
    placeholders = _placeholders()

    assert len(placeholders) >= 8, f"only parsed {sorted(placeholders)} — the parse has gone blind"
    assert "arn:aws:iam::@{account_id}:root" in _allowlist(), "the break-glass root entry vanished"


def test_the_expected_principals_are_all_present():
    """The registry. A plane silently dropped from the bucket policy fails here, not at runtime."""
    missing = EXPECTED_PRINCIPALS - _placeholders()

    assert not missing, (
        f"{sorted(missing)} is not on the user-space bucket-policy allowlist — an explicit "
        f"resource-policy Deny beats an identity-policy Allow, so that principal is denied "
        f"by the bucket however correct its own grants are"
    )


def test_every_allowlisted_principal_is_actually_passed_in():
    """A placeholder s3.tf never fills renders as the literal `${foo}` and denies that principal."""
    unfilled = _placeholders() - _templatefile_arguments()

    assert not unfilled, f"{sorted(unfilled)} is in the allowlist but never rendered by s3.tf"


def test_every_principal_passed_in_reaches_the_allowlist():
    """THE HALF A NEW PLANE TRIPS: the variable and the argument added, the list line forgotten.

    ``bucket_arn`` and ``account_id`` are excluded because they are consumed elsewhere in the
    document (the Resource list, and the root ARN the allowlist builds inline) rather than
    being principals in their own right.
    """
    principals = _templatefile_arguments() - {"bucket_arn", "account_id"}
    orphaned = principals - _placeholders()

    assert not orphaned, (
        f"{sorted(orphaned)} is rendered into the bucket policy but appears nowhere in the "
        f"allowlist — the variable and the templatefile() argument landed, the Deny "
        f"exclusion did not"
    )
