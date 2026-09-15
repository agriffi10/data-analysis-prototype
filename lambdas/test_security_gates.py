"""The security gates' configuration must say what the workflows actually do.

A gate is a claim about what cannot merge, and every part of that claim lives somewhere the
suite otherwise never reads: a ``GATE_*`` value in a workflow, a list file the gate's numerator
comes from, a scanner flag the numerator silently depends on. Nothing here tests a scanner —
they are pinned by version and run in CI. What these tests hold is the WIRING, because that is
where a gate stops enforcing without anyone noticing.

The shape is SPEC-153's: assert the coupling, then assert the parse did not go trivial. A test
that reads a workflow and finds nothing must fail rather than pass vacuously — a regex that
stops matching after a reformat is exactly how a guard starts guarding nothing.

It lives under ``lambdas/`` because that is where pytest runs, alongside the other suites that
read CI's own files as data for the same reason.
"""

import dataclasses
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
from typing import NamedTuple

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
INFRA_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-infra.yml"
ENFORCED_LIST = ROOT / ".github" / "checkov-enforced.txt"
DOCKERFILE_ENFORCED_LIST = ROOT / ".github" / "checkov-dockerfile-enforced.txt"
ACCEPTED_LIST = ROOT / ".github" / "checkov-plan-accepted.txt"
NARROWING_SCRIPT = ROOT / ".github" / "scripts" / "checkov-enforced.sh"
GATE_SCRIPT = ROOT / ".github" / "scripts" / "apply-gate.sh"

#: The name of the Checkov gate's count, as a whole word, so ``CHECKOV_DOCKERFILE_FINDINGS``
#: is not a mention of it.
COUNT_NAME = re.compile(r"\bCHECKOV_FINDINGS\b")

#: Every step of security.yml's scan job that writes or reads the Checkov gate's count, in the
#: order the job runs them. Each is replayed from the workflow, and the replay refuses to run
#: unless these are exactly the steps that name the count.
CHECKOV_COUNT_STEPS = (
    "Narrow to the enforced checks",
    "Narrow the dockerfile scan to its enforced checks",
    "Apply gate (Checkov)",
)

#: The Semgrep rule excluded from the Lambdas scan. A Flask template-injection check, pulled in
#: by ``p/owasp-top-ten``'s Python set; there is no Flask and no HTTP response in this fleet.
#: Excluding it is what let ``GATE_SEMGREP`` become ``block`` (docs/security-baseline.md).
FLASK_RULE = "python.flask.security.audit.directly-returned-format-string.directly-returned-format-string"

#: Any mention of a Semgrep rule exclusion, capturing the rule ID after it on the same line past
#: any quotes, ``=`` or spaces; the ID is empty where nothing follows. Deliberately not anchored
#: on ``--``, so a bare ``exclude-rule`` key is a mention too.
EXCLUDE_RULE = re.compile(r"""exclude-rule[ \t"'=]*([^\s"']*)""")

CHECK_ID = re.compile(r"^CKV[0-9]*_[A-Z]+_[0-9]+$")

#: How many check IDs `.github/checkov-enforced.txt` holds at zero. Pinned so that removing an
#: entry — the way this gate would be quietly weakened — is a deliberate two-file edit. Raised from
#: 52 when the container platform's VPC, ECS, ECR, ALB, ACM and API Gateway resources brought 37
#: newly-passing IDs with them; no ID was removed, and the measurement is in
#: docs/security-baseline.md under the dated section for that spec.
ENFORCED_COUNT = 79

#: The same pin for the dockerfile framework's list, for the same reason. Measured at 38 passed /
#: 2 failed against checkov 3.3.9 on lambdas/Dockerfile; the two failures — no HEALTHCHECK and no
#: USER — are dispositioned in docs/security-baseline.md rather than enforced.
DOCKERFILE_ENFORCED_COUNT = 21

#: The gate steps must default to a NON-NUMERIC sentinel. `${VAR:-0}` substitutes on empty as
#: well as unset, so a numeric default turns "the narrowing step wrote nothing" into "clean".
SENTINEL = "no-count"

#: The empty ``.semgrepignore`` at the repository root. Without it Semgrep applies a built-in list
#: that skips every ``test/`` directory, so its only job is to exist.
ROOT_SEMGREPIGNORE = ROOT / ".semgrepignore"

#: The scripts the summary and gate steps call by path, copied into each run's checkout.
STEP_SCRIPTS = ("summary-section.sh", "apply-gate.sh")

#: For each scanner whose wrapper deletes the report of a refused scan: its summary step, its gate
#: step, the variable the one hands the other, the reports of a clean scan, and the report a
#: refusal leaves missing. Semgrep's refused report is one of two, because the realistic refusal
#: stops one scan while the other reports cleanly, and a summary that skipped the missing one
#: would hand the gate the clean one's zero.
GATED_REPORTS = {
    "semgrep": (
        "Summarize (Semgrep)",
        "Apply gate (Semgrep)",
        "SEMGREP_FINDINGS",
        {"semgrep-portal.json": '{"results": [], "errors": []}', "semgrep-lambdas.json": '{"results": [], "errors": []}'},
        "semgrep-lambdas.json",
    ),
    "gitleaks": ("Summarize (gitleaks)", "Apply gate (gitleaks)", "GITLEAKS_FINDINGS", {"gitleaks.json": "[]"}, "gitleaks.json"),
}


