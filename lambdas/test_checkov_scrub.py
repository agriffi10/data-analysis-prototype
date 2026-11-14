"""The scrub that keeps a plan's sensitive values out of the published Checkov result.

Checkov copies each resource's planned values into `check_result.entity`, so a SecureString
parameter's value reaches its JSON result in plain text, and that result is uploaded as an
artifact. These tests drive the scrub on a result shaped as Checkov 3 writes one, and hold the
workflow to uploading only the scrubbed copy.

Attributes:
  ROOT: The repository root.
  SCRUB: The script under test, imported by path because `.github/scripts` is not a package.
  WORKFLOW: The infrastructure deploy workflow.
"""

import importlib.util
import json
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "checkov_scrub", ROOT / ".github" / "scripts" / "checkov_scrub.py"
)
SCRUB = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCRUB)
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-infra.yml"


def _secret() -> str:
    """Names the sentinel standing in for a planned secret. It is not secret-shaped.

    Args:
      None.

    Returns:
      A value no real result would carry.

    Raises:
      None.
    """
    return "scrub-sentinel-4f1c"


def _result(secret: str) -> dict:
    """Builds a Checkov plan result with one passed check on a SecureString parameter.

    Args:
      secret: The parameter's planned value.

    Returns:
      The result, in the object shape Checkov writes for one framework.

    Raises:
      None.
    """
    check = {
        "check_id": "CKV2_AWS_34",
        "resource": "module.auth.aws_ssm_parameter.server_client_secret",
        "code_block": [[1, f'resource "aws_ssm_parameter" "server_client_secret" {{ value = "{secret}" }}']],
        "check_result": {
            "result": "PASSED",
            "entity": {
                "aws_ssm_parameter": {
                    "server_client_secret": {"type": ["SecureString"], "value": [secret]}
                }
            },
        },
    }
    return {
        "check_type": "terraform_plan",
        "results": {"passed_checks": [check], "failed_checks": []},
        "summary": {"passed": 1, "failed": 0, "parsing_errors": 0},
    }


def test_the_published_copy_carries_no_planned_value_and_keeps_what_the_gates_read(tmp_path) -> None:
    """A secret in a check's entity is gone, and the counts and check identities survive."""
    source, target = tmp_path / "checkov-plan.json", tmp_path / "publishable.json"
    source.write_text(json.dumps(_result(_secret())))

    assert SCRUB.main([str(source), str(target)]) == 0

    published = target.read_text()
    assert _secret() not in published
    parsed = json.loads(published)
    assert parsed["summary"] == {"passed": 1, "failed": 0, "parsing_errors": 0}
    assert parsed["results"]["passed_checks"][0]["check_id"] == "CKV2_AWS_34"
    assert parsed["results"]["passed_checks"][0]["resource"].endswith("server_client_secret")


def test_an_unreadable_result_writes_nothing(tmp_path) -> None:
    """A result that is not JSON leaves no publishable file, so the upload finds nothing to send."""
    source, target = tmp_path / "checkov-plan.json", tmp_path / "publishable.json"
    source.write_text("not json " + _secret())

    assert SCRUB.main([str(source), str(target)]) == 2
    assert not target.exists()


def test_the_workflow_uploads_only_the_scrubbed_copy_after_scrubbing_it() -> None:
    """The upload names the scrubbed file, the scrub runs before it on every outcome, and the scan
    stays compact, which keeps each resource's source lines out of the result in the first place."""
    steps = yaml.safe_load(WORKFLOW.read_text())["jobs"]["plan"]["steps"]
    scan = next(step for step in steps if "checkov-scan.sh -f plan.json" in step.get("run", ""))
    assert "--compact" in scan["run"], "the plan scan dropped --compact"
    names = [step.get("name") for step in steps]
    scrub_at = names.index("Scrub Checkov result")
    upload_at = names.index("Upload Checkov result")

    assert scrub_at < upload_at
    assert steps[scrub_at].get("if") == "always()"
    assert "checkov_scrub.py checkov-plan.json checkov-plan-publishable.json" in steps[scrub_at]["run"]
    assert steps[upload_at]["with"]["path"] == "infra/checkov-plan-publishable.json"
    cleanup = next(step for step in steps if step.get("name") == "Remove the plan files")
    assert "checkov-plan.json" in cleanup["run"].split(), "the unscrubbed result outlives the job's scans"
