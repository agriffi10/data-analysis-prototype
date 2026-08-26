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


def _csp_connect_src_entries(main_tf=None):
    """The enumerated hosts inside `csp_connect_src = join(" ", [ … ])`.

    Every entry, quoted or not. The list puts each host on its own line, so the slice is what
    makes the scan see more than the assignment line — a per-line scan for `connect_src` finds
    exactly one line and would pass with an archive host three lines below it.

    Unquoted entries count. A regex over quoted strings alone was complete while every term was
    a literal; the list now also carries interpolated locals, and a new bucket's origin would
    most naturally arrive as one of those — invisible to the old pattern.
    """
    body = _read(main_tf or INFRA / "main.tf")
    block = body[body.index("csp_connect_src = join("):]
    block = block[: block.index("])")]
    entries = []
    for line in block.splitlines()[1:]:
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        # Quoted AND unquoted, because the list carries both. A regex over quoted strings
        # alone was correct while every term was a literal; the first interpolated local
        # (an origin built at root) made it blind to exactly the kind of entry a new bucket
        # would arrive as.
        entries.append(line[1:-1] if line.startswith('"') and line.endswith('"') else line)
    return entries


def test_no_archive_host_appears_in_the_csp_connect_src():
    """SPEC-140: connect-src IS the app's network surface, so this list is the app's whole
    network surface. A reviewer must be able to read it and see that no archive host appears —
    this asserts it so the reviewer does not have to be the mechanism."""
    entries = _csp_connect_src_entries()

    assert entries, "the connect-src slice found nothing — it is the parse that is broken"
    offenders = [e for e in entries if "archive" in e.lower()]
    assert not offenders, f"connect-src allows an archive host: {offenders}"


def test_the_connect_src_scan_would_see_an_archive_host(tmp_path):
    """Guards the guard, through the REAL parser rather than a hand-built list.

    A fixture of literal strings proves only that `"archive" in e` works. It cannot see the
    failure that actually happened: the parser matched quoted terms only, so an interpolated
    entry was invisible to it and an archive origin added that way passed every check here.
    Both shapes are exercised below, against the parser itself.
    """
    for entry in (
        '"https://dat-prod-archive.s3.us-east-1.amazonaws.com",',
        "local.archive_origin,",
    ):
        fake = tmp_path / "main.tf"
        fake.write_text(
            'locals {\n  csp_connect_src = join(" ", [\n    "\'self\'",\n    '
            + entry
            + "\n  ])\n}\n"
        )
        seen = _csp_connect_src_entries(fake)

        assert [e for e in seen if "archive" in e.lower()], (
            f"the scan cannot see {entry!r} — a clean list and a blind scan look identical"
        )


def test_the_app_module_is_not_wired_to_the_archive_bucket_at_all():
    """The CSP list is built at ROOT now, so a host gets in only if somebody adds it there.

    Both halves still matter: this checks the app module's own wiring, and the list check above
    checks what root assembles. A hard-coded host would pass one and a new variable the other.
    """
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


def _execution_statement(sid):
    """One statement of the archive execution role's policy, by Sid."""
    found = [s for s in _statements(ARCHIVE_EXECUTION) if s.get("Sid") == sid]

    assert len(found) == 1, f"{sid} is not in the archive execution policy exactly once"
    return found[0]


def test_the_write_into_a_users_space_is_unrestricted_by_prefix_and_deliberately_so():
    """**SPEC-171 FR-007 AC2 WIDENED THIS, and the widening is recorded here rather than left to
    a diff.** SPEC-169's `ReceiptWrite` was `*/archive/*` because the only thing this plane put
    into a user's space was a receipt — the data went the other way, into the vault. A RESTORE
    writes wherever the data came from, which is anywhere in the space, so the narrow grant
    cannot stand.

    The multipart pair rides with it because an archived object may be up to
    ARCHIVE_MAX_OBJECT_BYTES (10 GiB) and the copy-back part-copies above 5 GiB — a grant that
    covered `PutObject` alone would restore every small object and fail on exactly the big ones,
    hours into a run.
    """
    write = _execution_statement("SpaceDataWrite")

    assert write["Effect"] == "Allow"
    assert set(write["Action"]) == {
        "s3:PutObject",
        "s3:AbortMultipartUpload",
        "s3:ListMultipartUploadParts",
    }
    assert set(write["Resource"]) == {"user_space_bucket_arn/*", "shared_space_bucket_arn/*"}


