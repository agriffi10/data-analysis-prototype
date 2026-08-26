"""The feature-flag document's validator, and the reachability it silently depends on (SPEC-162).

Two subjects, and they are here together because they fail the same way. A feature flag is
presentation-only and its browser read falls back to all-on when anything goes wrong, so a
document nobody can fetch and a healthy environment with every feature enabled look
IDENTICAL from the app. Nothing in the SPA can tell them apart, and no user would report it.
That is what makes the checks below worth their weight:

  * The validator's own tests, including a document it must reject and a workflow parse that
    must not go trivial (SPEC-153's shape — assert the coupling, then assert the parse found
    something).
  * FR-008's three reachability assertions over infra this spec does NOT change. The whole
    argument for putting the document beside `_directory/usernames.json` is that CORS, the CSP
    `connect-src` entry and the bucket-policy allowlist are already in place — but "it already
    works" is a claim about three files, and a claim nothing checks is how a silent-fallback
    feature ships permanently broken. If one of these fails it is a finding to raise, not a
    licence to widen infra.
  * FR-003's deploy-role assertion, for the same reason in the other direction: the publish
    workflow adds no IAM, on the grounds that the deploy role already holds the bucket.

Lives under ``lambdas/`` because that is where pytest runs, alongside ``test_security_gates.py``
and ``test_deploy_matrix.py`` — the other files here that read the repo as data rather than
exercising a Lambda.

Attributes:
  ROOT: The repository root.
  FLAG_KEYS: Every flag, re-stated from the validator so a test cannot pass by agreeing
    with a mistake it imported. `dataExplorer` joined in SPEC-179 and `asyncFileOperations` in
    SPEC-190 — a key is added in six places and this is the one that fails if the validator was
    not one of them.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import validate_feature_flags as validator

FLAG_KEYS = (
    "files",
    "query",
    "sharedWorkspaces",
    "dataQuality",
    "dataExplorer",
    "asyncFileOperations",
)

DOCUMENT = ROOT / "config" / "feature-flags.json"
PUBLISH_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-config.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
PORTAL_POLICY = ROOT / "infra" / "modules" / "data" / "policies" / "portal-role-permissions.json.tftpl"
DEPLOY_POLICY = ROOT / "infra" / "modules" / "base" / "policies" / "github-actions-deploy.json.tftpl"
BUCKET_POLICY = ROOT / "infra" / "modules" / "data" / "policies" / "user-space-bucket-policy.json.tftpl"
DATA_S3 = ROOT / "infra" / "modules" / "data" / "s3.tf"
# connect-src is built at ROOT, not in the app module: the API's origin comes into
# existence there, and three consumers read the list where only CloudFront did before.
CLOUDFRONT = ROOT / "infra" / "main.tf"


def _valid_document() -> dict:
    """A minimal document the validator accepts, for tests that break exactly one thing.

    Args:
      None.

    Returns:
      A freshly-allocated valid document naming the same environment the repo's does.
    """
    return {
        "version": 1,
        "defaults": dict.fromkeys(FLAG_KEYS, True),
        "environments": {"prod": {}},
    }


# ── The checked-in document ──────────────────────────────────────────────────


def test_the_repo_document_is_valid():
    """The document in git passes, against the targets the publish workflow really declares."""
    targets = validator.read_upload_targets(PUBLISH_WORKFLOW.read_text())
    assert validator.validate_document(json.loads(DOCUMENT.read_text()), targets) == []


def test_the_document_names_exactly_the_known_flags():
    """FR-001: every flag named, each an explicit boolean, and no key the readers do not know."""
    defaults = json.loads(DOCUMENT.read_text())["defaults"]
    assert sorted(defaults) == sorted(FLAG_KEYS)
    assert all(isinstance(value, bool) for value in defaults.values())


# ── Reading the upload targets ───────────────────────────────────────────────


def test_the_publish_workflow_declares_its_targets_readably():
    """Guards the guard: a matrix that parses to nothing makes every cross-check vacuous.

    This is the check that would have caught a rename or a reformat of the matrix, which is
    the realistic way this stops working — nobody deletes a validator, they move a key.
    """
    assert validator.read_upload_targets(PUBLISH_WORKFLOW.read_text()) == {"prod"}


def test_an_unparseable_matrix_is_an_error_not_an_empty_set():
    """A workflow with no `environment_name:` entries must raise rather than validate nothing."""
    with pytest.raises(validator.ValidationError, match="no `environment_name:` upload targets"):
        validator.read_upload_targets("jobs:\n  publish:\n    steps: []\n")


def test_a_matrix_entry_with_no_bucket_var_is_an_error():
    """An entry declaring a destination that does not exist fails here, not at publish time.

    The workflow's own empty-bucket guard would catch it — correctly, and too late: a red
    deploy where a red PR check would do.
    """
    workflow = "        include:\n          - environment_name: staging\n          - environment_name: prod\n            bucket_var: B\n"
    with pytest.raises(validator.ValidationError, match="staging"):
        validator.read_upload_targets(workflow)


def test_the_bucket_var_check_does_not_accept_the_steps_reference():
    """`vars[matrix.bucket_var]` in a later step must not stand in for the declaration.

    The last matrix entry's text runs to the end of the file, so an unanchored search would
    find the steps block's reference and pass every entry forever.
    """
    workflow = (
        "        include:\n"
        "          - environment_name: prod\n"
        "    steps:\n"
        "      - env:\n"
        "          BUCKET: ${{ vars[matrix.bucket_var] }}\n"
    )
    with pytest.raises(validator.ValidationError, match="prod"):
        validator.read_upload_targets(workflow)


def test_a_github_environment_keyword_is_not_an_upload_target():
    """`environment:` is a GitHub Actions job keyword; only `environment_name:` declares a target.

    Matching the bare keyword would let an unrelated deployment-environment block masquerade
    as an upload target, and the bidirectional check would then be comparing the document
    against something that publishes nothing.
    """
    with pytest.raises(validator.ValidationError):
        validator.read_upload_targets("jobs:\n  publish:\n    environment: production\n")


# ── Validation is a hard error (FR-002) ──────────────────────────────────────


def test_an_unknown_flag_key_fails():
    """A typo'd flag would otherwise resolve to its compiled-in default and silently do nothing."""
    document = _valid_document()
    document["defaults"]["quries"] = True
    problems = validator.validate_document(document, {"prod"})
    assert any("unknown flag 'quries'" in p for p in problems)


