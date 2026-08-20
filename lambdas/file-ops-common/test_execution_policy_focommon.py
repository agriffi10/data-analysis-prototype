"""What the file-operations execution role may do, and — mostly — what it may not.

This role will eventually hold ``DeleteObject`` across the user-space bucket, which is the
single most dangerous grant in this repo. It does not hold it here, and these tests are what stop
it arriving early and unreviewed.

**THE ROLE NOW READS BOTH DATA BUCKETS, AND THE RULE THAT REPLACED "NO DATA BUCKET AT ALL" IS
NARROWER RATHER THAN WEAKER.** The machine lists a source folder, heads a selected file and heads
every destination key; a listing is the only producer of an object list there is, so a grant-free
version of this stage would be a plane that cannot run its own two verbs. What it must not hold is
the other direction, and that is asserted twice over: no ``PutObject`` or ``DeleteObject`` Allow
reaches either data bucket, and an explicit ``Deny`` says so — because "read only" resting on the
ABSENCE of an Allow is a state a later statement reverses silently, where a Deny has to be deleted
on purpose.

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


def test_the_role_reads_the_data_buckets_and_writes_to_NEITHER():
    """The rule that replaced "names no data bucket", and the one that has to hold from here on.

    Asserted on the rendered template's own placeholders rather than on a bucket name, because the
    names are supplied at apply time. Every statement naming a data bucket must be a read, and the
    two verbs that exist need exactly three: list the bucket, get an object, and nothing else.
    """
    reads = {"s3:ListBucket", "s3:GetBucketLocation", "s3:GetObject"}
    named = []
    for statement in _statements(EXECUTION_POLICY):
        resources = json.dumps(statement["Resource"])
        if "user_space_bucket_arn" not in resources and "shared_space_bucket_arn" not in resources:
            continue
        named.append(statement["Sid"])
        if statement["Effect"] != "Allow":
            continue
        actions = statement["Action"]
        for action in [actions] if isinstance(actions, str) else actions:
            assert action in reads, f"{statement['Sid']} grants {action!r} on a data bucket"

    assert named, "the plane heads and lists user data — a policy naming no data bucket cannot run"


def test_a_data_bucket_WRITE_is_denied_rather_than_merely_ungranted():
    """The half that survives the next spec's edit.

    A reviewer reading only Allows sees "no write" as an absence, and an absence is what a widened
    statement removes without anyone noticing. The transfer spec has to delete this Deny by name,
    which is a review; adding a Put to an existing Allow is not.
    """
    deny = next(
        s
        for s in _statements(EXECUTION_POLICY)
        if s["Effect"] == "Deny" and "user_space_bucket_arn/*" in json.dumps(s["Resource"])
    )

    assert set(deny["Action"]) == {
        "s3:Put*",
        "s3:Delete*",
        "s3:Restore*",
        "s3:AbortMultipartUpload",
    }, "the Deny is narrower than the claim made for it — every write verb, not two of them"
    assert "shared_space_bucket_arn/*" in json.dumps(deny["Resource"])


def test_every_object_write_is_confined_to_this_planes_own_admin_prefixes():
    """No write verb reaches anything but the two objects this plane owns — its lock and its plan.

    Matched as a PATTERN rather than by equality, because ``s3:*``, ``s3:Put*`` and ``s3:Delete*``
    each grant exactly what this test says is excluded while passing any equality check.
    """
    for statement in _statements(EXECUTION_POLICY):
        if statement["Effect"] != "Allow":
            continue
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            if not action.startswith("s3:"):
                continue
            assert "*" not in action, f"{statement['Sid']} grants the wildcard action {action!r}"
            assert action != "s3:DeleteObject", f"{statement['Sid']} grants DeleteObject"
            if action in ("s3:PutObject", "s3:PutObjectAcl"):
                resource = json.dumps(statement["Resource"])
                assert "admin_bucket_arn" in resource and (
                    "lock_prefix" in resource or "plan_prefix" in resource
                ), f"{statement['Sid']} may write outside this plane's own admin prefixes"


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


def test_the_plan_prefix_in_the_policy_is_the_one_the_code_writes():
    """Two homes for one prefix is a plan the verbs write and the policy does not permit, and it
    fails at the moment the expansion has already done all of its listing.

    The third home is the admin bucket's lifecycle rule, checked with them: a rule filtered on a
    prefix nothing writes expires nothing, and the plans accumulate forever.
    """
    assert f'"{config.PLAN_PREFIX}"' not in EXECUTION_POLICY.read_text()
    plan_statement = next(s for s in _statements(EXECUTION_POLICY) if s["Sid"] == "PlanReadWrite")

    assert plan_statement["Resource"] == "admin_bucket_arn/plan_prefix/*"
    assert (MODULE / "locals.tf").read_text().count(f'plan_prefix = "{config.PLAN_PREFIX}"') == 1
    assert f'prefix = "{config.PLAN_PREFIX}/"' in (
        ROOT / "infra" / "modules" / "analytics" / "s3.tf"
    ).read_text()


def test_the_plan_prefix_cannot_reach_the_lock_objects():
    """An S3 lifecycle prefix anchors at the start of the key, so the expiry rule on the plans must
    not match the locks: a lock is released by OVERWRITING, so that "free" is a state of the object
    rather than its absence, and an expired lock is a missing one — the compare-and-set that detects
    a steal would have nothing left to compare."""
    assert not config.LOCK_PREFIX.startswith(config.PLAN_PREFIX)


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
    deny = next(s for s in _statements(EXECUTION_POLICY) if s["Sid"] == "NoLockDelete")

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