@pytest.mark.parametrize(
    "pattern",
    [
        "/*/athenaresults/*",
        "/*/user_settings/*",
        # AT THE BUCKET ROOT, so a `*/x/*` pattern cannot match them: the feature-flag document
        # that decides what every user can see (SPEC-162) and the username directory (SPEC-146).
        # They are the two most dangerous objects in that bucket and were outside a statement
        # whose NAME claims to cover portal-managed state.
        "/_config/*",
        "/_directory/*",
    ],
)
def test_the_widened_write_can_never_reach_portal_managed_state(pattern):
    """The narrowing that goes with FR-007's widening, and it is defence in depth rather than
    the rule itself: `athenaresults/` and `user_settings/` can never appear in an archive
    (RESERVED_SOURCE_ROOTS refuses them at archive time) and the destination guard's fail-closed
    403-is-occupied rule refuses them again at restore time. What the Deny buys is that a plan
    which somehow named one could not overwrite the notification inbox or a user's query results.

    It deliberately does NOT cover `archive/`, which is exactly where the receipt lives — the one
    place this plane may write and may never delete.
    """
    deny = _execution_statement("NeverOverwritePortalManagedObjects")

    assert deny["Effect"] == "Deny"
    assert deny["Action"] == "s3:PutObject"
    assert [arn for arn in deny["Resource"] if arn.endswith(pattern)]
    assert not [arn for arn in deny["Resource"] if arn.endswith("/*/archive/*")], (
        "the receipt's own prefix is denied — every archive would fail at its last state"
    )


def test_the_state_machine_role_already_covers_the_two_new_maps():
    """**SPEC-171 FR-007 AC3, ASSERTED RATHER THAN ASSUMED**, which is SPEC-170's own precedent:
    the spec lists grants for the copy-back Map, and every one of them already exists because
    SPEC-169's copy needed the identical set — the new Maps read a manifest under
    `{admin}/archive/*` and export under it, exactly as the old one does.

    "It already works" is the claim most worth checking, because the failure mode is silent until
    the first real restore: the Map's own permissions belong to the STATE MACHINE role, and on
    the Lambda role they render, apply and unit-test green and then AccessDeny at the ItemReader
    (SPEC-160 FR-006). So this reads the rendered policy rather than trusting the inheritance.
    """
    sfn = _statements(INFRA / "modules" / "archive" / "policies" / "sfn-permissions.json.tftpl")
    granted = {}
    for statement in sfn:
        if statement.get("Effect") != "Allow":
            continue
        actions = statement["Action"]
        resource = statement["Resource"]
        for action in [actions] if isinstance(actions, str) else actions:
            granted.setdefault(action, set()).update(
                [resource] if isinstance(resource, str) else resource
            )

    assert granted["states:StartExecution"] == {"state_machine_arn"}
    assert granted["states:DescribeExecution"] == {"child_execution_arn_wildcard"}
    # One prefix covers both restore Maps' ItemReader and both ResultWriters, because
    # arcommon.plan keys every artifact of a run under `archive/{requestId}/`.
    assert "admin_bucket_arn/archive/*" in granted["s3:GetObject"]
    assert "admin_bucket_arn/archive/*" in granted["s3:PutObject"]


