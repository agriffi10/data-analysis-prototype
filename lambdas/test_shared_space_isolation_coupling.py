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
Phase 5 → *Shared-space entitlements* — and this file is the current-account half: it fails when
either artefact moves without the other, in the tree where the edit is made.

**A tripwire, not a design.** If the coupling is deliberately replaced — per-member grants, a
different narrowing — revisit the decision and rewrite these assertions with it. Do not delete a
red test here to make a change land.

What it does NOT cover: a narrowing supplied by some third mechanism (an SCP, a permissions
boundary, a Lake Formation LF-Tag policy) would be invisible to it, and personal-space isolation
is the same shape in ``portal-role-analytics.json.tftpl`` but is not asserted here — that template
is swept for database mutation below and nothing more.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda tree.
  POLICIES: Every portal-role permission template, by glob.
  SHARED_SPACE_POLICY: The one template narrowing the role to a member's own spaces.
  GLUE_SID: The statement inside it that carries the Glue actions.
  MEMBERSHIP_TAG: The principal tag whose expansion IS the narrowing.
  CATALOG_SUFFIX: The one Glue resource in that statement that carries no space, and may not.
  DATABASE_MUTATION: The two Glue actions that would make the Lake Formation grant's ``DROP``
    and ``ALTER`` on a Database live for every member. Absent from every portal-role template
    today, which is the only reason a member cannot delete a shared space's catalog.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
POLICIES = "infra/modules/*/policies/portal-role-*.json.tftpl"
SHARED_SPACE_POLICY = "infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl"
GLUE_SID = "SharedSpaceGlue"
MEMBERSHIP_TAG = "aws:PrincipalTag/shared_space_"
CATALOG_SUFFIX = ":catalog"
DATABASE_MUTATION = ("glue:DeleteDatabase", "glue:UpdateDatabase")

sys.path.insert(0, str(LAMBDAS / "shared-space-common"))
sys.path.insert(0, str(LAMBDAS / "shared-space-create"))

import create_space
from fakes import install

import config


def _statement(sid):
    """Reads one statement out of the shared-space policy template, as lines.

    The template is HCL-in-JSON — ``%{ for }`` directives and ``$${}`` escapes — so it does not
    parse as JSON and is read as text. The slice runs from the named ``Sid`` to the next one,
    which is what makes "every resource in THIS statement" answerable.

    Args:
      sid: The statement's ``Sid`` value.

    Returns:
      The statement's lines, from its ``Sid`` to the line before the next ``"Sid"``.

    Raises:
      AssertionError: When no statement carries that ``Sid``.
    """
    lines = (ROOT / SHARED_SPACE_POLICY).read_text().split("\n")
    starts = [i for i, line in enumerate(lines) if f'"Sid": "{sid}"' in line]
    assert starts, f"{SHARED_SPACE_POLICY} has no statement with Sid {sid!r}"
    start = starts[0]
    after = [i for i, line in enumerate(lines[start + 1 :], start + 1) if '"Sid"' in line]
    return lines[start : after[0] if after else len(lines)]


def test_create_grants_lake_formation_to_the_shared_role_not_to_a_member():
    """The union grant exists, and it is the role that holds it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When create stops issuing both halves to the portal role.
    """
    _s3, _glue, lf, _cognito = install()
    create_space.create_space("sales", "alice", "req-1")

    principals = {grant["Principal"]["DataLakePrincipalIdentifier"] for grant in lf.grants}
    assert principals == {config.PORTAL_ROLE_ARN}, (
        "every Lake Formation grant a create issues goes to the shared portal role. A grant to "
        "anything else is a different isolation model and the tag conditions no longer describe it"
    )
    granted = {
        next(iter(grant["Resource"])): tuple(grant["Permissions"]) for grant in lf.grants
    }
    assert granted == {
        "Database": tuple(config.DATABASE_PERMISSIONS),
        "Table": tuple(config.TABLE_PERMISSIONS),
    }, "the role-level grant is Database + Table, and its breadth is what the tag scoping narrows"


def test_every_glue_space_resource_is_scoped_by_the_membership_tag():
    """Nothing in the Glue statement reaches a space the caller's tags do not name.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a Glue resource names a space without the tag expansion.
    """
    resources = [line for line in _statement(GLUE_SID) if "arn:aws:glue" in line]
    assert resources, f"{GLUE_SID} names no Glue resources — the statement moved"

    untagged = [line.strip() for line in resources if MEMBERSHIP_TAG not in line]
    assert [line for line in untagged if not line.rstrip('",').endswith(CATALOG_SUFFIX)] == [], (
        f"a Glue resource in {GLUE_SID} is not scoped by {MEMBERSHIP_TAG}. That expansion is the "
        "ONLY thing standing between the role-level Lake Formation grant and every user reading "
        f"every shared space; the catalog ARN is the one exception, and it grants no space. Found: {untagged}"
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