def test_an_unknown_flag_key_in_an_environment_block_fails():
    """The same rule inside an override block, which is where a typo is likelier."""
    document = _valid_document()
    document["environments"]["prod"]["dataQaulity"] = False
    problems = validator.validate_document(document, {"prod"})
    assert any("environments.prod` has unknown flag 'dataQaulity'" in p for p in problems)


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None, [], {}])
def test_a_non_boolean_flag_value_fails(value):
    """`"true"` is truthy everywhere the document travels, so it must not be spellable.

    Accepting it would make the one spelling that cannot be turned OFF indistinguishable from
    the one that can — the exact failure FR-005's per-key fallback exists to contain, and it
    should never get as far as needing containing.
    """
    document = _valid_document()
    document["defaults"]["query"] = value
    problems = validator.validate_document(document, {"prod"})
    assert any("`defaults.query` must be true or false" in p for p in problems)


def test_an_unknown_version_fails():
    """A shape this build has no reader for is not one it should publish."""
    document = _valid_document()
    document["version"] = 2
    assert any("unknown version 2" in p for p in validator.validate_document(document, {"prod"}))


@pytest.mark.parametrize("version", [True, False, "1", 1.5, None, [1]])
def test_a_version_that_is_not_a_plain_integer_fails(version):
    """`True` is the one that matters, and a bare membership test would have accepted it.

    `isinstance(True, int)` is True and `hash(True) == hash(1)` in Python, so `True in {1}`
    is True — while the browser compares `version !== 1` in JS, where `true !== 1`. A
    document that passes validation and is then refused by every reader is the silent
    failure this validator exists to prevent, and it is invisible: the app falls back to
    all-on, which is what a healthy environment looks like.
    """
    document = _valid_document()
    document["version"] = version
    assert any("unknown version" in p for p in validator.validate_document(document, {"prod"}))


