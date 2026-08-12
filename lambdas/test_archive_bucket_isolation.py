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
    raw = re.sub(r'("\s*:\s*)\$\{([^}]+)\}', r'\1["\2"]', raw)
    # Each placeholder renders to its OWN NAME, never a shared literal. A shared one makes
    # every by-name assertion below pass with the wrong variable substituted in.
    raw = re.sub(r"\$\{([^}]+)\}", r"\1", raw)
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


def test_the_portal_roles_only_archive_privilege_is_enqueueing():
    """FR-007 AC1. One action, one resource — and it is a QUEUE, not a bucket."""
    statements = _statements(PORTAL_ARCHIVE)

    assert len(statements) == 1
    assert statements[0]["Effect"] == "Allow"
    assert statements[0]["Action"] == "sqs:SendMessage"
    assert statements[0]["Resource"] == "request_queue_arn"


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


def _csp_connect_src_entries():
    """The enumerated hosts inside `csp_connect_src = join(" ", [ … ])`.

    Sliced out of the block, NOT scanned line by line. The list puts each host on its own
    line and none of those lines contains the string `connect_src`, so a per-line scan for
    that word inspects exactly one line — the assignment — and would pass with an archive
    host sitting three lines below it. Measured: inserting one made every check here green.
    """
    body = _read(APP_MODULE / "cloudfront.tf")
    block = body[body.index("csp_connect_src = join("):]
    block = block[: block.index("])")]
    return re.findall(r'"([^"]+)"', block)


def test_no_archive_host_appears_in_the_csp_connect_src():
    """SPEC-140: connect-src IS the app's network surface, so this list is the app's whole
    network surface. A reviewer must be able to read it and see that no archive host appears —
    this asserts it so the reviewer does not have to be the mechanism."""
    entries = _csp_connect_src_entries()

    assert entries, "the connect-src slice found nothing — it is the parse that is broken"
    offenders = [e for e in entries if "archive" in e.lower()]
    assert not offenders, f"connect-src allows an archive host: {offenders}"


def test_the_connect_src_scan_would_see_an_archive_host():
    """Guards the guard. The version this replaced could not see one, and the difference
    between "the list is clean" and "the scan is blind" is not visible in a green run."""
    entries = ["'self'", "https://dat-prod-archive.s3.us-east-1.amazonaws.com"]

    assert [e for e in entries if "archive" in e.lower()]


def test_the_app_module_is_not_wired_to_the_archive_bucket_at_all():
    """The CSP list is built from module.app's OWN variables, so a host can only get in if
    root passes the name in. Neither half alone is sufficient — a hard-coded host would pass
    this and a new variable would pass the list check — so both are asserted."""
    block = _read(ROOT_MAIN).split('module "app"')[1].split("\n}")[0]

    assert "archive" not in block.lower()
    assert not [v for v in _read(APP_MODULE / "variables.tf").splitlines() if "archive" in v.lower()]


# ── FR-001 AC8: the bucket policy admits this plane and deploy, nobody else ──


def test_the_archive_bucket_policy_denies_every_principal_but_this_plane_and_deploy():
    statements = _statements(ARCHIVE_BUCKET_POLICY)

    assert len(statements) == 1
    deny = statements[0]
    assert deny["Effect"] == "Deny"
    assert deny["Principal"] == "*"
    assert set(deny["Condition"]) == {"StringNotLike"}

    allowed = deny["Condition"]["StringNotLike"]["aws:PrincipalArn"]
    # BY NAME, not by count. Rendering every placeholder to the same literal would make this
    # pass with ${portal_role_arn} substituted for ${execution_role_arn} — which is the exact
    # widening the policy exists to prevent — so each placeholder keeps its own name.
    assert allowed == ["execution_role_arn", "deploy_role_arn", "arn:aws:iam::account_id:root"]


def test_the_archive_bucket_policy_denies_restore_object_too():
    """RestoreObject is the action that makes a GLACIER object readable, and it is not covered
    by GetObject. A policy that denied only the four ordinary actions would leave any principal
    able to START a billed retrieval on somebody's archive."""
    deny = _statements(ARCHIVE_BUCKET_POLICY)[0]

    assert "s3:RestoreObject" in deny["Action"]


def test_the_archive_execution_role_holds_no_grant_on_any_data_bucket_yet():
    """SPEC-168 copies nothing and deletes nothing. The listing, the Glacier write and the
    source DELETION are SPEC-169's, and granting them early would make the delete a permission
    this plane INHERITED rather than one a spec decided to give it — which matters more here
    than anywhere else, because this is the only plane whose role cannot carry a blanket
    `Deny s3:DeleteObject` forever.

    Scoped by RESOURCE, not by action. An action list is the wrong axis: the role legitimately
    holds `s3:GetObject`, on the shared-spaces registry in the ADMIN bucket, so a check that
    only forbids Put and Delete passes while its own name says otherwise — and would keep
    passing if `s3:GetObject` on `${user_space_bucket_arn}/*` were added tomorrow.
    """
    forbidden = ("user_space_bucket_arn", "shared_space_bucket_arn", "archive_bucket_arn")
    for statement in _statements(ARCHIVE_EXECUTION):
        resource = statement.get("Resource")
        for arn in [resource] if isinstance(resource, str) else (resource or []):
            assert not any(bucket in arn for bucket in forbidden), (
                f'{statement.get("Sid")} already reaches {arn} — SPEC-169 grants the source '
                "read, the Glacier write and the delete, each with the commit gate in front"
            )


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


