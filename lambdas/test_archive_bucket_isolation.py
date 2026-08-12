"""The archive bucket's isolation, asserted against the IaC rather than described in prose.

SPEC-168 FR-001/FR-006/FR-007. The claim this file exists to hold is a NEGATIVE one — *the
browser has no relationship with the archive bucket* — and a negative claim is exactly the kind
that rots quietly: nothing fails, nothing looks wrong, and a statement added to the portal role
two specs from now would open the vault with nothing in a diff to say so.

Four properties, and each catches a different mistake:

* the portal role names the archive bucket NOWHERE (the vault stays closed to the browser);
* the archive bucket's own policy denies every principal but this plane and deploy (so an
  identity policy that grew such a statement would still be refused);
* both space buckets deny the browser WRITING under `archive/` (so a receipt cannot be forged);
* the CSP's connect-src has no archive host (so the browser could not reach it even if IAM let
  it).

Read as text rather than as rendered JSON on purpose: these are `.tftpl` templates, so a
`templatefile()` render would need every variable this repo does not have at test time, and the
question being asked — *does this string appear at all* — does not need one.
"""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
INFRA = ROOT / "infra"

PORTAL_PERSONAL = INFRA / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
PORTAL_SHARED = INFRA / "modules" / "shared-spaces" / "policies" / "portal-role-shared-space.json.tftpl"
PORTAL_ARCHIVE = INFRA / "modules" / "archive" / "policies" / "portal-role-archive.json.tftpl"
ARCHIVE_BUCKET_POLICY = INFRA / "modules" / "archive" / "policies" / "archive-bucket-policy.json.tftpl"
ARCHIVE_EXECUTION = INFRA / "modules" / "archive" / "policies" / "execution.json.tftpl"
ROOT_MAIN = INFRA / "main.tf"
APP_MODULE = INFRA / "modules" / "app"


def _read(path):
    return path.read_text()


def _statements(path):
    """The policy's statements, with `${…}` placeholders stubbed so it parses as JSON.

    Two substitutions, not one: a placeholder in a VALUE position (`"Resource": ${arns_json}`,
    the SFN role's constructed function-ARN list) is not inside a string, so stubbing it to a
    bare word makes invalid JSON and fails every check in this file at once — which reads like
    a broken policy rather than a broken parser. That trap is inherited from the fleet's own
    ASL loader, which learned it the same way.

    The value-position pattern anchors on the closing quote of the KEY, not on a bare colon.
    ``"arn:aws:iam::${account_id}:root"`` has a placeholder immediately after a colon too, and
    a colon-anchored pattern rewrites the middle of that ARN into a nested list.
    """
    raw = re.sub(r"\$\$\{[^}]+\}", "TAG", _read(path))
    raw = re.sub(r'("\s*:\s*)\$\{[^}]+\}', r'\1["STUB"]', raw)
    raw = re.sub(r"\$\{[^}]+\}", "STUB", raw)
    return json.loads(raw)["Statement"]


def _shared_space_statement(sid):
    """One statement out of the shared-space portal template, which is NOT parseable as JSON.

    It carries Terraform `%{ for … }` loop directives that render the per-membership-slot
    Allows, so there is no JSON document here until `templatefile()` runs. The archive Deny it
    holds is a plain block with no directive in it, so it is sliced out by Sid and parsed
    alone — which is honest about what is being checked rather than pretending the file is
    something it is not.
    """
    body = _read(PORTAL_SHARED)
    # EVERY brace-bearing template construct is removed BEFORE the slice, not after. Both the
    # `%{ for … }` directives and the `${…}` placeholders contain literal braces, so a
    # rindex("{") on the raw text lands inside one of them and slices from the middle of a
    # string — which fails as "unterminated string" and reads like a malformed policy.
    body = re.sub(r"%\{[^}]*\}", "", body)
    body = re.sub(r"\$\$\{[^}]+\}", "TAG", body)
    body = re.sub(r"\$\{[^}]+\}", "STUB", body)
    start = body.rindex("{", 0, body.index(f'"Sid": "{sid}"'))
    end = body.index("}", body.index("]", start)) + 1
    return json.loads(body[start:end])