@dataclasses.dataclass(frozen=True)
class _Guarded:
    """One scanner whose every scan goes through a wrapper that refuses configuration it discovers.

    Each wrapper exists because its scanner, measured, reads a file or variable from outside its
    command line that removes a finding from a blocking gate. A scan added without the wrapper is
    open to that again and looks exactly as green, so the sweep below reads every workflow line.

    Attributes:
      word: What a workflow line says, case-sensitively, when it may run the scanner.
      harmless: The forms that say ``word`` without running the scanner: the gate's own scripts by
        name, a report, list file or release archive, the pinned install, messages that name the
        scanner, and the artifact's name in backticks, as a job summary prints it. Anything else
        on a line that still says ``word`` is taken to run it, however it is spelled, which is why
        this lists the harmless forms rather than the invocations. A new script is added here by
        hand, because the sweep reads workflows and not the scripts they call.
      wrapper: The wrapper's file name, as the messages below give it.
      wrapped: The wrapper, however its path is spelled, capturing the arguments that tell one
        scan from another.
      corpus: The wrapper's fixture corpus, however its path is spelled.
      known_scans: Every scan that must be found going through the wrapper, as (workflow,
        identifying arguments). The sweep's positive control: a collector that stopped matching
        would otherwise report no bare invocation and pass.
      known_jobs: The jobs that must be found among those scanning through the wrapper.
    """

    word: str
    harmless: re.Pattern[str]
    wrapper: str
    wrapped: re.Pattern[str]
    corpus: re.Pattern[str]
    known_scans: frozenset[tuple[str, str]]
    known_jobs: frozenset[tuple[str, str]]


