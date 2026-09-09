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
    # PORTAL_ARCHIVE is gone: the browser's one archive privilege was an enqueue, and the API is
    # the only writer now. Its absence is asserted below rather than by reading a missing file.
    assert not PORTAL_ARCHIVE.exists(), "the browser's archive enqueue grant is retired"

    for path in (PORTAL_PERSONAL, PORTAL_SHARED):
        body = _read(path)

        assert "archive_bucket" not in body, f"{path.name} names the archive bucket"
        assert "prod-archive" not in body, f"{path.name} names the archive bucket"


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


# ── SPEC-139 parity: no new Resource "*" anywhere in this plane ──────────────
