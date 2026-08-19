"""What the file-operations execution role may do, and — mostly — what it may not.

This role will eventually hold ``DeleteObject`` across the user-space bucket, which is the
single most dangerous grant in this repo. It does not hold it here, and these tests are what stop
it arriving early and unreviewed: the machine lists nothing, copies nothing and deletes nothing, so
a data-bucket grant now would be unreviewable privilege sitting in production ahead of the code
that justifies it.

They read the ``.tftpl`` templates as data. That is deliberate rather than second-best: the plan
scan in CI evaluates the RENDERED plan and is the authority on findings, but it runs against AWS
credentials, so it cannot tell an author at their desk that the statement they just added widened
this role's reach.

Attributes:
  EXECUTION_POLICY: The shared execution role's permission policy.
  PORTAL_POLICY: The inline policy this module attaches to the browser's role.
  MAIN_PORTAL_POLICY: The portal role's main permission policy — checked here only for the
    negative: this plane must have added nothing to it.
  ANALYTICS_PORTAL_POLICY, SHARED_SPACE_PORTAL_POLICY: The two policies whose ``athenaresults``
    Denies differ by bucket, which is what the domain layer's asymmetric rule mirrors.
"""

import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "control-plane-common"),
)

from focommon import config

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE = ROOT / "infra" / "modules" / "file-ops"
EXECUTION_POLICY = MODULE / "policies" / "execution.json.tftpl"
PORTAL_POLICY = MODULE / "policies" / "portal-role-file-ops.json.tftpl"
MAIN_PORTAL_POLICY = ROOT / "infra" / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
ANALYTICS_PORTAL_POLICY = (
    ROOT / "infra" / "modules" / "analytics" / "policies" / "portal-role-analytics.json.tftpl"
)
SHARED_SPACE_PORTAL_POLICY = (
    ROOT / "infra" / "modules" / "shared-spaces" / "policies" / "portal-role-shared-space.json.tftpl"
)


def _statements(path: pathlib.Path) -> list:
    """Parses a policy template's statements, tolerating its placeholders.

    Args:
      path: The ``.tftpl`` to read.

    Returns:
      The statement list.

    Raises:
      None.
    """
    raw = path.read_text()
    for placeholder in set(__import__("re").findall(r"\$\{[a-z_]+\}", raw)):
        raw = raw.replace(placeholder, placeholder.strip("${}"))
    return json.loads(raw)["Statement"]


def _sids(path: pathlib.Path) -> set:
    """Returns every Sid in a policy template.

    Args:
      path: The ``.tftpl`` to read.

    Returns:
      The set of Sids.

    Raises:
      None.
    """
    return {statement["Sid"] for statement in _statements(path)}


# ── The grant that is not there ──────────────────────────────────────────────


def test_the_execution_role_names_NO_data_bucket():
    """The whole point of this stage. A grant that arrives before the verb that needs it is
    privilege nobody reviewed against a use.

    Asserted on the rendered template's own placeholders rather than on a bucket name, because
    the names are supplied at apply time — if either data bucket's placeholder appears in any
    resource here, something has reached for user data.
    """
    resources = json.dumps([statement["Resource"] for statement in _statements(EXECUTION_POLICY)])

    assert "user_space_bucket_arn" not in resources
    assert "shared_space_bucket_arn" not in resources


def test_the_role_holds_no_object_write_or_delete_anywhere():
    """The complementary negative: no data bucket is named, and no write verb is granted either.

    Either one alone is weaker than it looks — a grant on ``*`` names no bucket, and a grant on a
    bucket with only reads is not the danger.
    """
    for statement in _statements(EXECUTION_POLICY):
        if statement["Effect"] != "Allow":
            continue
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            assert action != "s3:DeleteObject", f"{statement['Sid']} grants DeleteObject"
            if action == "s3:PutObject":
                assert "lock_prefix" in json.dumps(statement["Resource"]), (
                    f"{statement['Sid']} may write outside the lock prefix"
                )


def test_no_statement_uses_a_wildcard_resource():
    """A ``Resource: "*"`` here would be invisible to every name-based assertion above."""
    for statement in _statements(EXECUTION_POLICY):
        assert statement["Resource"] != "*", f"{statement['Sid']} is unscoped"


def test_no_cognito_grant_is_taken():
    """The absence is deliberate rather than pending. Token verification is offline against the
    pool's public JWKS — an HTTPS fetch, not an API call — and this plane authorizes an actor
    against a SPACE, never against a user directory. The neighbouring planes carry AdminGetUser
    because they resolve a recipient; there is no recipient here, and copying the statement over
    would let a role on the user-space bucket's allowlist enumerate the pool.
    """
    assert "cognito-idp" not in EXECUTION_POLICY.read_text()


# ── The grants it does hold, each for a reason ───────────────────────────────