#: Every scanner whose scans must go through a configuration refusal, by name.
GUARDED = {
    "checkov": _Guarded(
        word="checkov",
        harmless=re.compile(
            r"(?<![\w-])checkov-(?:scan|scan-test|enforced|plan-iam)\.sh(?![\w.-])"
            r"|[\w./-]*checkov[\w-]*\.(?:json|txt)(?![\w.-])"
            r"""|\bpip3?\s+install\s+(["']?)checkov==[^\s"']+\1"""
            r"|\\?`checkov\\?`"
        ),
        wrapper="checkov-scan.sh",
        wrapped=re.compile(r"(?<![\w-])checkov-scan\.sh\s+(\S+\s+\S+)"),
        corpus=re.compile(r"(?<![\w-])checkov-scan-test\.sh(?![\w.-])"),
        known_scans=frozenset(
            {
                ("security.yml", "-d infra"),
                ("security.yml", "-f lambdas/Dockerfile"),
                ("deploy-infra.yml", "-f plan.json"),
            }
        ),
        known_jobs=frozenset({("security.yml", "scan"), ("deploy-infra.yml", "plan")}),
    ),
    "semgrep": _Guarded(
        word="semgrep",
        harmless=re.compile(
            r"(?<![\w-])semgrep-scan(?:-test)?\.sh(?![\w.-])"
            r"|[\w./*-]*semgrep[\w*-]*\.json(?![\w.-])"
            r"""|\bpip3?\s+install\s+(["']?)semgrep==[^\s"']+\1"""
            r"|\\?`semgrep\\?`"
        ),
        wrapper="semgrep-scan.sh",
        wrapped=re.compile(r"(?<![\w-])semgrep-scan\.sh\s+(\S+)"),
        corpus=re.compile(r"(?<![\w-])semgrep-scan-test\.sh(?![\w.-])"),
        known_scans=frozenset({("security.yml", "semgrep-portal.json"), ("security.yml", "semgrep-lambdas.json")}),
        known_jobs=frozenset({("security.yml", "scan")}),
    ),
    "gitleaks": _Guarded(
        word="gitleaks",
        harmless=re.compile(
            r"(?<![\w-])gitleaks-scan\.sh\s+\S+\s+\S*gitleaks(?![\w.-])"
            r"|(?<![\w-])gitleaks-scan-test\.sh\s+\S*gitleaks(?![\w.-])"
            r"|[\w./-]*gitleaks[\w.-]*\.(?:json|tar\.gz)(?![\w.-])"
            r"|https://github\.com/gitleaks/gitleaks/releases/download/\S+"
            r"|\btar\s+-xzf\s+gitleaks\.tar\.gz\s+gitleaks(?![\w.-])"
            r"|(?<![\w-])(?:\./)?gitleaks\s+version(?![\w.-])"
            r"|\btitle=gitleaks::"
            r'|\bsummary-section\.sh\s+"gitleaks\b'
            r"|\bapply-gate\.sh\s+gitleaks(?![\w.-])"
        ),
        wrapper="gitleaks-scan.sh",
        wrapped=re.compile(r"(?<![\w-])gitleaks-scan\.sh\s+(\S+\s+\S+)"),
        corpus=re.compile(r"(?<![\w-])gitleaks-scan-test\.sh(?![\w.-])"),
        known_scans=frozenset({("security.yml", "gitleaks.json ./gitleaks")}),
        known_jobs=frozenset({("security.yml", "scan")}),
    ),
}


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
    invocation = _invocation(SECURITY_WORKFLOW, "checkov-scan.sh -d infra")
    assert "--quiet" not in invocation, (
        "the -d infra scan passes --quiet, which strips passed_checks. The enforced gate cannot "
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


def test_the_checkov_dockerfile_enforced_list_parses_to_real_check_ids():
    """The dockerfile enforce list must parse to exactly the number of IDs the docs claim.

    Equality, not a floor, for the reason the terraform list gives: deleting an entry is how this
    gate gets quietly weakened, and an ID that starts failing can be made to go away by removing
    the line. Trimming the list to one ID otherwise passes the entire suite.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: On a count mismatch or a malformed row.
    """
    entries = _list_entries(DOCKERFILE_ENFORCED_LIST)
    assert len(entries) == DOCKERFILE_ENFORCED_COUNT, (
        f"{len(entries)} enforced dockerfile check ID(s), expected {DOCKERFILE_ENFORCED_COUNT}. "
        "If the change is deliberate, update DOCKERFILE_ENFORCED_COUNT here and the measurement "
        "in docs/security-baseline.md — removing an ID is a decision that belongs in that file."
    )
    for row in entries:
        assert len(row) == 1, f"enforced list rows carry one check ID, got {row!r}"
        assert CHECK_ID.match(row[0]), f"{row[0]!r} is not a checkov check ID"


def test_the_checkov_dockerfile_scan_does_not_pass_quiet():
    """`--quiet` strips `passed_checks`, and the enforced gate needs them.

    Without them `checkov-enforced.sh` cannot tell "this check passed" from "this check never
    ran", and those two must never look alike. The terraform scan carries the same constraint and
    the same pin; this is the second invocation, which would otherwise be unguarded.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the invocation passes `--quiet`.
    """
    invocation = _invocation(SECURITY_WORKFLOW, "checkov-scan.sh -f lambdas/Dockerfile")
    assert "--quiet" not in invocation, (
        "the dockerfile scan passes --quiet, which strips passed_checks — the enforced gate then "
        "cannot tell a check that passed from one that never ran, and hard-errors on every ID."
    )
    assert "--soft-fail" in invocation, (
        "the dockerfile scan must pass --soft-fail; checkov exits 1 merely because checks failed, "
        "which under a report-mode gate is not a job failure. The count comes from the JSON."
    )


def _steps_by_job(workflow: pathlib.Path) -> dict[str, list[dict]]:
    """Reads a workflow's steps, job by job.

    Args:
      workflow: The workflow file to read.

    Returns:
      Each job's name mapped to its list of steps, in order.

    Raises:
      None.
    """
    document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    return {name: job.get("steps", []) for name, job in document.get("jobs", {}).items()}


def _script_lines(step: dict) -> list[str]:
    """Returns a step's ``run`` script as lines, without its shell comment lines.

    A commented-out invocation runs nothing, so it neither needs the wrapper nor counts as a
    scan that has it.

    Args:
      step: One workflow step.

    Returns:
      The script's lines, or an empty list for a step with no ``run``.

    Raises:
      None.
    """
    return [line for line in str(step.get("run", "")).splitlines() if not line.lstrip().startswith("#")]


def _runs_outside_its_wrapper(line: str, guarded: _Guarded) -> bool:
    """Says whether one line of a ``run`` script runs a guarded scanner other than through its wrapper.

    It removes the forms that name the scanner without running it (``harmless``) and reads what
    is left, so a spelling nobody listed, such as an environment prefix, ``time``, ``pipx run``
    or a container image, is still caught. The cost is a false alarm on a new harmless form,
    which fails loudly and is fixed by naming it there.

    Args:
      line: One line of a step's ``run`` script, comment lines already removed.
      guarded: The scanner to look for.

    Returns:
      True when the line still names the scanner once the harmless forms are gone.

    Raises:
      None.
    """
    return guarded.word in guarded.harmless.sub("", line)


@pytest.mark.parametrize(
    ("name", "line", "runs_it"),
    [
        ("checkov", "checkov -d infra \\", True),
        ("checkov", "CKV_SKIP_CHECK=CKV_AWS_355 checkov -f plan.json", True),
        ("checkov", "env X=1 checkov -d infra", True),
        ("checkov", "if checkov -d infra; then", True),
        ("checkov", "time checkov -d infra", True),
        ("checkov", "pipx run checkov -d infra", True),
        ("checkov", 'docker run --rm -v "$PWD:/w" bridgecrew/checkov -d /w/infra', True),
        ("checkov", "python3 -m checkov.main -d infra", True),
        ("checkov", "out=$(checkov -f plan.json)", True),
        ("checkov", "out=`checkov -f plan.json`", True),
        ("checkov", ".github/scripts/checkov-scan.sh -d infra && checkov -f plan.json", True),
        ("checkov", ".github/scripts/checkov-bare.sh -d infra", True),
        ("checkov", "../.github/scripts/checkov-scan.sh -f plan.json \\", False),
        ("checkov", "bash ./.github/scripts/checkov-scan.sh -d infra", False),
        ("checkov", ".github/scripts/checkov-scan-test.sh", False),
        ("checkov", 'pip install "checkov==${CHECKOV_VERSION}"', False),
        ("checkov", "findings=$(.github/scripts/checkov-enforced.sh checkov.json .github/checkov-enforced.txt)", False),
        (
            "checkov",
            "findings=$(../.github/scripts/checkov-plan-iam.sh checkov-plan.json ../.github/checkov-plan-accepted.txt)",
            False,
        ),
        ("checkov", 'echo "::error title=Checkov (plan)::output is not valid"', False),
        ("checkov", 'echo "_Per-resource detail is in the \\`checkov\\` artifact._"', False),
        ("semgrep", "semgrep scan \\", True),
        ("semgrep", "SEMGREP_BASELINE_COMMIT=HEAD semgrep scan --config p/python lambdas", True),
        ("semgrep", "python3 -m semgrep scan lambdas", True),
        ("semgrep", 'docker run --rm -v "$PWD:/src" semgrep/semgrep semgrep scan', True),
        ("semgrep", "semgrep scan --json --output semgrep-lambdas.json lambdas", True),
        ("semgrep", ".github/scripts/semgrep-scan.sh semgrep-lambdas.json lambdas && semgrep scan lambdas", True),
        ("semgrep", ".github/scripts/semgrep-bare.sh semgrep-lambdas.json lambdas", True),
        ("semgrep", ".github/scripts/semgrep-scan.sh semgrep-portal.json \\", False),
        ("semgrep", ".github/scripts/semgrep-scan-test.sh", False),
        ("semgrep", 'pip install "semgrep==${SEMGREP_VERSION}"', False),
        ("semgrep", 'for pair in "SPA:semgrep-portal.json" "Lambdas:semgrep-lambdas.json"; do', False),
        ("semgrep", 'echo "_Showing the first 100 of ${count}. The full set is in the \\`semgrep\\` artifact._"', False),
        ("gitleaks", "./gitleaks git --redact --report-format json --report-path gitleaks.json .", True),
        ("gitleaks", "GITLEAKS_CONFIG=allow.toml gitleaks detect --source .", True),
        ("gitleaks", 'docker run -v "$PWD:/path" ghcr.io/gitleaks/gitleaks:latest git /path', True),
        ("gitleaks", ".github/scripts/gitleaks-scan.sh gitleaks.json ./gitleaks --redact && ./gitleaks git .", True),
        ("gitleaks", "tar -xzf gitleaks.tar.gz gitleaks && ./gitleaks git .", True),
        ("gitleaks", "./gitleaks version && ./gitleaks dir .", True),
        ("gitleaks", ".github/scripts/gitleaks-scan.sh gitleaks.json ./gitleaks --redact", False),
        ("gitleaks", ".github/scripts/gitleaks-scan-test.sh ./gitleaks", False),
        ("gitleaks", "curl -sSLo gitleaks.tar.gz \\", False),
        (
            "gitleaks",
            '"https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz"',
            False,
        ),
        ("gitleaks", "tar -xzf gitleaks.tar.gz gitleaks", False),
        ("gitleaks", "./gitleaks version", False),
        ("gitleaks", 'echo "::error title=gitleaks::gitleaks.json missing — the scan did not run or was refused."', False),
        ("gitleaks", '.github/scripts/summary-section.sh "gitleaks — full history" "$count" body.md', False),
        ("gitleaks", '.github/scripts/apply-gate.sh gitleaks "$GATE_GITLEAKS" "${GITLEAKS_FINDINGS:-no-count}"', False),
    ],
)
def test_a_line_that_runs_a_scanner_is_found_however_it_is_spelled(name: str, line: str, runs_it: bool):
    """The sweep's reading of one line, against a line whose verdict is known.

    The sweep below passes on every workflow here, which proves the workflows pass and nothing
    about whether the sweep can see an invocation. These rows are the positive control: the
    spellings that escaped a sweep matching command positions, a wrapped scan followed by a bare
    one, a script the allowlist does not name, and, for silence, every harmless form the
    workflows use today.

    Args:
      name: The scanner's key in ``GUARDED``.
      line: One line of a ``run`` script.
      runs_it: Whether the line runs the scanner outside its wrapper.

    Returns:
      None.

    Raises:
      AssertionError: When the sweep reads the line the other way.
    """
    assert _runs_outside_its_wrapper(line, GUARDED[name]) is runs_it, (
        f"{line!r} was read as {'running' if not runs_it else 'not running'} {name} outside its wrapper"
    )


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_every_scan_goes_through_its_config_refusal(name: str):
    """No workflow runs a guarded scanner except through its wrapper.

    Checkov takes configuration from a ``.checkov.yml`` in the scanned directory, the working
    directory or $HOME, and from its flags' environment variables; Semgrep skips what a
    ``.semgrepignore`` anywhere in the tree matches, and reads SEMGREP_* variables; gitleaks reads
    a ``.gitleaks.toml`` and a ``.gitleaksignore`` from the repository it scans, and two
    variables. Measured, one such file or variable took a finding off each blocking gate while
    the job still read as a clean scan. Each wrapper refuses the scan when that happens. A scan
    added without it is open to the same file again and looks exactly as green, and so is the
    scanner's GitHub Action, which runs it where the wrapper cannot reach.

    Args:
      name: The scanner's key in ``GUARDED``.

    Returns:
      None.

    Raises:
      AssertionError: When a step runs the scanner outside its wrapper or through its Action, or
        when a known scan is not found going through the wrapper, which is what a collector that
        stopped matching would look like.
    """
    guarded = GUARDED[name]
    bare = []
    wrapped = set()
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for job, steps in _steps_by_job(workflow).items():
            for step in steps:
                if guarded.word in str(step.get("uses", "")).lower():
                    bare.append(f"{workflow.name} / {job}: uses {step['uses']}")
                for line in _script_lines(step):
                    if _runs_outside_its_wrapper(line, guarded):
                        bare.append(f"{workflow.name} / {job}: {line.strip()}")
                    for match in guarded.wrapped.finditer(line):
                        wrapped.add((workflow.name, " ".join(match.group(1).split())))
    assert not bare, (
        f"{name} runs without .github/scripts/{guarded.wrapper}, so configuration it discovers can "
        f"change what its gate counts: {bare}"
    )
    missing = guarded.known_scans - wrapped
    assert not missing, (
        f"scan(s) {sorted(missing)} not found going through {guarded.wrapper} (found {sorted(wrapped)}). "
        "Either a scan moved or the collector stopped matching, and a collector matching nothing "
        "would also find no bare invocation."
    )


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_each_config_refusal_is_proven_before_its_job_scans(name: str):
    """Every job that scans through a wrapper runs that wrapper's fixture corpus first, under the same condition.

    The refusal never fires on a normal run, so a scanner release that stopped reporting a file
    the scan still reads, or renamed the line or reason its wrapper reads, would switch every
    refusal off with nothing going red. The corpus plants configuration against the scanner the
    job installed. It has to run in that job, before the job's first scan, under the scan's own
    ``if:`` so that it runs whenever the scan does, and without ``continue-on-error``, which would
    make its failure as quiet as the one it catches.

    Args:
      name: The scanner's key in ``GUARDED``.

    Returns:
      None.

    Raises:
      AssertionError: When a scanning job has no corpus step, runs it after its first scan,
        runs it under another condition or lets it fail quietly, or when a known scanning job is
        not found.
    """
    guarded = GUARDED[name]
    checked = set()
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for job, steps in _steps_by_job(workflow).items():
            scans = [i for i, step in enumerate(steps) if any(guarded.wrapped.search(line) for line in _script_lines(step))]
            if not scans:
                continue
            checked.add((workflow.name, job))
            corpus = [i for i, step in enumerate(steps) if any(guarded.corpus.search(line) for line in _script_lines(step))]
            where = f"{workflow.name} / {job}"
            assert corpus, f"{where} scans through {guarded.wrapper} without running its corpus"
            assert corpus[0] < scans[0], f"{where} runs the {name} corpus after its first scan, which has already been read"
            proof, first_scan = steps[corpus[0]], steps[scans[0]]
            assert proof.get("if") == first_scan.get("if"), (
                f"{where}: the {name} corpus runs under if={proof.get('if')!r} and the first scan under "
                f"if={first_scan.get('if')!r}, so the scan can run without the proof"
            )
            assert not proof.get("continue-on-error"), f"{where}: the {name} corpus step may fail without failing the job"
    assert guarded.known_jobs <= checked, (
        f"expected {sorted(guarded.known_jobs)} among the jobs scanning through {guarded.wrapper}, found {sorted(checked)}"
    )


def test_the_root_semgrepignore_holds_no_pattern():
    """The repository's root ``.semgrepignore`` exists and ignores nothing.

    Without the file, Semgrep applies a built-in list that skips every ``test/`` directory, under
    the same skip reason as a pattern somebody wrote, and ``semgrep-scan.sh`` refuses that reason.
    The file is what switches the list off. A pattern in it that matches a file is refused by the
    wrapper, but one that matches nothing yet reads as a suppression while suppressing nothing,
    until the day it matches.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the file is missing or holds a line other than a comment or a blank.
    """
    assert ROOT_SEMGREPIGNORE.is_file(), (
        "the root .semgrepignore is missing, so Semgrep's built-in list applies and every scan is refused"
    )


class StepRun(NamedTuple):
    """What one replayed workflow step did.

    Attributes:
      name: The step's name.
      returncode: The step's exit status.
      output: What it printed to stdout and stderr together.
      carried: Every ``$GITHUB_ENV`` value the job holds once the step has finished, last write
        winning, which is what the next step starts with.
    """

    name: str
    returncode: int
    output: str
    carried: dict[str, str]


def _scan_json(enforce_list: pathlib.Path, shape: str) -> str:
    """Builds a Checkov JSON report over every ID on one enforce list.

    Args:
      enforce_list: The list whose IDs the report evaluates.
      shape: ``clean`` passes every ID, ``one-failure`` fails the first ID on one resource and
        passes the rest, and ``unevaluated`` leaves the first ID out, so the narrowing script
        hard-errors on an enforced ID evaluated against nothing.

    Returns:
      The report, as Checkov's ``--output json`` writes it.

    Raises:
      AssertionError: On a shape this does not build.
    """
    assert shape in {"clean", "one-failure", "unevaluated"}, f"unknown report shape {shape!r}"
    ids = [row[0] for row in _list_entries(enforce_list)]
    first, rest = ids[0], ids[1:]
    passed = [{"check_id": check, "resource": "fixture.passing"} for check in (ids if shape == "clean" else rest)]
    failed = [{"check_id": first, "resource": "fixture.failing"}] if shape == "one-failure" else []
    return json.dumps({"results": {"passed_checks": passed, "failed_checks": failed, "skipped_checks": []}})


def _replay_checkov_count(terraform: str, dockerfile: str) -> list[StepRun]:
    """Runs every step that writes or reads the Checkov gate's count, as the runner would.

    First it holds ``CHECKOV_COUNT_STEPS`` to the workflow: they must be exactly the scan job's
    steps that name the count, in the job's order, neither the job nor the workflow may set it in
    an ``env`` block, and no script under ``.github/scripts/`` may name it. A writer the replay did
    not run could hand the gate a number no row sees. Then each script is the workflow's own, run by ``bash -e`` from a checkout holding the
    gate's scripts and both enforce lists, and sits outside that checkout as the runner's does.
    Each step starts with what earlier steps wrote to ``$GITHUB_ENV``, never its own writes, and
    every step runs whatever the one before did, since each carries ``if: always()``. The
    caller's ``CHECKOV_*``, ``GATE_*`` and ``GITHUB_*`` variables are dropped, so a shell that has
    one set cannot hand a step a count.

    Args:
      terraform: The shape of the terraform scan's report, as ``_scan_json`` builds it.
      dockerfile: The shape of the dockerfile scan's report.

    Returns:
      One run per step in ``CHECKOV_COUNT_STEPS``, in order.

    Raises:
      AssertionError: If the steps naming the count are not ``CHECKOV_COUNT_STEPS``, if an
        ``env`` block or a gate script names it, if a step uses an expression the replay cannot
        evaluate or writes
        ``$GITHUB_ENV`` in a form the replay cannot read, or if ``bash`` or ``jq`` is not
        installed.
    """
    bash, jq = shutil.which("bash"), shutil.which("jq")
    assert bash and jq, "bash and jq are needed to run the gate's steps; CI has both, and a laptop without them should say so"
    document = yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))
    scan = document["jobs"]["scan"]
    preset = [where for where, env in (("workflow", document.get("env")), ("scan job", scan.get("env"))) if COUNT_NAME.search(json.dumps(env or {}))]
    assert not preset, f"the {' and '.join(preset)} env names CHECKOV_FINDINGS, a value the gate reads whenever no step writes one"
    touching = [
        str(step.get("name"))
        for step in scan["steps"]
        if any(COUNT_NAME.search(line) for line in _script_lines(step))
        or COUNT_NAME.search(json.dumps({key: value for key, value in step.items() if key != "run"}, default=str))
    ]
    assert touching == list(CHECKOV_COUNT_STEPS), (
        f"the scan job's steps naming CHECKOV_FINDINGS are {touching}, not {list(CHECKOV_COUNT_STEPS)}. A step "
        "that writes or reads the count and is not replayed can hand the gate a number no row here sees: add it "
        "to CHECKOV_COUNT_STEPS in the job's order and stage it in the rows."
    )
    hidden = [
        path.relative_to(ROOT).as_posix()
        for path in sorted(GATE_SCRIPT.parent.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and COUNT_NAME.search(path.read_text(encoding="utf-8", errors="ignore"))
    ]
    assert not hidden, (
        f"{hidden} name CHECKOV_FINDINGS. A write there reaches the gate from a step whose own script never "
        "names the count, so the check above cannot see it: keep every write of the count in security.yml."
    )
    steps = {step.get("name"): step for step in scan["steps"]}
    base = {key: value for key, value in os.environ.items() if not key.startswith(("CHECKOV_", "GATE_", "GITHUB_"))}
    base["GATE_CHECKOV"] = _gate_value(SECURITY_WORKFLOW, "CHECKOV")
    runs: list[StepRun] = []
    carried: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        checkout = root / "checkout"
        for source in (NARROWING_SCRIPT, GATE_SCRIPT, ENFORCED_LIST, DOCKERFILE_ENFORCED_LIST):
            (checkout / source.relative_to(ROOT)).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, checkout / source.relative_to(ROOT))
        (checkout / "checkov.json").write_text(_scan_json(ENFORCED_LIST, terraform), encoding="utf-8")
        (checkout / "checkov-dockerfile.json").write_text(_scan_json(DOCKERFILE_ENFORCED_LIST, dockerfile), encoding="utf-8")
        for index, name in enumerate(CHECKOV_COUNT_STEPS):
            step = steps.get(name)
            assert step, f"security.yml's scan job has no step named {name!r}, so the replay would skip it"
            assert "${{" not in str(step["run"]) and not step.get("env"), f"{name!r} reads an expression the replay cannot evaluate"
            script, env_file = root / f"step-{index}.sh", root / f"env-{index}"
            script.write_text(str(step["run"]), encoding="utf-8")
            env_file.touch()
            finished = subprocess.run(  # noqa: S603
                [bash, "-e", str(script)],
                cwd=checkout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                env={**base, **carried, "GITHUB_ENV": str(env_file), "GITHUB_STEP_SUMMARY": str(root / "summary.md")},
            )
            for line in env_file.read_text(encoding="utf-8").splitlines():
                assert "=" in line and "<<" not in line.split("=", 1)[0], f"{name!r} wrote {line!r}, a form the replay cannot read"
                key, value = line.split("=", 1)
                carried[key] = value
            runs.append(StepRun(name, finished.returncode, finished.stdout + finished.stderr, dict(carried)))
    return runs