def test_the_retrieval_is_granted_as_its_own_action_on_the_vault():
    """SPEC-171 FR-007 AC1. `s3:RestoreObject` is a DISTINCT ACTION from GetObject and
    PutObject — a role holding both still cannot initiate a retrieval — and the failure of
    missing it would be an AccessDenied at the point of no return rather than at plan time."""
    retrieve = _execution_statement("ArchiveVaultRetrieve")

    assert retrieve["Effect"] == "Allow"
    assert retrieve["Action"] == "s3:RestoreObject"
    assert retrieve["Resource"] == "archive_bucket_arn/*"


def test_the_source_delete_is_granted_on_the_space_buckets_and_nowhere_else():
    """**The one grant that makes this plane unlike every other one.** File-send and table-share
    each carry a blanket `Deny s3:DeleteObject` from their first apply; this role cannot, because
    archiving deletes what it copies. So the delete is scoped to the two SPACE buckets — never
    the admin bucket, and never the vault by this statement, which has its own."""
    delete = _execution_statement("SourceDataDelete")

    assert delete["Effect"] == "Allow"
    assert delete["Action"] == "s3:DeleteObject"
    assert set(delete["Resource"]) == {"user_space_bucket_arn/*", "shared_space_bucket_arn/*"}


@pytest.mark.parametrize(
    "pattern",
    [
        "/*/athenaresults/*",
        "/*/user_settings/*",
        "/*/archive/*",
        "/*DO_NOT_DELETE.txt",
    ],
)
def test_the_delete_can_never_reach_a_portal_managed_object(pattern):
    """The narrowing that replaces the blanket Deny the other planes get for free, and it is
    written as a DENY rather than as a narrower Allow because an explicit Deny beats every
    Allow, including one a later spec adds without reading this file.

    Each pattern is a different way for a run to end badly: `athenaresults/` and any
    `DO_NOT_DELETE.txt` would be refused by the BUCKET policy part way through a deletion, after
    some of the user's data had gone; `user_settings/` is the notification inbox and connections
    cache, so deleting it breaks the app for the user; `archive/` holds the receipts this plane
    itself writes, which are a user's only route to a restore.

    `*` matches `/` in an IAM resource, which is what makes the marker rule hold at any depth —
    the same property both bucket policies already rely on.
    """
    deny = _execution_statement("NeverDeletePortalManagedObjects")

    assert deny["Effect"] == "Deny"
    assert deny["Action"] == "s3:DeleteObject"
    assert [arn for arn in deny["Resource"] if arn.endswith(pattern)], (
        f"nothing denies s3:DeleteObject on {pattern}"
    )


def test_the_vault_grants_belong_to_this_role_and_the_map_grants_do_not():
    """SPEC-160 FR-006, inherited rather than rediscovered: the Distributed Map's own
    permissions — StartExecution for each child, the ItemReader read, the ResultWriter write —
    belong to the STATE MACHINE role. On the Lambda role they render, apply and unit-test green,
    then fail on the first real archive with AccessDenied at the ItemReader.

    The one states: action that IS on this role is the timeout door's DescribeExecution, because
    it is the notify-failure LAMBDA that makes that call, invoked by EventBridge outside any
    execution.
    """
    lambda_actions = set()
    for statement in _statements(ARCHIVE_EXECUTION):
        action = statement.get("Action")
        lambda_actions.update([action] if isinstance(action, str) else action)

    assert "states:StartExecution" not in lambda_actions
    assert lambda_actions & {"states:DescribeExecution"} == {"states:DescribeExecution"}

    sfn = _statements(INFRA / "modules" / "archive" / "policies" / "sfn-permissions.json.tftpl")
    sfn_actions = set()
    for statement in sfn:
        action = statement.get("Action")
        sfn_actions.update([action] if isinstance(action, str) else action)

    assert "states:StartExecution" in sfn_actions


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


# ── The admin bucket's archive/ prefix, and the three unrelated things so named ──


