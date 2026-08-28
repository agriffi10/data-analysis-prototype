"""The browser's file-send privilege is one queue send, and the execution role cannot delete.

Why the browser is granted no S3 action at all — the isolation model working rather than a gap —
and why these read templates as data instead of waiting for the CI plan scan:
``infra/modules/file-send/README.md``.

Attributes:
  FILE_SEND_PORTAL_POLICY: The inline policy this module attaches to the portal role.
  EXECUTION_POLICY: The file-send execution role's policy, where the privilege actually lives.
  PORTAL_POLICY: The portal role's main permission policy — checked only for the negative.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "infra" / "modules" / "file-send"
FILE_SEND_PORTAL_POLICY = MODULE / "policies" / "portal-role-file-send.json.tftpl"
EXECUTION_POLICY = MODULE / "policies" / "execution.json.tftpl"
PORTAL_POLICY = (
    ROOT / "infra" / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
)


def _statements(path: pathlib.Path) -> list[dict]:
    """Every statement in a policy template, with ``${`` rewritten so JSON parsing survives.

    Args:
      path: The template to read.

    Returns:
      The statement list.

    Raises:
      None.
    """
    return json.loads(path.read_text().replace("${", "@{"))["Statement"]


def _as_list(value) -> list:
    """Normalises a policy field that may be a scalar or a list.

    Args:
      value: The ``Action`` or ``Resource`` field.

    Returns:
      The value as a list.

    Raises:
      None.
    """
    return value if isinstance(value, list) else [value]


def test_the_browsers_only_file_send_privilege_is_one_queue_send() -> None:
    """A user writing into another user's prefix is what this plane does ON THEIR BEHALF, under
    a role they cannot assume — so the browser gains one enqueue and no S3 action at all.

    The grant is its own small inline policy attached by name; nothing about sending files
    belongs in the role's general permissions.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the browser gains more than the one send, or the main portal policy
        learned about this plane.
    """
    statements = _statements(FILE_SEND_PORTAL_POLICY)

    assert len(statements) == 1
    assert statements[0]["Effect"] == "Allow"
    assert _as_list(statements[0]["Action"]) == ["sqs:SendMessage"]
    assert _as_list(statements[0]["Resource"]) == ["@{request_queue_arn}"]

    text = PORTAL_POLICY.read_text()
    assert "file-send" not in text and "file_send" not in text, (
        "the enqueue grant is a separate inline policy — the main one must not name this plane"
    )


def test_the_execution_role_cannot_delete_enumerate_or_reach_a_wildcard() -> None:
    """This role sits on the user-space bucket's principal allowlist, so its ceiling matters.

    A send is a copy: it never deletes the sender's files and never overwrites at the
    destination, and the Deny makes that a property of the role rather than an intention of the
    code. ``cognito-idp:ListUsers`` would let it read every username, email and attribute in the
    pool. A new ``Resource: "*"`` would be a third rendered-plan IAM finding, and the gate is
    keyed by check ID AND resource, so it fails the plan job rather than being absorbed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the delete Deny is missing or narrowed, the role can enumerate the
        pool, or either policy introduces a wildcard resource.
    """
    statements = _statements(EXECUTION_POLICY)

    denies = [
        statement
        for statement in statements
        if statement["Effect"] == "Deny" and "s3:DeleteObject" in _as_list(statement["Action"])
    ]
    assert denies, "the execution policy has no s3:DeleteObject Deny"
    assert set(_as_list(denies[0]["Resource"])) == {
        "@{user_space_bucket_arn}/*",
        "@{shared_space_bucket_arn}/*",
        "@{admin_bucket_arn}/*",
    }

    cognito = [
        action
        for statement in statements
        for action in _as_list(statement["Action"])
        if action.startswith("cognito-idp:")
    ]
    assert cognito == ["cognito-idp:AdminGetUser"], (
        f"the role reaches {cognito} — ListUsers would expose the whole pool to a principal on "
        "the user-space bucket allowlist"
    )

    for path in (FILE_SEND_PORTAL_POLICY, EXECUTION_POLICY):
        for statement in _statements(path):
            assert "*" not in _as_list(statement["Resource"]), (
                f"{path.name} has a Resource: \"*\" statement ({statement.get('Sid')})"
            )