@pytest.mark.parametrize(
    ("terraform", "dockerfile", "refusal", "verdict"),
    [
        pytest.param("clean", "one-failure", None, "1 finding(s) and gate=block", id="both-narrowings-count"),
        pytest.param(
            "clean", "unevaluated", "evaluated against nothing", "finding count 'no-count' is not a number",
            id="the-dockerfile-narrowing-fails-after-a-terraform-zero",
        ),
        pytest.param(
            "unevaluated", "clean", "the terraform narrowing produced no count ('')",
            "finding count 'no-count' is not a number", id="the-terraform-narrowing-fails",
        ),
    ],
)
def test_the_checkov_gate_counts_both_frameworks_or_refuses(terraform: str, dockerfile: str, refusal: str | None, verdict: str):
    """The Checkov gate reads a total of both frameworks, and refuses any count that is less.

    Two steps write the one count the gate reads, the terraform narrowing and then the dockerfile
    narrowing adding to it, and the gate's ``:-no-count`` default covers only a count nothing
    wrote. A narrowing that hard-errors writes nothing, so when the dockerfile narrowing failed
    after a terraform zero, the zero stood as the total and the gate printed "no findings" over a
    red step; the dockerfile narrowing now writes the sentinel before it narrows. The terraform
    narrowing has to stay the first writer, or its own failure would leave an earlier number
    standing the same way, and the dockerfile step has to refuse the empty count that failure
    leaves rather than add it, because bash arithmetic reads an empty value as zero.

    Args:
      terraform: The shape of the terraform scan's report.
      dockerfile: The shape of the dockerfile scan's report.
      refusal: What the dockerfile narrowing prints when it fails, or ``None`` where neither
        narrowing fails.
      verdict: What the gate says about the count it is handed.

    Returns:
      None.

    Raises:
      AssertionError: When a row does not stage its case, when the gate says anything else or
        passes, or when the dockerfile narrowing fails for another reason or not at all.
    """
    narrowed_terraform, narrowed_dockerfile, gate = _replay_checkov_count(terraform, dockerfile)
    if terraform == "clean":
        assert narrowed_terraform.carried.get("CHECKOV_FINDINGS") == "0", (
            f"the terraform narrowing did not write a zero, so this row does not stage its case: {narrowed_terraform}"
        )
    else:
        assert narrowed_terraform.returncode != 0 and "evaluated against nothing" in narrowed_terraform.output, (
            f"the terraform narrowing did not hard-error, so this row does not stage its case: {narrowed_terraform}"
        )
        assert "CHECKOV_FINDINGS" not in narrowed_terraform.carried, (
            f"the terraform narrowing failed after CHECKOV_FINDINGS={narrowed_terraform.carried['CHECKOV_FINDINGS']!r} "
            "was written, a number that stands as the count once the narrowing writes nothing"
        )
    handed = narrowed_dockerfile.carried.get("CHECKOV_FINDINGS")
    assert verdict in gate.output and gate.returncode != 0, (
        f"the gate was handed CHECKOV_FINDINGS={handed!r} and should say {verdict!r} and fail; "
        f"it exited {gate.returncode} saying: {gate.output.strip()}"
    )
    if refusal is None:
        assert narrowed_dockerfile.returncode == 0, narrowed_dockerfile
    else:
        assert narrowed_dockerfile.returncode != 0 and refusal in narrowed_dockerfile.output, (
            f"the dockerfile narrowing should fail saying {refusal!r}; it exited "
            f"{narrowed_dockerfile.returncode}: {narrowed_dockerfile.output}"
        )