def test_the_admin_buckets_archive_prefix_expires_and_is_prefix_scoped():
    """SPEC-169's copy plan, transfer manifest and Map Run results live in the ADMIN bucket, and
    that bucket's own `admin_lifecycle_rules_are_prefix_scoped` check fails any EXPIRING rule
    without a `filter.prefix` — because an unfiltered one there would reach `logs/`, which
    SPEC-127 FR-009 retains indefinitely. The exact inverse of the archive bucket's rule, in the
    same repo, for opposite and equally good reasons.
    """
    body = _read(INFRA / "modules" / "analytics" / "s3.tf")
    block = body[body.index('id     = "expire-archive-copy-plans"'):]
    block = block[: block.index("\n  }")]

    assert 'prefix = "archive/"' in block
    assert "expiration {" in block


def test_the_three_things_named_archive_are_in_three_different_buckets():
    """Worth pinning because the name collides three ways and only one of them expires quickly.

    `{admin}/archive/` is control-plane scratch (days). `{space}/archive/` holds the user's
    RECEIPTS and is never expired. The archive BUCKET holds the data itself (7 years). A
    lifecycle rule written against the wrong one deletes either a user's only route to a restore
    or the archive it points at.
    """
    admin = _read(INFRA / "modules" / "analytics" / "s3.tf")
    archive = _read(INFRA / "modules" / "archive" / "s3.tf")

    # The admin bucket expires its archive/ prefix; it has no rule reaching a user's space.
    assert 'prefix = "archive/"' in admin
    # The archive bucket's rule is unfiltered and 7-year; it names no prefix at all.
    assert "archive_retention_days" in archive
    assert 'prefix = "archive/"' not in archive
    # Nothing anywhere expires the receipts, which live in the two SPACE buckets. Matched on
    # lifecycle PREFIXES, not on the word: `data/s3.tf` legitimately names the archive execution
    # role (the user-space bucket policy's allowlist) a few lines below its lifecycle block, and
    # a whole-file grep reads that as a rule.
    for module in ("data", "shared-spaces"):
        body = _read(INFRA / "modules" / module / "s3.tf")
        prefixes = re.findall(r'prefix\s*=\s*"([^"]*)"', body)
        assert not [pfx for pfx in prefixes if "archive" in pfx.lower()], (
            f"{module}/s3.tf has grown a lifecycle rule reaching archive/ — that folder holds "
            "the receipts, which are a user's only route to a restore"
        )


# ── SPEC-170: the guard's permission, where the failure mode is a FALSE PASS ─


def test_the_destination_guard_reads_with_GetObject_and_never_with_ListBucket():
    """SPEC-170 FR-006, and the reason it is asserted rather than assumed.

    `HeadObject` is authorized as **s3:GetObject**, not as `s3:ListBucket` — the trap being that
    a role granted only the listing permission does not ERROR on a head, it gets a 403, and this
    guard reads a 403 as OCCUPIED. So the visible symptom of the wrong grant would be every
    restore refusing; the invisible one, if the guard had been written to read an unreadable key
    as clear, is every restore silently overwriting. Both directions come back to this statement
    being the one that exists.

    The grant itself is SPEC-169's `SourceDataRead`, unchanged and unwidened: this spec adds no
    IAM at all, which is what this test records.
    """
    read = _execution_statement("SourceDataRead")

    assert read["Effect"] == "Allow"
    assert read["Action"] == "s3:GetObject"
    assert set(read["Resource"]) == {"user_space_bucket_arn/*", "shared_space_bucket_arn/*"}

    listing = _execution_statement("SourceDataList")
    assert "s3:GetObject" not in listing["Action"], (
        "the object-level read has drifted into the bucket-level statement, whose resources are "
        "the buckets themselves — a head against those ARNs is denied"
    )


def test_the_restore_reads_the_vault_with_grants_that_already_exist():
    """The other half of FR-006, and equally a record that nothing was added: the lookup lists
    the archive prefix and reads `_manifest.json` out of it, and SPEC-169 already granted both
    for the rollback and the copy."""
    vault_list = _execution_statement("ArchiveVaultList")
    vault_read = _execution_statement("ArchiveVaultWrite")

    assert "s3:ListBucket" in vault_list["Action"]
    assert "s3:GetObject" in vault_read["Action"]


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
