"""Two artefacts isolate one shared space from another, and neither one says so.

``shared-space-create`` grants Lake Formation ``Database`` and ``Table`` permissions to the
**shared portal role** — one standing grant per space, naming no member. Every portal user
assumes that role, so on its own that grant entitles everyone to everything. What narrows it is
somewhere else entirely: ``portal-role-shared-space.json.tftpl`` scopes the role's Glue actions to
``$${aws:PrincipalTag/shared_space_k}``, so the ARNs resolve only to the spaces the caller's
session tags name. Isolation is the INTERSECTION of a grant in Python and a condition in HCL, and
each half reads as complete on its own.

That is a live property of this account, and it is also the thing the client transition is most
likely to break, in either direction. Retire the principal tags and leave the role-level grants:
every portal user holds catalog access to every shared space. Revoke the grants first: every
member is locked out. The ordering that avoids both is transition work — ``transition_plan.md``
§3.11 — and this file is the current-account half: it fails when either artefact moves without the
other, in the tree where the edit is made.

**A tripwire, not a design.** If the coupling is deliberately replaced — per-member grants, a
different narrowing — revisit the decision and rewrite these assertions with it. Do not delete a
red test here to make a change land.

The scoping sweep reads **every** Glue ARN in the template rather than the ones inside the
statement that carries them today, because adding a second statement is a likelier edit than
rewriting an existing ``Resource`` list, and a slice keyed on one ``Sid`` cannot see one. For the
same reason the action sweep refuses a **wildcarded** Glue action as well as the two spelled-out
ones: ``glue:*Database`` grants both while matching neither literally.

**Both sweeps are Effect-blind, and that cuts both ways.** They read the template as text, so a
``Deny`` carrying a Glue ARN, or a ``Deny`` on ``glue:*Database``, reddens them as though it were a
grant — and the failure message would describe the opposite of what the author did. Nothing in any
portal-role template does this today. It is stated because the hardening this file argues for is
exactly the edit that would trip it: if you add such a ``Deny``, teach these two sweeps about
``Effect`` rather than deleting the assertion.

What it does NOT cover: a narrowing supplied by some third mechanism (an SCP, a permissions
boundary, a Lake Formation LF-Tag policy) would be invisible to it, and personal-space isolation
is the same shape in ``portal-role-analytics.json.tftpl`` but is asserted only by the action sweep
below, which covers every portal-role template.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda tree.
  POLICIES: Every template rendered onto the portal role, by glob. It matches the role's trust
    policy too, which carries no Glue action and so cannot answer the action sweep either way.
  SHARED_SPACE_POLICY: The one template narrowing the role to a member's own spaces.
  GLUE_SID: The statement in it that carries the Glue actions today. Asserted to still exist, so a
    rename is noticed, but the sweeps below do not depend on it.
  MEMBERSHIP_TAG: The principal tag whose expansion IS the narrowing.
  CATALOG_SUFFIX: The one Glue resource in the template that carries no space, and may not.
  DATABASE_MUTATION: The two Glue actions that would make the Lake Formation grant's ``DROP`` and
    ``ALTER`` on a Database live for every member. Absent from every portal-role template today,
    which is the only reason a member cannot delete a shared space's catalog.
  GLUE_WILDCARD: An action pattern that reaches a Glue action without naming one.
  ROLE_DATABASE_PERMISSIONS: The Lake Formation database set the role holds, as literals. Written
    out rather than read from ``config`` so that a change to the constant reddens this file
    instead of moving both sides of the comparison together.
  ROLE_TABLE_PERMISSIONS: The same, at table level.
"""

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
POLICIES = "infra/modules/*/policies/portal-role-*.json.tftpl"
SHARED_SPACE_POLICY = "infra/modules/shared-space-storage/policies/portal-role-shared-space.json.tftpl"
GLUE_SID = "SharedSpaceGlue"
MEMBERSHIP_TAG = "aws:PrincipalTag/shared_space_"
CATALOG_SUFFIX = ":catalog"
DATABASE_MUTATION = ("glue:DeleteDatabase", "glue:UpdateDatabase")
GLUE_WILDCARD = re.compile(r'"glue:[^"]*\*[^"]*"')
ROLE_DATABASE_PERMISSIONS = ("DESCRIBE", "CREATE_TABLE", "ALTER", "DROP")
ROLE_TABLE_PERMISSIONS = ("SELECT", "INSERT", "DESCRIBE", "ALTER", "DROP")