def _rule_exclusions(node: object, where: str) -> list[tuple[str, str]]:
    """Every mention of a Semgrep rule exclusion in a parsed workflow, keys included, with the step it sits in.

    Every string is read, not only ``run`` scripts, so a ``with:`` input or an ``env:`` value is
    seen too; a ``run`` script's comment lines are dropped, since they run nothing.

    Args:
      node: A parsed workflow, or any part of one.
      where: The name of the step ``node`` sits in, or a label for text outside any step.

    Returns:
      One ``(where, rule ID)`` pair per mention, in document order; the ID is empty where the
      mention is not followed by one.

    Raises:
      None.
    """
    if isinstance(node, dict):
        found = []
        for key, value in node.items():
            found += [(where, rule) for rule in EXCLUDE_RULE.findall(str(key))]
            if key == "steps" and isinstance(value, list):
                for step in value:
                    label = str(step.get("name") or step.get("uses") or "(unnamed step)") if isinstance(step, dict) else where
                    found += _rule_exclusions(step, label)
            elif key == "run" and isinstance(value, str):
                script = "\n".join(_script_lines(node)).replace("\\\n", " ")
                found += [(where, rule) for rule in EXCLUDE_RULE.findall(script)]
            else:
                found += _rule_exclusions(value, where)
        return found
    if isinstance(node, list):
        return [pair for item in node for pair in _rule_exclusions(item, where)]
    return [(where, rule) for rule in EXCLUDE_RULE.findall(str(node))]


