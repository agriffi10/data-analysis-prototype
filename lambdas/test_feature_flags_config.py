"""The feature-flag document's validator, and the reachability it silently depends on.

A document nobody can fetch and a healthy environment with every feature enabled look identical
from the app, which is what makes these checks worth their weight. The full argument, and the
rule that a failed reachability assertion is a finding rather than a licence to widen infra, is
in ``apps/portal/info/runtime-configuration.md``.

Lives under ``lambdas/`` because that is where pytest runs.

Attributes:
  ROOT: The repository root.
  FLAG_KEYS: Every flag, re-stated from the validator so a test cannot pass by agreeing with a
    mistake it imported — a key is added in eight places, and this is the one that fails if the
    validator was not one of them.
"""

import json
import pathlib
import sys

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
    "resultsConversion",
    "archive",
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
ROOT_MAIN = ROOT / "infra" / "main.tf"


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


# ── Validation is a hard error (FR-002) ──────────────────────────────────────


def test_an_unknown_flag_key_fails():
    """A typo'd flag would otherwise resolve to its compiled-in default and silently do nothing."""
    document = _valid_document()
    document["defaults"]["quries"] = True
    problems = validator.validate_document(document, {"prod"})
    assert any("unknown flag 'quries'" in p for p in problems)


