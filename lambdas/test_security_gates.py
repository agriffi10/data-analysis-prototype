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
FLASK_RULE = "python.flask.security.audit.directly-returned-format-string.directly-returned-format-string"

CHECK_ID = re.compile(r"^CKV[0-9]*_[A-Z]+_[0-9]+$")

#: How many check IDs `.github/checkov-enforced.txt` holds at zero. Pinned so that removing an
#: entry — the way this gate would be quietly weakened — is a deliberate two-file edit. Raised from
#: 52 when the container platform's VPC, ECS, ECR, ALB, ACM and API Gateway resources brought 37
#: newly-passing IDs with them; no ID was removed, and the measurement is in
#: docs/security-baseline.md under the dated section for that spec.
ENFORCED_COUNT = 89

#: The gate steps must default to a NON-NUMERIC sentinel. `${VAR:-0}` substitutes on empty as
#: well as unset, so a numeric default turns "the narrowing step wrote nothing" into "clean".
SENTINEL = "no-count"


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
    """The enforced list must parse to exactly the number of IDs the docs claim.

    Equality, not a floor. A floor lets IDs be deleted one at a time without anything
    noticing, and deleting an entry is precisely how this gate gets quietly weakened — an ID
    that starts failing can be made to go away by removing the line. Growing or shrinking the
    list is fine; doing it without touching this number is not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: On a count mismatch or a malformed row.
    """
    entries = _list_entries(ENFORCED_LIST)
    assert len(entries) == ENFORCED_COUNT, (
        f"{len(entries)} enforced check ID(s), expected {ENFORCED_COUNT}. If the change is "
        "deliberate, update ENFORCED_COUNT here and the count in docs/security-baseline.md — "
        "removing an ID is a decision that belongs in that file."
    )
    for row in entries:
        assert len(row) == 1, f"enforced list rows carry one check ID, got {row!r}"
        assert CHECK_ID.match(row[0]), f"{row[0]!r} is not a checkov check ID"


def test_the_checkov_plan_accepted_list_names_iam_resources():
    """Every accepted row must be `CHECK_ID resource`, and the resource must be an IAM one.

    A non-IAM line would sit in the file suppressing nothing — the count it modifies is
    IAM-only — while reading as a suppression. The script refuses one too.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: On an empty list or a malformed row.
    """
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


def _invocation(workflow: pathlib.Path, first_line: str) -> str:
    """Reads a whole backslash-continued shell invocation out of a workflow.

    A regex anchored on the invocation's LAST flag only covers the text up to that flag, so a
    flag added after it — same line or a later continuation — slips through. This follows the
    continuations instead, so the returned text is every line of the command.

    Args:
      workflow: The workflow file to read.
      first_line: Substring identifying the invocation's first line.

    Returns:
      The invocation's full text, newlines included.

    Raises:
      AssertionError: If no line contains ``first_line`` — a guard that matches nothing must
        fail rather than pass over an empty string.
    """
    lines = workflow.read_text().splitlines()
    start = next((i for i, line in enumerate(lines) if first_line in line), None)
    assert start is not None, f"{first_line!r} not found in {workflow.name} — this guard went trivial"
    end = start
    while lines[end].rstrip().endswith("\\"):
        end += 1
    return "\n".join(lines[start : end + 1])


def test_the_checkov_tf_scan_does_not_pass_quiet():
    """``--quiet`` strips ``passed_checks``, and the enforced gate needs them.

    Without ``passed_checks`` every enforced ID looks unevaluated, the gate script hard-errors,
    and — since the sentinel default landed — that reaches the gate as a failure rather than a
    zero. Pinned anyway because the failure would read as "the list is wrong" rather than "the
    flag is wrong", and deploy-infra.yml already carries the same constraint as a comment.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the flag is anywhere in the invocation.
    """
    invocation = _invocation(SECURITY_WORKFLOW, "checkov -d infra")
    assert "--quiet" not in invocation, (
        "checkov -d infra passes --quiet, which strips passed_checks. The enforced gate cannot "
        "tell 'this check passed' from 'this check never ran' without them."
    )


def test_the_enforced_gate_is_wired_to_the_list_and_blocks():
    """security.yml must call the narrowing script, name the list, and be set to block.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three is missing.
    """
    text = SECURITY_WORKFLOW.read_text()
    assert "checkov-enforced.sh" in text, "security.yml does not call the enforced-count script"
    assert ".github/checkov-enforced.txt" in text, "security.yml does not name the enforced list"
    assert _gate_value(SECURITY_WORKFLOW, "CHECKOV") == "block"