def test_the_failure_path_can_actually_notify():
    """Not an exception to the no-grants rule. The failure path ships from day one and that verb
    enqueues a notification, so a role without this cannot run this module's own first failure
    path — the machine would fail silently on exactly the request the user most needs to hear
    about."""
    assert "EmitNotifications" in _sids(EXECUTION_POLICY)


def test_a_shared_space_can_be_authorized():
    """Authorizing a shared space is a registry read. Without it every shared-space source or
    destination fails AccessDenied while every personal one works — a split that reads like a code
    bug and is not."""
    assert "RegistryRead" in _sids(EXECUTION_POLICY)


def test_the_timeout_door_can_read_the_input_back():
    """On THIS role rather than the state machine's, because it is the notify-failure Lambda that
    makes the call — invoked by EventBridge, outside any execution. EventBridge caps an event at
    256 KB and this plane's own request cap allows a selection to approach it, so without this the
    requests most likely to time out are the ones nobody can be told about."""
    assert "ReadTimedOutExecutionInput" in _sids(EXECUTION_POLICY)


def test_the_lock_prefix_in_the_policy_is_the_one_the_code_writes():
    """Two homes for one prefix is a lock the verbs write and the policy does not permit — an
    AccessDenied on the one object whose whole purpose is preventing data loss."""
    assert f'"{config.LOCK_PREFIX}"' not in EXECUTION_POLICY.read_text()
    lock_statement = next(s for s in _statements(EXECUTION_POLICY) if s["Sid"] == "SpaceLockReadWrite")

    assert lock_statement["Resource"] == "admin_bucket_arn/lock_prefix/*"
    assert (MODULE / "locals.tf").read_text().count(f'lock_prefix = "{config.LOCK_PREFIX}"') == 1


def test_the_lock_can_never_be_deleted():
    """The release frees the lock by OVERWRITING, so that "free" is a STATE of the object rather
    than its absence and a stolen lock stays detectable by compare-and-set. The Deny makes that an
    enforced property instead of a convention, and it is scoped to the ADMIN bucket alone so the
    data-bucket deletes a later spec adds are unaffected."""
    deny = next(s for s in _statements(EXECUTION_POLICY) if s["Effect"] == "Deny")

    assert deny["Action"] == "s3:DeleteObject"
    assert deny["Resource"] == "admin_bucket_arn/*"


# ── The browser's single privilege ───────────────────────────────────────────


def test_the_browser_gains_exactly_one_send_and_nothing_else():
    """That a user's own credentials cannot write into another user's prefix is the isolation
    model working, not a gap — and it is the entire reason this plane exists."""
    statements = _statements(PORTAL_POLICY)

    assert len(statements) == 1
    assert statements[0]["Action"] == "sqs:SendMessage"
    assert statements[0]["Resource"] == "request_queue_arn"


def test_this_plane_added_nothing_to_the_portal_roles_main_policy():
    assert "file-ops" not in MAIN_PORTAL_POLICY.read_text()
    assert "file_ops" not in MAIN_PORTAL_POLICY.read_text()


# ── The IAM the domain layer mirrors ─────────────────────────────────────────


def test_the_athenaresults_denies_differ_BY_BUCKET_exactly_as_the_domain_rule_assumes():
    """The domain layer refuses ``athenaresults/`` root-anchored in a personal space and at any
    depth in a shared one. That asymmetry is not a preference — it mirrors these two policies, and
    a rule that averaged them would refuse a delete IAM permits in one bucket and accept one IAM
    denies in the other.

    Held here rather than against the browser, because there is no browser predicate for
    ``athenaresults`` at any depth — the write-lock rule covers ``archive`` alone — so this is the
    only artifact the source rule's other half can be checked against.
    """
    personal = ANALYTICS_PORTAL_POLICY.read_text()
    shared = SHARED_SPACE_PORTAL_POLICY.read_text()

    assert "aws:PrincipalTag/${principal_tag_key}}/athenaresults/*" in personal, (
        "the personal athenaresults Deny is no longer anchored at the caller's own root"
    )
    assert "${shared_space_bucket_arn}/*/athenaresults/*" in shared, (
        "the shared athenaresults Deny is no longer any-depth"
    )


@pytest.mark.parametrize(
    "key,space_kind,refused",
    [
        ("alice/athenaresults/r.csv", "personal", True),
        ("alice/reports/athenaresults/r.csv", "personal", False),
        ("sales/athenaresults/r.csv", "shared", True),
        ("sales/reports/athenaresults/r.csv", "shared", True),
    ],
)
def test_the_domain_rule_agrees_with_those_denies(key, space_kind, refused):
    """The same four keys, asked of the code rather than the policy. The nested personal case is
    the one the spec names verbatim as something that must NOT be refused."""
    from focommon import protected

    root = f"{key.split('/')[0]}/"

    assert (protected.source_refusal(root, key, "delete", space_kind) is not None) is refused