@pytest.mark.parametrize(
    ("workflow", "exclusions"),
    [
        ({"steps": [{"name": "S", "run": "semgrep scan --exclude-rule=a lambdas"}]}, [("S", "a")]),
        ({"steps": [{"name": "S", "run": 'semgrep scan "--exclude-rule" "b" lambdas'}]}, [("S", "b")]),
        ({"steps": [{"name": "S", "run": "args=('--exclude-rule' \"$r\")"}]}, [("S", "$r")]),
        ({"steps": [{"name": "S", "run": "semgrep scan --exclude-rule \\\n  c lambdas"}]}, [("S", "c")]),
        ({"steps": [{"uses": "docker://semgrep/semgrep", "with": {"args": "scan --exclude-rule=d ."}}]}, [("docker://semgrep/semgrep", "d")]),
        ({"env": {"ARGS": "--exclude-rule=e"}, "jobs": {}}, [("(outside any step)", "e")]),
        ({"steps": [{"name": "K", "uses": "some/action@v1", "with": {"exclude-rule": "f"}}]}, [("K", "")]),
        ({"steps": [{"name": "S", "run": "# --exclude-rule=g\nsemgrep scan --exclude=node_modules ."}]}, []),
    ],
)
def test_an_exclusion_is_found_wherever_a_workflow_puts_it(workflow: dict, exclusions: list[tuple[str, str]]):
    """The collector's reading of one workflow, against exclusions known to be in it.

    The live sweep below finds the one exclusion the workflows hold, which proves nothing about
    whether it would see a quoted flag, a ``with:`` input, an ``env:`` value or a bare key. These
    rows are the positive control for each, and the last is the control for silence: a comment
    line and a path ``--exclude`` are not rule exclusions.

    Args:
      workflow: A parsed workflow, or the part of one that matters.
      exclusions: The ``(step, rule ID)`` pairs it holds.

    Returns:
      None.

    Raises:
      AssertionError: When the collector reads the workflow any other way.
    """
    assert _rule_exclusions(workflow, "(outside any step)") == exclusions


