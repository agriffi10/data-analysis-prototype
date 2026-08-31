"""The preservation claim, checked artefact by artefact rather than asserted once.

Why the no-change guard is a named-absence assertion plus a git baseline rather than a snapshot,
and why the one template this change edits needs a literal second copy of its own, are in
``infra/info/deploy-role-iam.md``.

Attributes:
  REPO: The repository root.
  INFRA: The IaC tree.
  BASELINE_COMMIT: The commit these templates are pinned to.
  ADDED_SINCE_BASELINE: Permission templates added since, named one by one.
  RETIRED_SINCE_BASELINE: Permission templates removed since, named one by one.
  TRUST: The one template this spec edits.
  API_ROLE_ARN: A rendered API execution role ARN.
  PORTAL_ROLE_ARN: A rendered portal role ARN.
"""

import json
import pathlib
import re
import shutil
import subprocess

REPO = pathlib.Path(__file__).resolve().parent.parent
INFRA = REPO / "infra"

BASELINE_COMMIT = "b01930c8"

#: Permission templates added since the baseline, each named deliberately. Empty today. A new
#: plane adds its name here in the same commit that adds its template — the point is not to
#: forbid additions but to stop one arriving unread, since a byte comparison against the baseline
#: cannot see a file that was not in it.
ADDED_SINCE_BASELINE: frozenset[str] = frozenset()

#: Permission templates RETIRED since the baseline, each named deliberately, for the same reason
#: additions are named: a byte comparison cannot argue for a file's absence, so a deletion has to
#: be read by a person once. These seven were the browser's per-plane ``sqs:SendMessage`` grants.
#: They came off in the change that repointed the browser at the API, and they came off THERE
#: rather than later on purpose — the message's identity block becomes authoritative in the next
#: spec, and a trusted actor field plus a browser credential able to write the queue is
#: impersonation. The eighth grant, shared-space's, was one statement inside a template whose
#: other statements are membership grants; that template survives and its bytes are compared
#: below like every other.
#:
#: **Do not add to this to make a red run green.** A name here says someone decided the browser
#: should stop being able to do that thing.
RETIRED_SINCE_BASELINE: frozenset[str] = frozenset(
    {
        "infra/modules/archive/policies/portal-role-archive.json.tftpl",
        "infra/modules/data-quality/policies/portal-role-data-quality.json.tftpl",
        "infra/modules/file-ops/policies/portal-role-file-ops.json.tftpl",
        "infra/modules/file-send/policies/portal-role-file-send.json.tftpl",
        "infra/modules/notifications/policies/portal-role-notifications.json.tftpl",
        "infra/modules/table-builder/policies/portal-role-table-builder.json.tftpl",
        "infra/modules/table-share/policies/portal-role-table-share.json.tftpl",
    }
)

TRUST = "infra/modules/data/policies/portal-role-trust.json.tftpl"

#: The one PERMISSION template this change edits, exempted from the byte comparison and asserted
#: by content instead — the same treatment the trust template gets, and for the same reason: a
#: byte comparison can only say "changed", which is not an answer to "changed how".
EDITED = "infra/modules/shared-spaces/policies/portal-role-shared-space.json.tftpl"

#: The user-space permission template, exempted for the same reason and asserted by content in
#: ``test_the_user_space_template_gained_ONLY_the_shared_document_listing``. Its edit adds a
#: ``ListBucket`` for the two documents that belong to no user, without which their absence
#: branches answer ``AccessDenied`` instead of the empty list and the ``NotFound`` they promise.
LISTING_EDITED = "infra/modules/data/policies/portal-role-permissions.json.tftpl"

#: Every template the byte comparison skips because a test below reads it instead. **Adding a
#: name here without also adding that test is how a widening gets absorbed unread.**
CONTENT_ASSERTED = frozenset({EDITED, LISTING_EDITED})

API_ROLE_ARN = "arn:aws:iam::696000197480:role/dat-prod-api-role"
PORTAL_ROLE_ARN = "arn:aws:iam::696000197480:role/dat-portal-user-role"
IDENTITY_POOL_ID = "us-east-1:11111111-2222-3333-4444-555555555555"

