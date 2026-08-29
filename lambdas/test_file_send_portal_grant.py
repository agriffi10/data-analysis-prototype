"""The browser has NO file-send privilege at all, and the execution role cannot delete.

The browser used to hold exactly one: ``sqs:SendMessage`` on this plane's request queue. It is
gone — the API is the only writer now, and the grant came off in the same change that repointed
the browser at it, so at no moment was there a trusted actor field with a browser credential able
to forge one.

Why the browser is granted no S3 action at all — the isolation model working rather than a gap —
and why these read templates as data instead of waiting for the CI plan scan:
``infra/modules/file-send/README.md``.

Attributes:
  FILE_SEND_PORTAL_POLICY: Where the browser's enqueue grant used to be. Asserted ABSENT.
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


def test_the_browser_holds_no_file_send_privilege_at_all() -> None:
    """The one grant it had is gone, and the main policy never learned about this plane.

    Asserted as the file's ABSENCE rather than as an empty statement list, because an emptied
    template still renders and still attaches: a policy with no statements and a policy that was
    never created are the same to a reader and different to IAM.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the enqueue template came back, or the main portal policy learned about
        this plane.
    """
    assert not FILE_SEND_PORTAL_POLICY.exists(), (
        "the browser's file-send enqueue grant is retired; the API is the only writer"
    )

    text = PORTAL_POLICY.read_text()
    assert "file-send" not in text and "file_send" not in text, (
        "the main portal policy must not learn about this plane"
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

    for statement in statements:
        assert "*" not in _as_list(statement["Resource"]), (
            f"{EXECUTION_POLICY.name} has a Resource: \"*\" statement ({statement.get('Sid')})"
        )