def test_semgrep_excludes_exactly_the_flask_rule():
    """The Flask false positive is the only Semgrep rule any workflow excludes, and only from the Lambdas scan.

    An exclusion removes findings, so a second one arrives as green as the scan it narrowed, and
    the disposition docs/security-baseline.md asks for is the only record it would leave. This
    makes adding one a deliberate edit here too. Equality with the one known exclusion is its own
    positive control: a collector that stopped matching would find none, and fail.

    Any mention of ``exclude-rule`` counts as an exclusion, however it is quoted and wherever in
    the workflow it sits. Unlike the Checkov sweep above, nothing is exempted as a harmless form,
    so a harmless new mention fails loudly rather than a new quoting passing quietly. An inline
    ``nosemgrep`` or a ``.semgrepignore`` narrows the scan without any workflow saying so, and is
    not seen here. Nor can it tell a correct rule ID from a wrong one: it reads the string, not
    what Semgrep matches.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a workflow excludes any other rule, excludes this one twice or from
        another step, mentions an exclusion without a rule ID after it, or when no exclusion is
        found at all.
    """
    found = []
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        found += [(workflow.name, where, rule) for where, rule in _rule_exclusions(document, "(outside any step)")]
    assert found == [("security.yml", "Scan the Lambdas", FLASK_RULE)], (
        f"Semgrep rule exclusions found: {found}. Each one narrows what SAST reports and needs its "
        "own disposition in docs/security-baseline.md; once it has one, add it to this test. A "
        "mention that is not a Semgrep exclusion (another tool's flag, prose in a step name or an "
        "echo) is reworded instead, never added here."
    )


    patterns = [
        line for line in ROOT_SEMGREPIGNORE.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")
    ]
    assert not patterns, (
        f"the root .semgrepignore holds {patterns}. A path a scan must not cover goes on that scan's "
        "invocation as --exclude, where the gate's reviewer reads it."
    )


def _step_named(name: str) -> dict:
    """Returns the security scan job's step with the given name.

    Args:
      name: The step's ``name``.

    Returns:
      The step mapping, including its ``run`` script.

    Raises:
      AssertionError: If the job has no step, or more than one, with that name.
    """
    steps = [step for step in _steps_by_job(SECURITY_WORKFLOW)["scan"] if step.get("name") == name]
    assert len(steps) == 1, f"security.yml's scan job has {len(steps)} step(s) named {name!r}, not one"
    return steps[0]