EXPECTED_FEDERATED_STATEMENT = {
    "Effect": "Allow",
    "Principal": {"Federated": "cognito-identity.amazonaws.com"},
    "Action": ["sts:AssumeRoleWithWebIdentity", "sts:TagSession"],
    "Condition": {
        "StringEquals": {"cognito-identity.amazonaws.com:aud": IDENTITY_POOL_ID},
        "ForAnyValue:StringLike": {
            "cognito-identity.amazonaws.com:amr": "authenticated"
        },
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
        if re.fullmatch(
            r"infra/modules/[^/]+/policies/portal-role-.*\.json\.tftpl", path
        )
        and path != TRUST
    }


# ── FR-008: what stays true ───────────────────────────────────────────────────


def _statements_by_sid(body: str) -> dict[str, str]:
    """Splits a policy template into WHOLE statements, keyed by Sid.

    Whole statements, not their names. A Sid-set comparison says a statement is still called what
    it was called, which is not the same as it still saying what it said: deleting the
    ``Condition`` from a list grant leaves the Sid, the Action and the Resource untouched and
    turns "list the prefix your principal tag names" into "list the whole bucket" for every
    signed-in user.

    Split by text rather than parsed, because these templates carry ``%{ for }`` directives and
    are not JSON until Terraform renders them.

    Args:
      body: The template's text.

    Returns:
      Sid to the statement's collapsed text.

    Raises:
      None.
    """
    found = {}
    for chunk in re.split(r'(?=\{\s*\n\s*"Sid")', body):
        name = re.search(r'"Sid"\s*:\s*"([^"]+)"', chunk)
        if not name:
            continue
        # Cut at the statement's OWN closing brace. Splitting on the next statement makes the last
        # chunk absorb the document's closing brackets, and removing the final element then reads
        # as a change to its predecessor — punctuation presenting as a narrowed grant.
        depth, end = 0, len(chunk)
        for index, character in enumerate(chunk):
            if character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        found[name.group(1)] = re.sub(r"\s+", " ", chunk[:end]).strip()
    return found


def test_ACCEPTED_the_portal_role_permission_templates_are_byte_identical_to_the_baseline() -> (
    None
):
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
    missing = baseline - present - RETIRED_SINCE_BASELINE
    assert not missing, (
        f"a portal-role permission template was deleted: {sorted(missing)}"
    )

    # A name in the retirement set that is back on disk is a re-grant, and it would otherwise
    # read as tidy: the set would simply stop matching anything.
    resurrected = RETIRED_SINCE_BASELINE & present
    assert not resurrected, (
        f"a retired portal-role grant is back: {sorted(resurrected)}. The API is the only writer "
        "of these queues; a browser credential that can write one can forge an actor."
    )

    added = present - baseline - ADDED_SINCE_BASELINE
    assert not added, (
        f"a portal-role permission template was ADDED and is un-baselined: {sorted(added)}. "
        "Additions are allowed — Arc A adds a tenth — but a new template is the one direction "
        "no byte comparison covers, and only the named-absence sweep is looking at it. Name it "
        "in ADDED_SINCE_BASELINE so it is an argued edit rather than a silent one."
    )

    for path in sorted(baseline - RETIRED_SINCE_BASELINE - CONTENT_ASSERTED):
        assert _git("show", f"{BASELINE_COMMIT}:{path}") == (REPO / path).read_text(), (
            f"{path} differs from its pre-change bytes"
        )


# ── FR-003: the trust policy ──────────────────────────────────────────────────


def test_the_tag_key_set_is_the_same_in_the_trust_policy_and_the_permission_templates() -> (
    None
):
    """A fourth copy of the slot name arrived with this spec, so it joins the comparison.

    The name is written in the two portal-role permission templates, in the Python layer — and
    in this statement's key list. A drifted list refuses the whole assume at runtime with
    nothing offline to show it.

    THE DECLARED SIDE COMES FROM BOTH TEMPLATES, and that is not tidiness. The Identity Pool's
    ``principal_tags`` map used to be the single declaration of the whole set; it is retired,
    and the two halves landed in different files. ``username`` appears only in the permissions
    template and ``shared_space_${k}`` only in the shared-space one, so reading either alone
    drops half the comparison silently — and the half that would go is ``username``, the only
    one whose two sides do not already come from the same Tofu variable.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two sets differ, or if either template declares nothing.
    """
    slots = int(_tofu_default("max_shared_memberships"))

    permissions = (
        INFRA / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
    ).read_text()
    shared = (
        INFRA
        / "modules"
        / "shared-spaces"
        / "policies"
        / "portal-role-shared-space.json.tftpl"
    ).read_text()

    literal_keys = sorted(set(re.findall(r"aws:PrincipalTag/([A-Za-z_][\w]*)\}", permissions)))
    assert literal_keys, "the permissions template declares no principal tag — no subject"

    slot_template = re.findall(r"aws:PrincipalTag/([A-Za-z_]\w*)\$\{k\}\}", shared)
    assert slot_template, "the shared-space template declares no slot tag — no subject"
    assert len(set(slot_template)) == 1, f"more than one slot tag shape: {set(slot_template)}"

    declared = literal_keys + [f"{slot_template[0]}{k}" for k in range(1, slots + 1)]

    assert declared == _expected_tag_keys()


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
    api_block = main[
        main.index('module "api" {') : main.index("\n}\n", main.index('module "api" {'))
    ]
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


def test_ACCEPTED_a_recreated_api_role_would_not_redraw_the_trust_policy() -> None:
    """A tripwire for a trap nothing in this repo can currently detect.

    IAM stores a trust policy's principal as the role's **unique id**, not as the ARN written. If
    the API's execution role is ever destroyed and recreated — a project or environment rename, a
    taint — the rendered ARN string is unchanged, so Terraform sees no diff, never rewrites the
    trust policy, and every API request fails with a refusal that names nothing. The old unique id
    is simply dead.

    There is no offline assertion that can catch this and no plan that shows it. What this test
    pins is that the exposure is still the one described: exactly one statement in the trust policy
    names an AWS principal, so a reader chasing an inexplicable blanket refusal has one place to
    look. **If this reddens, do not delete it** — re-read the note above and decide whether the new
    shape has the same trap.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the trust policy's shape changed enough to invalidate the note.
    """
    principals = [
        statement
        for statement in _rendered_trust()["Statement"]
        if "AWS" in statement.get("Principal", {})
    ]
    assert len(principals) == 1


def test_the_shared_space_template_lost_ONLY_its_enqueue_statement() -> None:
    """The one edited permission template, checked by content because bytes cannot say how.

    Its other statements are the membership grants — the per-slot S3 allows, the list condition,
    the Glue grants and the three denies — and they are what a member's access to a shared space
    actually is. An edit that took one of those out with the enqueue would read as the same diff.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the enqueue statement survived, or any other statement did not.
    """

    before = _statements_by_sid(_git("show", f"{BASELINE_COMMIT}:{EDITED}"))
    after = _statements_by_sid((REPO / EDITED).read_text())

    assert len(before) >= 6, (
        "the sweep found nothing, so every comparison below is vacuous"
    )

    survived = set(before) & set(after)
    changed = [name for name in sorted(survived) if before[name] != after[name]]
    assert changed == [], (
        f"a statement that should be untouched changed: {changed}. These are the membership "
        "grants — what a member's access to a shared space actually IS — and an edit that "
        "narrowed or widened one would be the same diff as removing the enqueue."
    )

    assert set(before) - set(after) == {"SharedSpaceEnqueue"}, (
        f"this change should remove exactly the enqueue statement; it removed "
        f"{set(before) - set(after)}"
    )
    assert set(after) - set(before) == set(), (
        f"it should add none; it added {set(after) - set(before)}"
    )
    assert "sqs:SendMessage" not in (REPO / EDITED).read_text()


def test_the_user_space_template_gained_ONLY_the_shared_document_listing() -> None:
    """The user-space permission template, checked by content because bytes cannot say how.

    Its other statements are what personal-file access IS — the prefix-scoped object grant, the
    prefix-scoped list condition, the marker Deny and the archive-receipt Deny — and the one
    that matters most here is the neighbour: ``UserPrefixList``'s condition is the whole of one
    user's isolation from another's prefix. Adding a second list grant beside it is exactly the
    edit that could widen that one by accident, and a byte comparison would report both the same
    way.

    The addition itself exists because ``_directory/`` and ``_config/`` are under no caller's own
    prefix, so the role could read both documents and could not be told when one is absent — S3
    answers ``NoSuchKey`` only to a caller that can list. Without it the username directory raises
    instead of answering an empty list, and the flag document raises instead of ``NotFound``.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If anything but the listing statement changed, or it is not scoped to the
        two document prefixes.
    """
    before = _statements_by_sid(_git("show", f"{BASELINE_COMMIT}:{LISTING_EDITED}"))
    after = _statements_by_sid((REPO / LISTING_EDITED).read_text())

    assert len(before) >= 5, "the sweep found nothing, so every comparison below is vacuous"

    survived = set(before) & set(after)
    changed = [name for name in sorted(survived) if before[name] != after[name]]
    assert changed == [], (
        f"a statement that should be untouched changed: {changed}. UserPrefixList's condition is "
        "one user's isolation from another's prefix, and widening it would be this same diff."
    )

    assert set(before) - set(after) == set(), (
        f"this change should remove nothing; it removed {set(before) - set(after)}"
    )
    assert set(after) - set(before) == {"ListTheSharedDocuments"}, (
        f"it should add exactly the document listing; it added {set(after) - set(before)}"
    )

    added = after["ListTheSharedDocuments"]
    assert '"s3:ListBucket"' in added
    assert '"_directory/*"' in added and '"_config/*"' in added, (
        "the listing must name both document prefixes"
    )
    assert "PrincipalTag" not in added, (
        "this grant is deliberately not tag-scoped — the documents belong to no user — so it must "
        "not be written as though it were, which would make it silently empty"
    )
    assert '"Condition"' in added, (
        "the document listing must stay conditioned — unconditioned it is a bucket-wide list for "
        "every signed-in user, which would expose every username prefix by name"
    )
    assert re.findall(r'"(_[a-z]+/\*)"', added) == ["_directory/*", "_config/*"], (
        "the document listing may name those two prefixes and nothing else"
    )
