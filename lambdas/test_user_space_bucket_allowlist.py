"""The user-space bucket policy's principal allowlist is a registry, and it must not rot.

An explicit resource-policy Deny beats an identity-policy Allow, so a control plane whose
execution role is not on the list is denied by the bucket however correct its own grants are.
The failure is asymmetric and reads like a code bug — why that is, and the three times it bit:
``infra/info/deploy-role-iam.md``.

Attributes:
  BUCKET_POLICY: The rendered-at-apply bucket-policy template.
  DATA_S3: The Terraform that renders it, and the only place its arguments are supplied.
  EXPECTED_PRINCIPALS: Every principal the allowlist must name, by placeholder.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUCKET_POLICY = (
    ROOT / "infra" / "modules" / "data" / "policies" / "user-space-bucket-policy.json.tftpl"
)
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
    "file_ops_execution_role_arn",
    "user_directory_build_role_arn",
}


def _allowlist() -> list[str]:
    """Returns the allowlist's raw entries, placeholders included.

    Parses the template as JSON with ``${`` rewritten to ``@{``, so the assertion is against the
    real document structure rather than a substring of the file.

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
    return {
        entry[2:-1]
        for entry in _allowlist()
        if entry.startswith("@{") and entry.endswith("}")
    }


def _templatefile_arguments() -> set[str]:
    """Returns the arguments s3.tf passes when rendering the bucket policy.

    Args:
      None.

    Returns:
      The argument names in the ``templatefile()`` call for the user-space bucket policy.

    Raises:
      None.
    """
    block = (
        DATA_S3.read_text()
        .split("user-space-bucket-policy.json.tftpl", 1)[1]
        .split("\n}", 1)[0]
    )
    return set(re.findall(r"^\s*([a-z_]+)\s*=", block, re.MULTILINE))


def test_the_allowlist_names_every_expected_plane_and_nothing_unrendered() -> None:
    """The registry, plus the two halves that drift apart in opposite directions.

    A placeholder ``s3.tf`` never fills renders as the literal ``${foo}``, matches no principal
    and silently denies one. The reverse — the variable and the ``templatefile()`` argument
    added, the allowlist line forgotten — is the half a new plane actually trips.

    ``bucket_arn`` and ``account_id`` are excluded because they are consumed elsewhere in the
    document rather than being principals in their own right.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a plane is missing from the allowlist, a placeholder is never
        rendered, or a rendered principal never reaches the allowlist.
    """
    placeholders = _placeholders()
    arguments = _templatefile_arguments()

    assert len(placeholders) >= 8, f"only parsed {sorted(placeholders)} — the parse has gone blind"
    assert "arn:aws:iam::@{account_id}:root" in _allowlist(), "the break-glass root entry vanished"

    assert not EXPECTED_PRINCIPALS - placeholders, (
        f"{sorted(EXPECTED_PRINCIPALS - placeholders)} is not on the user-space bucket-policy "
        "allowlist — an explicit resource-policy Deny beats an identity-policy Allow, so that "
        "principal is denied by the bucket however correct its own grants are"
    )
    assert not placeholders - arguments, (
        f"{sorted(placeholders - arguments)} is in the allowlist but never rendered by s3.tf"
    )
    assert not (arguments - {"bucket_arn", "account_id"}) - placeholders, (
        f"{sorted((arguments - {'bucket_arn', 'account_id'}) - placeholders)} is rendered into "
        "the bucket policy but appears nowhere in the allowlist — the variable and the "
        "templatefile() argument landed, the Deny exclusion did not"
    )
