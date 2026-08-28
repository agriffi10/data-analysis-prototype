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