# ── FR-001 AC4/AC5/AC6: retention is a ceiling, and the rule is unfiltered ───


def _lifecycle_rules():
    """The archive bucket's lifecycle rules, as `{id: block-text}`.

    Read as text: this is HCL, not JSON, and the question — does this rule carry a
    `filter {}` or a `filter { prefix = … }` — is answerable without a parser.
    """
    body = _read(INFRA / "modules" / "archive" / "s3.tf")
    block = body[body.index('resource "aws_s3_bucket_lifecycle_configuration" "archive"'):]
    rules = {}
    for chunk in block.split("\n  rule {")[1:]:
        chunk = chunk.split("\n  }")[0]
        rules[re.search(r'id\s*=\s*"([^"]+)"', chunk).group(1)] = chunk
    return rules


def test_every_object_expires_and_the_rule_carries_no_prefix_filter():
    """FR-001 AC4. THE INVERSE of the admin bucket's `admin_lifecycle_rules_are_prefix_scoped`
    check, and asserted here for the same reason that one exists there: S3 lifecycle can
    INCLUDE a prefix but never EXCLUDE one.

    That bucket mixes `logs/` (retained forever) with expiring content, so an unfiltered
    expiring rule there would silently delete the logs. This bucket holds exactly one class of
    object, so the risk runs the other way — a prefix filter would be a silent way to leave
    some archived data unexpired past the retention the feature promises.
    """
    rule = _lifecycle_rules()["expire-archived-objects"]

    assert "expiration {" in rule
    assert "days = var.archive_retention_days" in rule
    assert "prefix" not in rule, (
        "the expiry rule has grown a prefix filter — everything outside it is now retained "
        "forever, and the rule still reads as correct"
    )


def test_the_default_retention_is_seven_years():
    """A CEILING, not a WORM floor: nothing here prevents an earlier delete, and SPEC-171's
    restore must be able to delete the archived copy once it has been put back."""
    variables = _read(INFRA / "modules" / "archive" / "variables.tf")
    block = variables[variables.index('variable "archive_retention_days"'):]

    assert re.search(r"default\s*=\s*2557", block)


def test_the_abort_incomplete_multipart_rule_exists_and_cannot_delete_an_object():
    """CKV_AWS_300, the disposition every other bucket already carries. It is unfiltered too,
    and that is safe in a way an expiring rule would not be: it carries no `expiration` and can
    only discard the PARTS of an upload that never completed."""
    rule = _lifecycle_rules()["abort-incomplete-multipart-uploads"]

    assert "abort_incomplete_multipart_upload {" in rule
    assert "expiration {" not in rule


def test_the_bucket_has_no_cors_configuration():
    """FR-001 AC2. The absence is the mechanism, not an omission — and an absence is exactly
    what nothing notices being reversed."""
    body = _read(INFRA / "modules" / "archive" / "s3.tf")

    assert "aws_s3_bucket_cors_configuration" not in body
    assert "No CORS configuration, and the absence is the point" in body


def test_versioning_is_off_so_object_lock_stays_out_of_reach():
    """Object Lock REQUIRES versioning, and in compliance mode nothing can delete an object —
    not even root — which would make SPEC-171's cleanup of a restored archive impossible."""
    body = _read(INFRA / "modules" / "archive" / "s3.tf")

    assert 'status = "Disabled"' in body
    assert "object_lock" not in body.lower()


# ── SPEC-139 parity: no new Resource "*" anywhere in this plane ──────────────


def test_no_archive_policy_introduces_a_new_wildcard_resource():
    """Keeps the SPEC-139 plan scan's IAM findings flat. The two exemptions are the ones every
    plane already carries and neither is scopable: Step Functions log DELIVERY has no ARN, and
    ValidateStateMachineDefinition acts on a definition rather than a resource."""
    unscopable = {"StepFunctionLogDelivery", "ArchiveStateMachineValidate"}
    policies = list((INFRA / "modules" / "archive" / "policies").glob("*.json.tftpl"))
    policies.append(INFRA / "modules" / "base" / "policies" / "github-actions-deploy-archive.json.tftpl")

    assert policies, "the policy sweep found nothing — it is the scan that is broken"
    # THE TWO TEMPLATES THIS SPEC ACTUALLY EDITED, which the sweep above does not reach —
    # FR-006 AC5 puts the requirement on them, and the shared one is not parseable as JSON,
    # so it is checked as text.
    for path in (PORTAL_PERSONAL, PORTAL_SHARED):
        assert '"Resource": "*"' not in _read(path), f"{path.name} introduced a wildcard resource"

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
