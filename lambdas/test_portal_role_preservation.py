"""The preservation claim, checked artefact by artefact rather than asserted once.

The arc's central claim is that moving a call from the browser to the API rewrites **no** existing
authorization artefact. That is only worth making if each one is checked, so this file walks them:
the nine permission templates that must not have moved, the trust policy that gains exactly one
statement, the tag key set that must agree across three places, the deploy grant that must already
exist, and the two buckets whose reachability must be unchanged.

**The no-change guard is a NAMED-ABSENCE assertion plus a git baseline, and not a snapshot.** A
test that captures the rendered templates during the build and diffs them against themselves
compares a copy of the answer with itself and passes whatever happens. So the byte comparison is
against the **pre-change blob in git**, and the file set is enumerated from that same commit —
a glob of the working tree with a length check passes a deletion, because the deleted file is
simply not in the glob.

**The federated statement needs its own baseline, and this is the one place that is easy to
miss.** The blob comparison deliberately EXCLUDES the trust template, because this spec edits it —
so "the existing statement is untouched" has nothing to compare against. Asserting that the string
``sts:AssumeRoleWithWebIdentity`` still appears would survive someone changing that statement's
principal, its conditions, or dropping ``sts:TagSession`` from it. It is asserted whole, against a
literal written here — a deliberate second copy, for the same reason the CSP terms are one.

Attributes:
  REPO: The repository root.
  INFRA: The IaC tree.
  BASELINE_COMMIT: The commit these templates are pinned to.
  TRUST: The one template this spec edits.
  API_ROLE_ARN: A rendered API execution role ARN.
  PORTAL_ROLE_ARN: A rendered portal role ARN.
  IDENTITY_POOL_ID: A rendered identity pool id.
  EXPECTED_FEDERATED_STATEMENT: The browser's trust statement, whole, as it must remain for as
    long as both credential paths run.
"""

import json
import pathlib
import re
import shutil
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"

BASELINE_COMMIT = "b01930c8"

TRUST = "infra/modules/data/policies/portal-role-trust.json.tftpl"

API_ROLE_ARN = "arn:aws:iam::696000197480:role/dat-prod-api-role"
PORTAL_ROLE_ARN = "arn:aws:iam::696000197480:role/dat-portal-user-role"
IDENTITY_POOL_ID = "us-east-1:11111111-2222-3333-4444-555555555555"

EXPECTED_FEDERATED_STATEMENT = {
    "Effect": "Allow",
    "Principal": {"Federated": "cognito-identity.amazonaws.com"},
    "Action": ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
    "Condition": {
        "StringEquals": {"cognito-identity.amazonaws.com:aud": IDENTITY_POOL_ID},
        "ForAnyValue:StringLike": {"cognito-identity.amazonaws.com:amr": "authenticated"},
    },
}