def _run_steps(root: pathlib.Path, names: list[str], reports: dict[str, str]) -> list[subprocess.CompletedProcess[str]]:
    """Runs security.yml steps in order the way the runner does, carrying ``$GITHUB_ENV`` between them.

    Each script runs under ``bash -e``, the command the runner uses for a step that names no
    ``shell``, which is every step in this workflow: no ``pipefail``. It runs from a checkout
    holding the reports given and the scripts the steps call, with the workflow's own ``env`` block
    and every value an earlier step wrote to ``$GITHUB_ENV``. The script itself sits outside the
    checkout, as the runner's does.

    Args:
      root: A directory private to this run.
      names: The steps to run, by name, in order.
      reports: The scan reports present in the checkout, by file name.

    Returns:
      Each step's completed process, in order.

    Raises:
      None.
    """
    checkout, scripts = root / "checkout", root / "checkout" / ".github" / "scripts"
    scripts.mkdir(parents=True)
    for script in STEP_SCRIPTS:
        shutil.copy2(ROOT / ".github" / "scripts" / script, scripts / script)
    for file, content in reports.items():
        (checkout / file).write_text(content, encoding="utf-8")
    github_env, summary = root / "github-env", root / "step-summary"
    github_env.touch()
    summary.touch()
    workflow_env = {key: str(value) for key, value in yaml.safe_load(SECURITY_WORKFLOW.read_text(encoding="utf-8"))["env"].items()}
    runs = []
    for index, name in enumerate(names):
        script = root / f"step-{index}.sh"
        script.write_text(_step_named(name)["run"], encoding="utf-8")
        written = dict(line.split("=", 1) for line in github_env.read_text(encoding="utf-8").splitlines() if "=" in line)
        environment = {
            key: value for key, value in os.environ.items() if not key.endswith("_FINDINGS") and not key.startswith("GATE_")
        }
        environment.update(workflow_env, **written, GITHUB_ENV=str(github_env), GITHUB_STEP_SUMMARY=str(summary), TMPDIR=str(root))
        runs.append(
            subprocess.run(  # noqa: S603
                [shutil.which("bash") or "bash", "-e", str(script)],
                cwd=checkout,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                env=environment,
            )
        )
    return runs


@pytest.mark.parametrize("name", sorted(GATED_REPORTS))
def test_a_refused_scan_reaches_its_gate_as_no_count(name: str, tmp_path: pathlib.Path):
    """A scan whose report its wrapper deleted is counted as nothing, and its gate fails.

    The wrapper deletes the report of a scan it refused, so the report being missing is what a
    refusal looks like from the summary step. Measured before this was written: both summaries read
    a missing report as zero, and the gate then printed "no findings" for a scan that never ran.

    Args:
      name: The scanner's key in ``GATED_REPORTS``.
      tmp_path: A directory private to this test.

    Returns:
      None.

    Raises:
      AssertionError: When the summary counts the missing report, or the gate passes on it.
    """
    summarize, gate, variable, reports, refused = GATED_REPORTS[name]
    left = {file: content for file, content in reports.items() if file != refused}

    summary_run, gate_run = _run_steps(tmp_path, [summarize, gate], left)

    assert summary_run.returncode != 0, f"{summarize} passed with {refused} missing: {summary_run.stdout}{summary_run.stderr}"
    assert f"{refused} missing" in summary_run.stdout + summary_run.stderr
    assert f"{variable}=no-report" in (tmp_path / "github-env").read_text(encoding="utf-8")
    assert gate_run.returncode == 2, f"{gate} exited {gate_run.returncode}: {gate_run.stdout}{gate_run.stderr}"
    assert "finding count 'no-report' is not a number" in gate_run.stdout + gate_run.stderr


@pytest.mark.parametrize("name", sorted(GATED_REPORTS))
def test_a_gate_with_no_count_written_fails(name: str, tmp_path: pathlib.Path):
    """A gate that runs with no count written reads its non-numeric default and fails.

    ``${VAR:-0}`` substitutes on empty as well as unset, so a numeric default turns "nothing was
    counted" into "clean".

    Args:
      name: The scanner's key in ``GATED_REPORTS``.
      tmp_path: A directory private to this test.

    Returns:
      None.

    Raises:
      AssertionError: When the gate passes, or fails for another reason.
    """
    _, gate, _, _, _ = GATED_REPORTS[name]

    (gate_run,) = _run_steps(tmp_path, [gate], {})

    assert gate_run.returncode == 2, f"{gate} exited {gate_run.returncode}: {gate_run.stdout}{gate_run.stderr}"
    assert f"finding count '{SENTINEL}' is not a number" in gate_run.stdout + gate_run.stderr


@pytest.mark.parametrize("name", sorted(GATED_REPORTS))
def test_a_clean_scan_passes_its_gate(name: str, tmp_path: pathlib.Path):
    """With every report present and empty, the summary counts zero and the gate passes.

    The positive control for the two tests above: a harness that could not run these steps at all
    would make every gate fail, and those tests would pass on it.

    Args:
      name: The scanner's key in ``GATED_REPORTS``.
      tmp_path: A directory private to this test.

    Returns:
      None.

    Raises:
      AssertionError: When the summary or the gate fails on clean reports.
    """
    summarize, gate, variable, reports, _ = GATED_REPORTS[name]

    summary_run, gate_run = _run_steps(tmp_path, [summarize, gate], reports)

    assert summary_run.returncode == 0, f"{summarize} failed on clean reports: {summary_run.stdout}{summary_run.stderr}"
    assert f"{variable}=0" in (tmp_path / "github-env").read_text(encoding="utf-8")
    assert gate_run.returncode == 0, f"{gate} failed on a zero count: {gate_run.stdout}{gate_run.stderr}"
    assert "no findings." in gate_run.stdout