# ── FR-001 AC7: the portal role has NO statement naming the archive bucket ───


def test_the_portal_role_names_the_archive_bucket_nowhere():
    """The browser's only relationship with this bucket is that it has none. The only route to
    archived bytes is a restore request through this plane, which is what makes archiving
    reversible only through something that takes hours rather than a click."""
    for path in (PORTAL_PERSONAL, PORTAL_SHARED, PORTAL_ARCHIVE):
        body = _read(path)

        assert "archive_bucket" not in body, f"{path.name} names the archive bucket"
        assert "prod-archive" not in body, f"{path.name} names the archive bucket"


def test_the_portal_roles_only_archive_privilege_is_enqueueing(_=None):
    """FR-007 AC1. One action, one resource — and it is a QUEUE, not a bucket."""
    statements = _statements(PORTAL_ARCHIVE)

    assert len(statements) == 1
    assert statements[0]["Effect"] == "Allow"
    assert statements[0]["Action"] == "sqs:SendMessage"
    assert statements[0]["Resource"].startswith("STUB")


def test_the_archive_module_passes_no_bucket_name_to_the_spa_or_the_app_module():
    """A bucket name in the SPA's build env is the first half of a browser relationship, and
    it would arrive long before any grant made it usable — which is how a reviewer comes to
    believe the browser is supposed to read this bucket."""
    env_example = _read(ROOT / "apps" / "portal" / ".env.example")
    matches = [line for line in env_example.splitlines() if "ARCHIVE" in line and line.startswith("VITE_")]

    assert matches == [
        "VITE_ARCHIVE_QUEUE_URL=https://sqs.us-east-1.amazonaws.com/000000000000/dat-prod-archive-requests.fifo"
    ], "the SPA learns the archive QUEUE and nothing else about this plane"


# ── FR-001 AC3: the bucket host is not in the CSP connect-src ────────────────


def test_no_archive_host_appears_in_the_csp_connect_src():
    """SPEC-140: connect-src IS the app's network surface. A reviewer must be able to read the
    enumerated list and see that no archive host appears — this asserts it so the reviewer does
    not have to be the mechanism."""
    for path in APP_MODULE.rglob("*.tf"):
        body = _read(path)
        for line in body.splitlines():
            if "connect_src" in line or "connect-src" in line:
                assert "archive" not in line.lower(), f"{path.name}: {line.strip()}"

    assert "archive_bucket_name" not in _read(ROOT_MAIN).split('module "app"')[1].split("}")[0]


# ── FR-001 AC8: the bucket policy admits this plane and deploy, nobody else ──


def test_the_archive_bucket_policy_denies_every_principal_but_this_plane_and_deploy():
    statements = _statements(ARCHIVE_BUCKET_POLICY)

    assert len(statements) == 1
    deny = statements[0]
    assert deny["Effect"] == "Deny"
    assert deny["Principal"] == "*"
    assert set(deny["Condition"]) == {"StringNotLike"}

    allowed = deny["Condition"]["StringNotLike"]["aws:PrincipalArn"]
    # Every placeholder renders to the same stub, so the check is on the COUNT of exclusions
    # plus the account root — three, and no more. A fourth would be a widening.
    assert len(allowed) == 3
    assert any("root" in arn for arn in allowed)


def test_the_archive_bucket_policy_denies_restore_object_too():
    """RestoreObject is the action that makes a GLACIER object readable, and it is not covered
    by GetObject. A policy that denied only the four ordinary actions would leave any principal
    able to START a billed retrieval on somebody's archive."""
    deny = _statements(ARCHIVE_BUCKET_POLICY)[0]

    assert "s3:RestoreObject" in deny["Action"]