@pytest.mark.parametrize("missing", FLAG_KEYS)
def test_defaults_missing_any_flag_fails(missing):
    """`defaults` is total where an environment block is partial — an omission is a missing answer."""
    document = _valid_document()
    del document["defaults"][missing]
    problems = validator.validate_document(document, {"prod"})
    assert any(f"`defaults` is missing the {missing!r} flag" in p for p in problems)


def test_an_environment_block_with_no_upload_target_fails():
    """A block nobody publishes is a defect, not a default — it would never take effect."""
    document = _valid_document()
    document["environments"]["staging"] = {"query": False}
    problems = validator.validate_document(document, {"prod"})
    assert any("environment 'staging' has no upload target" in p for p in problems)


def test_an_upload_target_with_no_environment_block_fails():
    """The other direction: a target publishing only defaults, under a name someone configured."""
    problems = validator.validate_document(_valid_document(), {"prod", "staging"})
    assert any("uploads to 'staging', which the document does not name" in p for p in problems)


def test_a_partial_environment_block_is_allowed():
    """FR-001: an environment may override any subset; what it omits comes from `defaults`."""
    document = _valid_document()
    document["environments"]["prod"] = {"query": False}
    assert validator.validate_document(document, {"prod"}) == []


@pytest.mark.parametrize("document", [[], "flags", 3, None])
def test_a_document_that_is_not_an_object_fails(document):
    """Guards the guard the other way: the validator must not crash into a pass on junk."""
    assert validator.validate_document(document, {"prod"}) != []


def test_every_problem_is_reported_not_just_the_first():
    """One run must name everything that has to change, or fixing the file becomes a loop."""
    document = _valid_document()
    document["version"] = 99
    del document["defaults"]["files"]
    document["defaults"]["query"] = "true"
    assert len(validator.validate_document(document, {"prod"})) >= 3


# ── The publish pipeline (FR-003) ────────────────────────────────────────────


def test_the_publish_workflow_addresses_one_exact_key():
    """No sync and no delete: `_directory/usernames.json` is one prefix over in this bucket.

    A mis-scoped reconcile that removed the username directory would break typeahead
    everywhere (SPEC-146/147) for a feature nothing user-facing depends on yet.
    """
    text = PUBLISH_WORKFLOW.read_text()
    # Comments stripped: this workflow's own commentary NAMES the two flags it refuses to
    # use, so a whole-file search would find them and pass for the wrong reason.
    commands = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "_config/feature-flags.json" in commands
    assert "aws s3 sync" not in commands
    assert "--delete" not in commands
    assert "--cache-control 'no-cache'" in commands


def test_the_publish_workflow_validates_before_it_uploads():
    """A failed validation must stop the workflow before any AWS call.

    Anchored on the STEP, not on the script path. The path also appears in the `on: paths:`
    trigger near the top of the file, so an index of the bare path is always the trigger's —
    which would leave every assertion here passing after someone moved the validate step
    below the upload. A guard that cannot fail is the thing it is guarding against.
    """
    text = PUBLISH_WORKFLOW.read_text()
    steps = text[text.index("\n    steps:") :]
    validate_at = steps.index("- name: Validate the flag document")
    assert validate_at < steps.index("aws s3 cp")
    assert validate_at < steps.index("configure-aws-credentials")


def test_that_ordering_check_is_not_reading_the_trigger():
    """Guards the guard above: the bare script path appears BEFORE the steps block."""
    text = PUBLISH_WORKFLOW.read_text()
    assert text.index("scripts/validate_feature_flags.py") < text.index("\n    steps:")


def test_ci_validates_the_document_on_every_pull_request():
    """The first of the two runs. Without it a bad document is caught only at publish time."""
    assert "scripts/validate_feature_flags.py" in CI_WORKFLOW.read_text()