def test_the_plan_gate_is_wired_to_the_list_and_blocks():
    """deploy-infra.yml must call the plan IAM script, name the list, and be set to block.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three is missing.
    """
    text = INFRA_WORKFLOW.read_text()
    assert "checkov-plan-iam.sh" in text, "deploy-infra.yml does not call the plan IAM script"
    assert "checkov-plan-accepted.txt" in text, "deploy-infra.yml does not name the accepted list"
    assert _gate_value(INFRA_WORKFLOW, "CHECKOV_PLAN") == "block"


@pytest.mark.parametrize(
    ("workflow", "variable"),
    [(SECURITY_WORKFLOW, "CHECKOV_FINDINGS"), (INFRA_WORKFLOW, "CHECKOV_PLAN_FINDINGS")],
)
def test_the_gate_defaults_to_a_non_numeric_sentinel(workflow, variable):
    """A gate whose count is absent must hard-error, never read as zero.

    This is the shape that made every one of the narrowing scripts' hard errors reach the gate
    as a silent green: `${VAR:-0}` substitutes on EMPTY as well as unset, so a failed narrowing
    step that wrote `VAR=` produced a clean pass. apply-gate.sh rejects a non-numeric count,
    which is what an absent count is.

    Args:
      workflow: The workflow whose gate invocation is checked.
      variable: The environment variable carrying the count.

    Returns:
      None.

    Raises:
      AssertionError: If the gate defaults to a number, or does not default at all.
    """
    text = workflow.read_text()
    assert f"${{{variable}:-{SENTINEL}}}" in text, (
        f"{workflow.name} does not default {variable} to the non-numeric sentinel "
        f"{SENTINEL!r}. A numeric default turns a missing count into a clean pass."
    )
    assert f"${{{variable}:-0}}" not in text, (
        f"{workflow.name} still defaults {variable} to 0 somewhere — that is the fail-open shape."
    )


@pytest.mark.parametrize(
    ("workflow", "script"),
    [(SECURITY_WORKFLOW, "checkov-enforced.sh"), (INFRA_WORKFLOW, "checkov-plan-iam.sh")],
)
def test_the_narrowing_step_assigns_before_it_echoes(workflow, script):
    """`echo "VAR=$(script)"` does not fail the step when the script fails.

    `echo` exits 0 regardless of what its argument's substitution did, so `set -e` sees
    success and the empty value gets written — overwriting the pessimistic full count. Only an
    assignment's substitution failure trips `set -e`. Pinned because the broken form reads
    exactly like the working one.

    Args:
      workflow: The workflow to check.
      script: The narrowing script it calls.

    Returns:
      None.

    Raises:
      AssertionError: If the script is called from inside an `echo` argument.
    """
    for line in workflow.read_text().splitlines():
        if script in line:
            assert not line.lstrip().startswith("echo "), (
                f"{workflow.name} calls {script} inside an echo argument. A failing substitution "
                "there does not fail the step; assign to a variable first."
            )


def test_semgrep_blocks_and_excludes_exactly_the_flask_rule():
    """The exclusion is what makes ``block`` reachable, so the two must move together.

    A ``block`` without the exclusion reddens every PR on a known false positive; an exclusion
    without ``block`` hides a finding and gates nothing. Either alone is worse than neither.

    **This test cannot tell a correct rule ID from a wrong one** — it asserts the string is
    present, not that Semgrep matches it. The first version of this exclusion was short by one
    component (Semgrep doubles the last segment: ``…format-string.directly-returned-format-string``)
    and this test passed while the scan failed. The CI run is the check that catches that, and
    it only catches it because the gate blocks.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the gate is not blocking, the exclusion is missing, or a second
        exclusion appeared.
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
    """The workflows invoke these by path, so the mode bit is part of the wiring.

    Args:
      script: The script's filename under .github/scripts/.

    Returns:
      None.

    Raises:
      AssertionError: If the script is missing or not executable.
    """
    path = ROOT / ".github" / "scripts" / script
    assert path.exists(), f"{script} is missing"
    assert path.stat().st_mode & 0o111, f"{script} is not executable — the workflow calls it directly"
