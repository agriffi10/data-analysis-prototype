"""The security gates' configuration must say what the workflows actually do.

A gate is a claim about what cannot merge, and every part of that claim lives somewhere the
suite otherwise never reads: a ``GATE_*`` value in a workflow, a list file the gate's numerator
comes from, a scanner flag the numerator silently depends on. Nothing here tests a scanner —
they are pinned by version and run in CI. What these tests hold is the WIRING, because that is
where a gate stops enforcing without anyone noticing.

The shape is SPEC-153's: assert the coupling, then assert the parse did not go trivial. A test
that reads a workflow and finds nothing must fail rather than pass vacuously — a regex that
stops matching after a reformat is exactly how a guard starts guarding nothing.

It lives under ``lambdas/`` because that is where pytest runs, alongside
``test_deploy_matrix.py``, which reads ``deploy-lambdas.yml`` for the same reason.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
INFRA_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-infra.yml"
ENFORCED_LIST = ROOT / ".github" / "checkov-enforced.txt"
ACCEPTED_LIST = ROOT / ".github" / "checkov-plan-accepted.txt"

#: The Semgrep rule excluded from the Lambdas scan. A Flask template-injection check, pulled in
#: by ``p/owasp-top-ten``'s Python set; there is no Flask and no HTTP response in this fleet.
#: Excluding it is what let ``GATE_SEMGREP`` become ``block`` (docs/security-baseline.md).
FLASK_RULE = "python.flask.security.audit.directly-returned-format-string"

CHECK_ID = re.compile(r"^CKV[0-9]*_[A-Z]+_[0-9]+$")


def _gate_value(workflow: pathlib.Path, name: str) -> str:
    """Reads one ``GATE_*`` value out of a workflow's env block.

    Args:
      workflow: The workflow file to read.
      name: The gate variable's name, without the ``GATE_`` prefix.

    Returns:
      The gate's value.

    Raises:
      AssertionError: If the variable is not present — a gate that cannot be found is not a
        gate whose value can be trusted.
    """
    match = re.search(rf"^\s*GATE_{name}:\s*(\S+)\s*$", workflow.read_text(), re.MULTILINE)
    assert match, f"GATE_{name} not found in {workflow.name} — the gate block was renamed or reformatted"
    return match.group(1)


def _list_entries(path: pathlib.Path) -> list[list[str]]:
    """Parses a gate list file into whitespace-split, comment-stripped rows.

    Args:
      path: The list file.

    Returns:
      One list of fields per non-empty, non-comment line.

    Raises:
      None.
    """
    rows = []
    for line in path.read_text().splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped:
            rows.append(stripped.split())
    return rows


def test_the_checkov_enforced_list_parses_to_real_check_ids():
    entries = _list_entries(ENFORCED_LIST)
    assert len(entries) >= 40, (
        f"only {len(entries)} enforced check ID(s) parsed. The list was measured at 52; a parse "
        "this small means the file's shape changed and the gate is enforcing almost nothing."
    )
    for row in entries:
        assert len(row) == 1, f"enforced list rows carry one check ID, got {row!r}"
        assert CHECK_ID.match(row[0]), f"{row[0]!r} is not a checkov check ID"


def test_the_checkov_plan_accepted_list_names_iam_resources():
    entries = _list_entries(ACCEPTED_LIST)
    assert entries, "the accepted list is empty — two permanent deploy-role findings are expected"
    for row in entries:
        assert len(row) == 2, f"accepted rows are `CHECK_ID resource`, got {row!r}"
        check_id, resource = row
        assert CHECK_ID.match(check_id), f"{check_id!r} is not a checkov check ID"
        assert "aws_iam_" in resource, (
            f"{resource!r} is not an IAM resource. This list only modifies the IAM count, so a "
            "non-IAM line suppresses nothing while reading as a suppression."
        )


def test_the_checkov_tf_scan_does_not_pass_quiet():
    """``--quiet`` strips ``passed_checks``, and the enforced gate needs them.

    Without ``passed_checks`` every enforced ID looks unevaluated, which the gate script treats
    as a hard error — so this would fail loudly rather than silently. It is pinned anyway
    because the failure would read as "the list is wrong" rather than "the flag is wrong", and
    deploy-infra.yml already carries the same constraint as a comment.
    """
    text = SECURITY_WORKFLOW.read_text()
    match = re.search(r"checkov -d infra \\\n(?:.*\n)*?.*--soft-fail", text)
    assert match, "the checkov invocation in security.yml was not found — this guard went trivial"
    assert "--quiet" not in match.group(0), (
        "checkov -d infra passes --quiet, which strips passed_checks. The enforced gate cannot "
        "tell 'this check passed' from 'this check never ran' without them."
    )


def test_the_enforced_gate_is_wired_to_the_list_and_blocks():
    text = SECURITY_WORKFLOW.read_text()
    assert "checkov-enforced.sh" in text, "security.yml does not call the enforced-count script"
    assert ".github/checkov-enforced.txt" in text, "security.yml does not name the enforced list"
    assert _gate_value(SECURITY_WORKFLOW, "CHECKOV") == "block"


def test_the_plan_gate_is_wired_to_the_list_and_blocks():
    text = INFRA_WORKFLOW.read_text()
    assert "checkov-plan-iam.sh" in text, "deploy-infra.yml does not call the plan IAM script"
    assert "checkov-plan-accepted.txt" in text, "deploy-infra.yml does not name the accepted list"
    assert _gate_value(INFRA_WORKFLOW, "CHECKOV_PLAN") == "block"


def test_semgrep_blocks_and_excludes_exactly_the_flask_rule():
    """The exclusion is what makes ``block`` reachable, so the two must move together.

    A ``block`` without the exclusion reddens every PR on a known false positive; an exclusion
    without ``block`` hides a finding and gates nothing. Either alone is worse than neither.
    """
    text = SECURITY_WORKFLOW.read_text()
    assert _gate_value(SECURITY_WORKFLOW, "SEMGREP") == "block"
    assert f"--exclude-rule={FLASK_RULE}" in text, (
        "the Flask false positive is not excluded, so gate=block fails every PR on it"
    )
    assert text.count("--exclude-rule=") == 1, (
        "a second Semgrep rule exclusion appeared. Each one narrows what SAST reports and needs "
        "its own disposition in docs/security-baseline.md."
    )


@pytest.mark.parametrize("script", ["checkov-enforced.sh", "checkov-plan-iam.sh"])
def test_the_gate_scripts_are_executable(script):
    path = ROOT / ".github" / "scripts" / script
    assert path.exists(), f"{script} is missing"
    assert path.stat().st_mode & 0o111, f"{script} is not executable — the workflow calls it directly"
