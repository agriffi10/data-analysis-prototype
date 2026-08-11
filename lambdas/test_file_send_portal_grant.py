"""The browser's file-send privilege is one queue send, and nothing else.

SPEC-164 FR-005. The whole reason this control plane exists is that a user's credentials
cannot write into another user's prefix — that is the isolation model working, not a gap. So
the grant this spec adds to the shared portal role has to stay exactly one ``sqs:SendMessage``
on one queue ARN, and it has to introduce no ``Resource: "*"`` statement, which is what keeps
the SPEC-139 rendered-plan IAM findings flat at the two permanent deploy-role rows.

These read the ``.tftpl`` templates as data. That is deliberate rather than second-best: the
plan scan in ``deploy-infra.yml`` evaluates the RENDERED plan and is the authority on findings,
but it runs in CI against AWS credentials, so it cannot tell an author at their desk that the
statement they just added widened the browser's reach.

Attributes:
  FILE_SEND_PORTAL_POLICY: The inline policy this module attaches to the portal role.
  PORTAL_POLICY: The portal role's main permission policy — checked here only for the
    negative: file-send must have added nothing to it.
  EXECUTION_POLICY: The file-send execution role's policy, which is where the privilege
    actually lives.
"""

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULE = ROOT / "infra" / "modules" / "file-send"
FILE_SEND_PORTAL_POLICY = MODULE / "policies" / "portal-role-file-send.json.tftpl"
EXECUTION_POLICY = MODULE / "policies" / "execution.json.tftpl"
PORTAL_POLICY = ROOT / "infra" / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"


def _document(path: pathlib.Path) -> dict:
    """Parses a policy template, rewriting ``${`` so the placeholders survive JSON parsing.

    Args:
      path: The template to read.

    Returns:
      The parsed policy document.

    Raises:
      None.
    """
    return json.loads(path.read_text().replace("${", "@{"))


def _statements(path: pathlib.Path) -> list[dict]:
    """Every statement in a policy template.

    Args:
      path: The template to read.

    Returns:
      The statement list.

    Raises:
      None.
    """
    return _document(path)["Statement"]


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


def test_the_browsers_only_file_send_privilege_is_one_queue_send():
    statements = _statements(FILE_SEND_PORTAL_POLICY)

    assert len(statements) == 1
    assert statements[0]["Effect"] == "Allow"
    assert _as_list(statements[0]["Action"]) == ["sqs:SendMessage"]
    assert _as_list(statements[0]["Resource"]) == ["@{request_queue_arn}"]


def test_the_browser_is_granted_no_s3_action_by_this_plane():
    """The point of the plane. A user writing into another user's prefix is what the control
    plane exists to do ON THEIR BEHALF, under a role they cannot assume."""
    actions = [a for s in _statements(FILE_SEND_PORTAL_POLICY) for a in _as_list(s["Action"])]

    assert not [a for a in actions if a.startswith("s3:")]


def test_no_statement_this_spec_adds_uses_a_wildcard_resource():
    """SPEC-139 took the rendered-plan IAM findings from 6 to 2, and the 2 that remain are
    permanent deploy-role rows. A new wildcard here would be a third, and the gate is keyed by
    check ID AND resource, so it would fail the plan job rather than be quietly absorbed."""
    for path in (FILE_SEND_PORTAL_POLICY, EXECUTION_POLICY):
        for statement in _statements(path):
            assert "*" not in _as_list(statement["Resource"]), (
                f"{path.name} has a Resource: \"*\" statement ({statement.get('Sid')})"
            )


def test_the_execution_role_is_not_granted_a_delete_on_any_data_bucket():
    """A send is a copy: it never deletes the sender's files and never overwrites at the
    destination. The Deny makes that a property of the role rather than an intention of the
    code, which matters because this role is on the user-space bucket's principal allowlist."""
    denies = [
        s
        for s in _statements(EXECUTION_POLICY)
        if s["Effect"] == "Deny" and "s3:DeleteObject" in _as_list(s["Action"])
    ]

    assert denies, "the execution policy has no s3:DeleteObject Deny"
    covered = set(_as_list(denies[0]["Resource"]))
    assert covered == {
        "@{user_space_bucket_arn}/*",
        "@{shared_space_bucket_arn}/*",
        "@{admin_bucket_arn}/*",
    }


def test_the_execution_role_can_only_check_a_user_and_not_enumerate_the_pool():
    """FR-004 AC4 makes admin_get_user the rule rather than the habit, and cognito-idp:ListUsers
    would let a role that sits on the user-space bucket allowlist read every username, email and
    attribute in the pool. Table-share's twin statement carries it unused; this one does not."""
    cognito = [
        a
        for s in _statements(EXECUTION_POLICY)
        for a in _as_list(s["Action"])
        if a.startswith("cognito-idp:")
    ]

    assert cognito == ["cognito-idp:AdminGetUser"]


def test_the_portal_roles_main_policy_was_not_touched_by_this_plane():
    """The enqueue grant is its own small inline policy on the role, attached by name. Nothing
    about sending files belongs in the role's general permissions."""
    text = PORTAL_POLICY.read_text()

    assert "file-send" not in text and "file_send" not in text