def _git(*args: str) -> str:
    """Runs a git command in the repository, failing loudly rather than skipping.

    A guard that cannot read its baseline has not passed — it has not run, and "did not run" is
    never "clean". CI checks out full history for exactly this.

    Args:
      *args: The git arguments.

    Returns:
      The command's stdout.

    Raises:
      AssertionError: If git fails, including when the baseline commit is unreachable because
        the checkout was shallow.
    """
    git = shutil.which("git") or "git"
    result = subprocess.run(  # noqa: S603
        [git, *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed: {result.stderr.strip()}\n"
        f"If the baseline commit is unreachable, the checkout is shallow — CI sets "
        f"fetch-depth: 0 for this guard, and a shallow one must fail rather than skip."
    )
    return result.stdout


def _tofu_default(name: str) -> str:
    """Reads a root variable's declared default.

    Args:
      name: The variable name.

    Returns:
      The default, as written.

    Raises:
      AssertionError: If the variable or its default is gone.
    """
    source = (INFRA / "variables.tf").read_text()
    block = re.search(rf'variable "{name}" \{{(.*?)\n\}}', source, re.DOTALL)
    assert block, f"root no longer declares {name}"
    default = re.search(r"default\s*=\s*\"?([^\"\n]+)\"?", block.group(1))
    assert default, f"{name} has no default"
    return default.group(1).strip()


def _expected_tag_keys() -> list[str]:
    """The session tag key set, expanded from the two Tofu variables that size it.

    Args:
      None.

    Returns:
      The tag key list, username first.

    Raises:
      AssertionError: If either variable is gone.
    """
    slots = int(_tofu_default("max_shared_memberships"))
    return [_tofu_default("principal_tag_key")] + [
        f"shared_space_{k}" for k in range(1, slots + 1)
    ]


def _rendered_trust() -> dict:
    """Renders the trust policy with plausible values.

    Rendered rather than read as a template: a placeholder can expand into something a text scan
    would not recognise, and this document must parse as JSON to be a trust policy at all.

    Args:
      None.

    Returns:
      The rendered policy.

    Raises:
      AssertionError: If the rendered document is not valid JSON.
    """
    rendered = (
        (REPO / TRUST)
        .read_text()
        .replace("${identity_pool_id}", IDENTITY_POOL_ID)
        .replace("${api_execution_role_arn}", API_ROLE_ARN)
        .replace("${session_tag_keys}", json.dumps(_expected_tag_keys()))
    )
    return json.loads(rendered)


def _permission_templates(commit: str) -> set[str]:
    """Every portal-role permission template at a commit, as repo-relative paths.

    The trust template is excluded because it is the one this spec edits.

    Args:
      commit: The commit to enumerate at.

    Returns:
      The set of paths.

    Raises:
      AssertionError: If git fails.
    """
    listed = _git("ls-tree", "-r", "--name-only", commit, "--", "infra/modules")
    return {
        path
        for path in listed.splitlines()
        if re.fullmatch(r"infra/modules/[^/]+/policies/portal-role-.*\.json\.tftpl", path)
        and path != TRUST
    }


# ── FR-008: what stays true ───────────────────────────────────────────────────


def test_ACCEPTED_the_portal_role_permission_templates_are_byte_identical_to_the_baseline() -> None:
    """The preservation claim, as bytes. Nine templates, none of them touched.

    **If this reddens, a portal-role permission template changed.** That is not automatically
    wrong — Arc A adds a tenth, and a later plane will add an eleventh — but it is never the
    thing to silence. Argue the change in the spec that makes it, record what the widening is,
    and move ``BASELINE_COMMIT`` forward with a written note. **Do not delete this test, and do
    not bump the commit to make a red run green**: re-baselining is exactly how a widening the
    named-absence guard below exists to catch gets absorbed without anyone reading it.

    The file set comes from the baseline commit, not from a glob of the working tree. A glob with
    a length check passes a DELETION, because a deleted file is simply not in the glob.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a template was deleted, or differs from its pre-change bytes.
    """
    baseline = _permission_templates(BASELINE_COMMIT)
    assert len(baseline) >= 9, (
        f"the baseline holds {len(baseline)} permission templates — the enumeration is broken, "
        "and an empty one would make every comparison below vacuous"
    )

    present = {
        str(path.relative_to(REPO))
        for path in INFRA.glob("modules/*/policies/portal-role-*.json.tftpl")
        if str(path.relative_to(REPO)) != TRUST
    }
    missing = baseline - present
    assert not missing, f"a portal-role permission template was deleted: {sorted(missing)}"

    for path in sorted(baseline):
        assert _git("show", f"{BASELINE_COMMIT}:{path}") == (REPO / path).read_text(), (
            f"{path} differs from its pre-change bytes"
        )


def test_no_permission_template_gained_a_resource_an_sts_action_or_the_api_role() -> None:
    """The named-absence half. It catches a widening a re-baselined snapshot would absorb.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any permission template reaches STS or names the API's role.
    """
    for path in sorted(INFRA.glob("modules/*/policies/portal-role-*.json.tftpl")):
        if str(path.relative_to(REPO)) == TRUST:
            continue
        source = path.read_text()
        assert "sts:" not in source, f"{path.name} reaches STS"
        assert "api-role" not in source, f"{path.name} names the API's execution role"
        assert "api_execution_role" not in source, f"{path.name} names the API's execution role"


def test_the_archive_bucket_stays_unreachable_from_the_portal_role() -> None:
    """Nothing here changes it, and the absence is what says so.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a portal-role policy names the archive bucket.
    """
    for path in sorted(INFRA.glob("modules/*/policies/portal-role-*.json.tftpl")):
        assert "archive_bucket" not in path.read_text(), (
            f"{path.name} names the archive bucket — the archive is reachable only through its "
            "own control plane, and a portal-role grant would make it reachable directly"
        )


def test_the_shared_space_bucket_still_carries_no_bucket_policy() -> None:
    """Stated because a reader will look for an allowlist there and find nothing.

    Its absence is otherwise indistinguishable from an oversight. Access to that bucket is
    identity-policy-only, which is what makes the membership tag set the entire gate.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a bucket policy appeared for it.
    """
    policies = {
        path.name for path in INFRA.glob("modules/*/policies/*bucket-policy.json.tftpl")
    }
    assert not any("shared-space" in name for name in policies), (
        f"a shared-space bucket policy appeared: {sorted(policies)}"
    )


# ── FR-003: the trust policy ──────────────────────────────────────────────────


def test_the_browsers_trust_statement_is_untouched_asserted_WHOLE() -> None:
    """Both paths run side by side for the whole arc, so this statement outlives this spec.

    Asserted as a complete value rather than by the presence of a substring: the blob baseline
    above deliberately excludes this file, so a substring check is all that would stand between
    this statement and a changed principal, a dropped action or a relaxed condition.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any part of it moved.
    """
    federated = [
        statement
        for statement in _rendered_trust()["Statement"]
        if "Federated" in statement.get("Principal", {})
    ]
    assert len(federated) == 1
    assert federated[0] == EXPECTED_FEDERATED_STATEMENT


def test_the_api_statement_carries_BOTH_actions_in_the_same_statement() -> None:
    """Either alone renders, plans, applies and unit-tests green, then fails at runtime.

    The refusal names neither the tag nor the missing action, so it reads as a permissions bug in
    whichever feature happened to call first.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the statement is missing, split, or admits the wrong principal.
    """
    api = [
        statement
        for statement in _rendered_trust()["Statement"]
        if "AWS" in statement.get("Principal", {})
    ]
    assert len(api) == 1, f"{len(api)} statements admit an AWS principal"

    assert set(api[0]["Action"]) == {"sts:AssumeRole", "sts:TagSession"}
    assert api[0]["Principal"]["AWS"] == API_ROLE_ARN
    assert api[0]["Effect"] == "Allow"

    for wrong in ("root", "*", "deploy-role"):
        assert wrong not in api[0]["Principal"]["AWS"], (
            "the statement admits something broader than the API's execution role"
        )


def test_the_statement_bounds_the_tag_keys_and_forbids_transitive_ones() -> None:
    """A ceiling on which keys may appear, and an absence requirement on transitive ones.

    Neither constrains a tag's VALUE and IAM offers no way to — the unspoofability argument rests
    entirely on the value coming from a claim of a signature-verified token. The transitive
    condition's value is the STRING "true"; a JSON boolean is a malformed policy at apply.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either condition is missing or malformed.
    """
    api = next(
        statement
        for statement in _rendered_trust()["Statement"]
        if "AWS" in statement.get("Principal", {})
    )

    assert api["Condition"]["ForAllValues:StringEquals"]["sts:TagKeys"] == _expected_tag_keys()
    assert api["Condition"]["Null"]["sts:TransitiveTagKeys"] == "true"
    assert isinstance(api["Condition"]["Null"]["sts:TransitiveTagKeys"], str)


def test_the_tag_key_set_is_the_same_in_the_trust_policy_and_the_identity_pool() -> None:
    """A fourth copy of the slot name arrived with this spec, so it joins the comparison.

    The name is written in the Identity Pool's map, in the portal role's shared-space policy, in
    the Python layer — and now in this statement's key list. A drifted list refuses the whole
    assume at runtime with nothing offline to show it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two sets differ.
    """
    pool = (INFRA / "modules" / "auth" / "identity-pool.tf").read_text()
    block = re.search(r"principal_tags\s*=\s*merge\((.*?)\n\s*\)", pool, re.DOTALL)
    assert block, "no principal_tags merge() was found — this comparison has no subject"

    literal = re.search(r"\{\s*([A-Za-z_][\w]*)\s*=\s*\"([^\"]+)\"\s*\}", block.group(1))
    comprehension = re.search(r':\s*"([^"]*\$\{k\}[^"]*)"\s*=>', block.group(1))
    assert literal and comprehension, "the principal-tag map's shape changed"

    slots = int(_tofu_default("max_shared_memberships"))
    declared = [literal.group(1)] + [
        comprehension.group(1).replace("${k}", str(k)) for k in range(1, slots + 1)
    ]

    assert declared == _expected_tag_keys()


def test_the_statement_is_rendered_from_the_variables_rather_than_transcribed() -> None:
    """Structural, so a hand-written list cannot pass by happening to match today.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the key list stops being built from the two variables.
    """
    iam = (INFRA / "modules" / "data" / "iam.tf").read_text()
    assert "var.principal_tag_key" in iam
    assert "var.max_shared_memberships" in iam
    assert re.search(r"session_tag_keys\s*=\s*jsonencode", iam), (
        "the tag key list is no longer computed"
    )


def test_the_honest_limit_is_recorded_where_a_reader_will_be() -> None:
    """The template cannot carry it: no `.json.tftpl` here does, and it must parse as JSON.

    So the note lives beside the `templatefile()` call. This asserts it is actually there,
    because "state the limit honestly" is a requirement and an unwritten one is indistinguishable
    from a forgotten one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the note is gone.
    """
    iam = (INFRA / "modules" / "data" / "iam.tf").read_text()
    assert "does NOT" in iam and "VALUES" in iam, (
        "the note that sts:TagKeys constrains keys and not values is gone from iam.tf"
    )
    assert "signature-verified" in iam


# ── FR-003: the deploy grant, verified rather than assumed ────────────────────


def test_the_deploy_role_can_already_rewrite_the_portal_roles_trust_policy() -> None:
    """No new resource type is created by this spec, and this is what says so out loud.

    "It needed no expansion" and "we forgot to check" are indistinguishable in a diff. A later
    narrowing of this grant reddens here rather than at the next apply.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the grant is gone or no longer scoped to the portal role.
    """
    deploy = (
        INFRA / "modules" / "base" / "policies" / "github-actions-deploy.json.tftpl"
    ).read_text()
    document = json.loads(
        deploy.replace("${portal_role_arn}", PORTAL_ROLE_ARN).replace(
            "${deploy_role_arn}", "arn:aws:iam::696000197480:role/dat-deploy-role"
        )
    )

    granting = [
        statement
        for statement in document["Statement"]
        if "iam:UpdateAssumeRolePolicy"
        in (
            [statement["Action"]]
            if isinstance(statement.get("Action"), str)
            else statement.get("Action", [])
        )
        and PORTAL_ROLE_ARN
        in (
            [statement["Resource"]]
            if isinstance(statement.get("Resource"), str)
            else statement.get("Resource", [])
        )
    ]
    assert granting, (
        "the deploy role can no longer rewrite the portal role's trust policy, so the second "
        "statement cannot be applied"
    )


# ── FR-001: the role is the existing one ──────────────────────────────────────


def test_the_api_assumes_the_EXISTING_portal_role_and_creates_none() -> None:
    """Reusing the role is what keeps the bucket policy's hand-maintained allowlist correct.

    That allowlist Denies every principal whose ARN is not on it, and it already names this role.
    An assumed-role request resolves to the role's IAM ARN rather than the session ARN, so
    assuming the same role keeps the same entry valid — and this repo has already been bitten by
    a principal missing from that list.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a new role appeared, or the function is pointed at anything else.
    """
    main = (INFRA / "main.tf").read_text()
    api_block = main[main.index('module "api" {') : main.index("\n}\n", main.index('module "api" {'))]
    assert re.search(r"portal_role_arn\s*=\s*local\.portal_role_arn", api_block), (
        "the API is not pointed at the existing portal role"
    )

    api_module = "\n".join(
        path.read_text() for path in sorted((INFRA / "modules" / "api").glob("*.tf"))
    )
    roles = re.findall(r'resource "aws_iam_role" "(\w+)"', api_module)
    assert roles == ["api"], (
        f"modules/api creates {roles} — the portal role is REUSED, never minted here"
    )


def test_the_execution_role_arn_is_built_the_same_way_in_both_places() -> None:
    """Constructed at root and again inside the module, so the two must agree.

    That duplication is the cost of keeping the value known at plan time; this is what stops it
    becoming a silent mismatch that admits nobody.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two constructions diverge.
    """
    main = (INFRA / "main.tf").read_text()
    root = re.search(
        r"api_execution_role_arn\s*=\s*\"arn:aws:iam::\$\{[^}]+\}:role/([^\"]+)\"", main
    )
    assert root, "root no longer constructs the API execution role ARN"

    lambda_tf = (INFRA / "modules" / "api" / "lambda.tf").read_text()
    function_name = re.search(r'function_name\s*=\s*"([^"]+)"', lambda_tf)
    role_name = re.search(r'name\s*=\s*"(\$\{local\.function_name\}[^"]*)"', lambda_tf)
    assert function_name and role_name, "the API module's naming changed shape"

    module_side = role_name.group(1).replace(
        "${local.function_name}", function_name.group(1)
    )
    assert root.group(1) == module_side, (
        f"root builds {root.group(1)!r} and the module builds {module_side!r}"
    )


def test_the_session_length_is_inside_the_roles_own_ceiling() -> None:
    """A shorter ceiling on the role plans green, applies green, and breaks every request.

    Absent means AWS's default of one hour, which is exactly what is requested. It cannot be
    RAISED either: the function runs on an assumed-role session of its own, so this call is role
    chaining, which AWS caps at one hour and fails rather than clamps.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the role declares a ceiling below the requested duration.
    """
    iam = (INFRA / "modules" / "data" / "iam.tf").read_text()
    declared = re.search(r"max_session_duration\s*=\s*(\d+)", iam)
    if declared is not None:
        assert int(declared.group(1)) >= 3600, (
            f"the portal role caps a session at {declared.group(1)}s, below the hour the API "
            "requests — every request would fail at runtime with nothing in the plan to warn it"
        )


@pytest.mark.parametrize("name", ["principal_tag_key", "max_shared_memberships"])
def test_the_variables_that_size_the_tag_set_refuse_a_value_that_would_break_it(name) -> None:
    """A default guards nothing on its own: an empty repo variable overrides one.

    Args:
      name: The variable to check.

    Returns:
      None.

    Raises:
      AssertionError: If the variable carries no validation.
    """
    source = (INFRA / "variables.tf").read_text()
    block = re.search(rf'variable "{name}" \{{(.*?)\n\}}', source, re.DOTALL)
    assert block, f"root no longer declares {name}"
    assert "validation {" in block.group(1), (
        f"{name} has no validation — an empty TF_VAR satisfies a required variable AND overrides "
        "a default, so the absence of one guards nothing"
    )