def test_the_archive_execution_role_holds_no_s3_grant_on_any_data_bucket_yet():
    """SPEC-168 copies nothing and deletes nothing. The listing, the Glacier write and the
    source DELETION are SPEC-169's, and granting them early would make the delete a permission
    this plane inherited rather than one a spec decided to give it."""
    for statement in _statements(ARCHIVE_EXECUTION):
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            assert action != "s3:DeleteObject", "SPEC-169 grants the delete, with its commit gate"
            assert action != "s3:PutObject", "SPEC-169 grants the Glacier write"


# ── FR-006: the browser cannot write under archive/ in either space bucket ───


@pytest.mark.parametrize(
    "deny_of",
    [
        lambda: next(s for s in _statements(PORTAL_PERSONAL) if s["Sid"] == "ArchiveReceiptsAreNotUserWritable"),
        lambda: _shared_space_statement("SharedArchiveReceiptsAreNotUserWritable"),
    ],
    ids=["personal", "shared"],
)
def test_each_space_bucket_denies_the_browser_writing_under_archive(deny_of):
    """A user who can rewrite a receipt can misreport what was archived, to themselves and to
    anyone they show it to."""
    deny = deny_of()

    assert deny["Effect"] == "Deny"
    assert set(deny["Action"]) == {"s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"}
    assert deny["Resource"].endswith("/archive/*")


@pytest.mark.parametrize(
    "denies",
    [
        lambda: [s for s in _statements(PORTAL_PERSONAL) if s["Effect"] == "Deny"],
        lambda: [_shared_space_statement("SharedArchiveReceiptsAreNotUserWritable")],
    ],
    ids=["personal", "shared"],
)
def test_reading_and_listing_the_archive_folder_stay_untouched(denies):
    """The receipt is deliberately a plain text file the user downloads and reads themselves.
    Denying a WRITE action does not perturb listing, and this asserts nothing over-reached."""
    for statement in denies():
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        assert "s3:GetObject" not in actions
        assert "s3:ListBucket" not in actions


def test_the_personal_deny_is_scoped_to_the_callers_own_prefix():
    """A wildcard space segment would be correct for a Deny in the SHARED bucket — where a
    member's slots are tag-scoped and a Deny needs no tag — but in the personal bucket the
    prefix IS the principal tag, and the two forms are not interchangeable."""
    deny = next(s for s in _statements(PORTAL_PERSONAL) if s["Sid"] == "ArchiveReceiptsAreNotUserWritable")

    assert "TAG" in deny["Resource"]  # the stubbed $${aws:PrincipalTag/username}


def test_the_shared_deny_uses_the_wildcard_space_segment():
    """It applies to every membership slot without a per-slot loop, matching the two denies
    already there."""
    deny = _shared_space_statement("SharedArchiveReceiptsAreNotUserWritable")

    assert "/*/archive/*" in deny["Resource"]


# ── SPEC-139 parity: no new Resource "*" anywhere in this plane ──────────────


def test_no_archive_policy_introduces_a_new_wildcard_resource():
    """Keeps the SPEC-139 plan scan's IAM findings flat. The two exemptions are the ones every
    plane already carries and neither is scopable: Step Functions log DELIVERY has no ARN, and
    ValidateStateMachineDefinition acts on a definition rather than a resource."""
    unscopable = {"StepFunctionLogDelivery", "ArchiveStateMachineValidate"}
    policies = list((INFRA / "modules" / "archive" / "policies").glob("*.json.tftpl"))
    policies.append(INFRA / "modules" / "base" / "policies" / "github-actions-deploy-archive.json.tftpl")

    assert policies, "the policy sweep found nothing — it is the scan that is broken"
    for path in policies:
        for statement in _statements(path):
            if statement.get("Sid") in unscopable:
                continue
            resource = statement.get("Resource")
            resources = [resource] if isinstance(resource, str) else (resource or [])
            assert "*" not in resources, f'{path.name}: {statement.get("Sid")} is Resource "*"'


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-q"]))