sys.path.insert(0, str(LAMBDAS / "shared-space-common"))
sys.path.insert(0, str(LAMBDAS / "shared-space-create"))

import create_space
from fakes import install

import config


def test_create_grants_lake_formation_to_the_shared_role_not_to_a_member():
    """The union grant exists, it is the role that holds it, and its breadth is pinned.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When create stops issuing both halves to the portal role, or when the
        breadth of either half moves.
    """
    _s3, _glue, lf, _cognito = install()
    create_space.create_space("sales", "alice", "req-1")

    principals = {grant["Principal"]["DataLakePrincipalIdentifier"] for grant in lf.grants}
    assert principals == {config.PORTAL_ROLE_ARN}, (
        "every Lake Formation grant a create issues goes to the shared portal role. A grant to "
        "anything else is a different isolation model and the tag conditions no longer describe it"
    )
    granted = {next(iter(grant["Resource"])): tuple(grant["Permissions"]) for grant in lf.grants}
    assert granted == {
        "Database": ROLE_DATABASE_PERMISSIONS,
        "Table": ROLE_TABLE_PERMISSIONS,
    }, (
        "the role-level grant is Database + Table at a pinned breadth, and that breadth is what "
        "the tag scoping narrows. Widening it widens every member of every space at once"
    )


def test_every_glue_resource_in_the_shared_space_policy_is_scoped_by_the_membership_tag():
    """No Glue ARN anywhere in the template reaches a space the caller's tags do not name.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a Glue resource names a space without the tag expansion.
    """
    text = (ROOT / SHARED_SPACE_POLICY).read_text()
    assert f'"Sid": "{GLUE_SID}"' in text, (
        f"{GLUE_SID} is gone from {SHARED_SPACE_POLICY}. The sweep below still holds, but the "
        "statement this file was written against has been renamed or removed — read it again"
    )
    resources = [line.strip() for line in text.split("\n") if "arn:aws:glue" in line]
    assert resources, f"{SHARED_SPACE_POLICY} names no Glue resources — the statement moved"

    untagged = [
        line for line in resources
        if MEMBERSHIP_TAG not in line and not line.rstrip('",').endswith(CATALOG_SUFFIX)
    ]
    assert untagged == [], (
        f"a Glue resource is not scoped by {MEMBERSHIP_TAG}. That expansion is the ONLY thing "
        "standing between the role-level Lake Formation grant and every user reading every shared "
        f"space; the catalog ARN is the one exception, and it grants no space. Found: {untagged}"
    )


@pytest.mark.parametrize("action", DATABASE_MUTATION)
def test_no_portal_role_policy_grants_glue_database_mutation(action):
    """A member cannot drop or alter a shared space's catalog, and this is why.

    Lake Formation already grants the role ``ALTER`` and ``DROP`` on every space Database. The
    role cannot use them because no IAM policy gives it these two Glue actions — so the effective
    right is the intersection, and adding either action here makes catalog destruction reachable
    by any member of any space, today, with no other change.

    Args:
      action: The Glue database-mutation action being swept for.

    Returns:
      None.

    Raises:
      AssertionError: When a portal-role template names it.
    """
    carriers = [
        str(path.relative_to(ROOT))
        for path in sorted(ROOT.glob(POLICIES))
        if action in path.read_text()
    ]
    assert carriers == [], (
        f"{action} is granted to the portal role by {carriers}. Lake Formation already grants the "
        "role DROP and ALTER on every shared-space database; this omission in IAM is the whole "
        "reason a member cannot destroy one. Granting it here is not a widening, it is the removal "
        "of the guard"
    )


def test_no_portal_role_policy_reaches_a_glue_action_by_wildcard():
    """The action sweep above matches literals, so a wildcard would walk past it.

    ``glue:*Database`` and ``glue:*`` each grant both mutation actions while matching neither
    spelling. An over-broad grant is the likelier way this arrives, so it is refused outright
    rather than enumerated.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a portal-role template names a wildcarded Glue action.
    """
    carriers = {
        str(path.relative_to(ROOT)): sorted(set(GLUE_WILDCARD.findall(path.read_text())))
        for path in sorted(ROOT.glob(POLICIES))
        if GLUE_WILDCARD.search(path.read_text())
    }
    assert carriers == {}, (
        f"a portal-role template reaches a Glue action by wildcard: {carriers}. The named sweep "
        "cannot see one, and a wildcard covering DeleteDatabase or UpdateDatabase hands every "
        "member the ability to destroy a shared space's catalog. Name the actions instead"
    )
