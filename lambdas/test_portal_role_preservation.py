"""The preservation claim, checked artefact by artefact rather than asserted once.

Why the no-change guard is a named-absence assertion plus a git baseline rather than a snapshot,
and why the one template this change edits needs a literal second copy of its own, are in
``infra/info/deploy-role-iam.md``.

Attributes:
  REPO: The repository root.
  INFRA: The IaC tree.
  BASELINE_COMMIT: The commit these templates are pinned to.
  ADDED_SINCE_BASELINE: Permission templates added since, named one by one.
  TRUST: The one template this spec edits.
  API_ROLE_ARN: A rendered API execution role ARN.
  PORTAL_ROLE_ARN: A rendered portal role ARN.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"

BASELINE_COMMIT = "b01930c8"

#: Permission templates added since the baseline, each named deliberately. Empty today. A new
#: plane adds its name here in the same commit that adds its template — the point is not to
#: forbid additions but to stop one arriving unread, since a byte comparison against the baseline
#: cannot see a file that was not in it.
ADDED_SINCE_BASELINE: frozenset[str] = frozenset()

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

    added = present - baseline - ADDED_SINCE_BASELINE
    assert not added, (
        f"a portal-role permission template was ADDED and is un-baselined: {sorted(added)}. "
        "Additions are allowed — Arc A adds a tenth — but a new template is the one direction "
        "no byte comparison covers, and only the named-absence sweep is looking at it. Name it "
        "in ADDED_SINCE_BASELINE so it is an argued edit rather than a silent one."
    )

    for path in sorted(baseline):
        assert _git("show", f"{BASELINE_COMMIT}:{path}") == (REPO / path).read_text(), (
            f"{path} differs from its pre-change bytes"
        )


# ── FR-003: the trust policy ──────────────────────────────────────────────────


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


# ── FR-003: the deploy grant, verified rather than assumed ────────────────────


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


def _plan_root_variable(name: str, value: str) -> bool:
    """Plans one root variable declaration with a value, and reports whether it was refused.

    Extracted into a scratch module rather than planned in place: the root needs a provider and a
    backend, and this is about one validation condition. Extracted, the module declares no
    provider, so the init is offline and no credentials are involved. The same shape the provider
    block's own refusal test already uses.

    Args:
      name: The root variable to plan.
      value: The value to plan it with.

    Returns:
      True if OpenTofu refused the value.

    Raises:
      AssertionError: If the declaration cannot be extracted, or tofu is unavailable — a skip
        here would read as coverage this suite would not have.
    """
    tofu = shutil.which("tofu")
    assert tofu, "OpenTofu is not on PATH — this assertion cannot be skipped into passing"

    source = (INFRA / "variables.tf").read_text()
    match = re.search(rf'variable\s+"{name}"\s*\{{', source)
    assert match, f"root no longer declares {name}"
    index, depth = source.index("{", match.start()), 0
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    declaration = source[match.start() : index + 1]

    with tempfile.TemporaryDirectory() as scratch:
        pathlib.Path(scratch, "variables.tf").write_text(declaration + "\n")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "TF_IN_AUTOMATION": "1",
            f"TF_VAR_{name}": value,
        }
        setup = subprocess.run(  # noqa: S603
            [tofu, "init", "-backend=false", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )
        assert setup.returncode == 0, (
            f"tofu init failed in the scratch module:\n{setup.stdout}\n{setup.stderr}"
        )
        plan = subprocess.run(  # noqa: S603
            [tofu, "plan", "-input=false"],
            cwd=scratch, env=environment, capture_output=True, text=True, check=False,
        )
    return plan.returncode != 0