def test_the_deploy_role_already_covers_the_user_space_bucket():
    """FR-003: the publish adds NO deploy-role statement, on the claim that one already covers it.

    Asserted rather than assumed. If this ever fails it is the finding — the response is to
    understand why the grant moved, not to add a statement here.

    ONE statement must carry both halves. Two independent substring checks would still pass
    if a future edit left `s3:*` on some other bucket and narrowed the user-space grant to a
    read — which is precisely the change that would break the publish while looking fine.
    """
    policy = json.loads(DEPLOY_POLICY.read_text().replace("${", "@{"))
    writes = {"s3:*", "s3:PutObject"}
    covering = [
        statement
        for statement in policy["Statement"]
        if statement["Effect"] == "Allow"
        and writes & set(_as_list(statement["Action"]))
        and "@{user_space_bucket_arn}/*" in _as_list(statement["Resource"])
    ]
    assert covering, "no single deploy-role statement both writes objects and covers the user-space bucket"


def _as_list(value: object) -> list:
    """A policy field that may be a scalar or a list, always as a list.

    Args:
      value: An `Action` or `Resource` field.

    Returns:
      The field's entries.
    """
    return value if isinstance(value, list) else [value]


# ── Portal-role IAM ──────────────────────────────────────────────────────────


def test_the_portal_role_reads_the_flag_document_and_nothing_more():
    """One GetObject on `_config/*`. No write, and no ListBucket widening.

    The absent widening is what keeps the document invisible to the file browser, which is
    why it is asserted here and not merely intended: `_config` is also in the SPA's two
    protected-folder lists, but those govern the user's own prefix and cannot reach a
    bucket-root folder at all.
    """
    policy = json.loads(
        PORTAL_POLICY.read_text()
        .replace("${bucket_arn}", "arn:aws:s3:::bucket")
        .replace("$${aws:PrincipalTag/username}", "USER")
    )
    statements = {s["Sid"]: s for s in policy["Statement"]}

    flags = statements["ReadTheFeatureFlags"]
    assert flags["Effect"] == "Allow"
    assert flags["Action"] == "s3:GetObject"
    assert flags["Resource"] == "arn:aws:s3:::bucket/_config/*"

    for statement in policy["Statement"]:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
        touches_config = any("_config" in r for r in resources)
        if touches_config:
            assert actions == ["s3:GetObject"], f"{statement['Sid']} grants more than a read under _config/"
        if "s3:ListBucket" in actions:
            assert "s3:prefix" in json.dumps(statement.get("Condition", {})), (
                f"{statement['Sid']} lists the bucket without a prefix condition — `_config/` would become visible"
            )


# ── FR-008: the reachability this spec depends on and does not change ────────


def test_the_user_space_bucket_allows_browser_gets():
    """Without CORS the browser fetch fails before it reaches IAM, and the app falls back all-on."""
    text = DATA_S3.read_text()
    marker = 'resource "aws_s3_bucket_cors_configuration" "user_space"'
    assert marker in text
    block = text.split(marker, 1)[1].split("\nresource ", 1)[0]
    assert '"GET"' in block, "the user-space CORS rule no longer allows GET"
    assert "var.app_url" in block, "the deployed app origin is no longer an allowed origin"


def test_the_user_space_bucket_host_is_in_the_csp_connect_src():
    """The enforcing CSP governs this fetch. An omitted host is SPEC-140's day-long sign-in break."""
    connect_src = CLOUDFRONT.read_text().split("csp_connect_src = join(", 1)[1].split("])", 1)[0]
    # `local.`, not `var.`: the list is built at root now, where the bucket name is a local
    # rather than a module input. The host it names is unchanged.
    assert "${local.user_space_bucket_name}.s3.${var.aws_region}.amazonaws.com" in connect_src


def test_the_portal_role_is_on_the_bucket_policy_allowlist():
    """A resource Deny overrides an identity Allow, so the grant above is only real while this holds.

    The list is hand-maintained. This assertion exists so an edit to it fails a test rather
    than silently killing the feature into its all-on fallback.
    """
    policy = BUCKET_POLICY.read_text()
    deny = json.loads(policy.replace("${", "@{"))["Statement"][0]
    assert deny["Effect"] == "Deny"
    assert "@{portal_role_arn}" in deny["Condition"]["StringNotLike"]["aws:PrincipalArn"]
