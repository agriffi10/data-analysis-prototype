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

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
SECURITY_WORKFLOW = ROOT / ".github" / "workflows" / "security.yml"
INFRA_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-infra.yml"
ENFORCED_LIST = ROOT / ".github" / "checkov-enforced.txt"
DOCKERFILE_ENFORCED_LIST = ROOT / ".github" / "checkov-dockerfile-enforced.txt"
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
ENFORCED_COUNT = 79

#: The same pin for the dockerfile framework's list, for the same reason. Measured at 38 passed /
#: 2 failed against checkov 3.3.9 on lambdas/Dockerfile; the two failures — no HEALTHCHECK and no
#: USER — are dispositioned in docs/security-baseline.md rather than enforced.
DOCKERFILE_ENFORCED_COUNT = 21

#: The gate steps must default to a NON-NUMERIC sentinel. `${VAR:-0}` substitutes on empty as
#: well as unset, so a numeric default turns "the narrowing step wrote nothing" into "clean".
SENTINEL = "no-count"

#: What a workflow line may say that contains "checkov" without running it: the gate's own four
#: scripts by name, a scan output or list file, the pinned install, and the artifact's name in
#: backticks, as a job summary prints it. Anything else on a line that still says "checkov" is
#: taken to run it, however it is spelled, which is why this lists the harmless forms rather than
#: the invocations. A new script is added here by hand, because this sweep reads workflows and not
#: the scripts they call.
_NOT_A_SCAN = re.compile(
    r"(?<![\w-])checkov-(?:scan|scan-test|enforced|plan-iam)\.sh(?![\w.-])"
    r"|[\w./-]*checkov[\w-]*\.(?:json|txt)(?![\w.-])"
    r"""|\bpip3?\s+install\s+(["']?)checkov==[^\s"']+\1"""
    r"|\\?`checkov\\?`"
)

#: The wrapper that refuses configuration Checkov reports taking from outside its command line,
#: however its path is spelled, capturing the scan's first two arguments.
WRAPPED_CHECKOV = re.compile(r"(?<![\w-])checkov-scan\.sh\s+(\S+\s+\S+)")

#: The fixture corpus that proves the wrapper's refusal still fires, however its path is spelled.
CORPUS_CALL = re.compile(r"(?<![\w-])checkov-scan-test\.sh(?![\w.-])")

#: Every scan that must be found going through the wrapper, as (workflow, first two arguments).
#: The positive control for the sweep below: a collector that stopped matching would otherwise
#: report no bare invocation and pass.
KNOWN_WRAPPED_SCANS = {
    ("security.yml", "-d infra"),
    ("security.yml", "-f lambdas/Dockerfile"),
    ("deploy-infra.yml", "-f plan.json"),
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


def _runs_checkov_outside_the_wrapper(line: str) -> bool:
    """Says whether one line of a ``run`` script runs Checkov other than through the wrapper.

    It removes the forms that say "checkov" without running it (``_NOT_A_SCAN``) and reads what
    is left, so a spelling nobody listed, such as an environment prefix, ``time``, ``pipx run``
    or a container image, is still caught. The cost is a false alarm on a new harmless form,
    which fails loudly and is fixed by naming it there.

    Args:
      line: One line of a step's ``run`` script, comment lines already removed.

    Returns:
      True when the line still says "checkov" once the harmless forms are gone.

    Raises:
      None.
    """
    return "checkov" in _NOT_A_SCAN.sub("", line)


@pytest.mark.parametrize(
    ("line", "runs_it"),
    [
        ("checkov -d infra \\", True),
        ("CKV_SKIP_CHECK=CKV_AWS_355 checkov -f plan.json", True),
        ("env X=1 checkov -d infra", True),
        ("if checkov -d infra; then", True),
        ("time checkov -d infra", True),
        ("pipx run checkov -d infra", True),
        ('docker run --rm -v "$PWD:/w" bridgecrew/checkov -d /w/infra', True),
        ("python3 -m checkov.main -d infra", True),
        ("out=$(checkov -f plan.json)", True),
        ("out=`checkov -f plan.json`", True),
        (".github/scripts/checkov-scan.sh -d infra && checkov -f plan.json", True),
        (".github/scripts/checkov-bare.sh -d infra", True),
        ("../.github/scripts/checkov-scan.sh -f plan.json \\", False),
        ("bash ./.github/scripts/checkov-scan.sh -d infra", False),
        (".github/scripts/checkov-scan-test.sh", False),
        ('pip install "checkov==${CHECKOV_VERSION}"', False),
        ("findings=$(.github/scripts/checkov-enforced.sh checkov.json .github/checkov-enforced.txt)", False),
        ("findings=$(../.github/scripts/checkov-plan-iam.sh checkov-plan.json ../.github/checkov-plan-accepted.txt)", False),
        ('echo "::error title=Checkov (plan)::output is not valid"', False),
        ('echo "_Per-resource detail is in the \\`checkov\\` artifact._"', False),
    ],
)
def test_a_line_that_runs_checkov_is_found_however_it_is_spelled(line: str, runs_it: bool):
    """The sweep's reading of one line, against a line whose verdict is known.

    The sweep below passes on every workflow here, which proves the workflows pass and nothing
    about whether the sweep can see an invocation. These rows are the positive control: the
    spellings that escaped a sweep matching command positions, a wrapped scan followed by a bare
    one, a script the allowlist does not name, and, for silence, every harmless form the
    workflows use today.

    Args:
      line: One line of a ``run`` script.
      runs_it: Whether the line runs Checkov outside the wrapper.

    Returns:
      None.

    Raises:
      AssertionError: When the sweep reads the line the other way.
    """
    assert _runs_checkov_outside_the_wrapper(line) is runs_it, (
        f"{line!r} was read as {'running' if not runs_it else 'not running'} Checkov outside the wrapper"
    )


def test_every_checkov_scan_goes_through_the_config_refusal():
    """No workflow runs Checkov except through ``checkov-scan.sh``.

    Checkov takes configuration from a ``.checkov.yml`` in the scanned directory, the working
    directory or $HOME, and from its flags' environment variables. Measured: one such file took
    CKV_AWS_355 off the blocking plan gate while every other IAM check still ran. The wrapper
    refuses to scan when Checkov reports configuration from outside its command line. A scan
    added without it is open to the same file again and looks exactly as green, and so is the
    Checkov GitHub Action, which runs the scanner where the wrapper cannot reach.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a step runs Checkov outside the wrapper or through its Action, or when
        a known scan is not found going through the wrapper, which is what a collector that
        stopped matching would look like.
    """
    bare = []
    wrapped = set()
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for job, steps in _steps_by_job(workflow).items():
            for step in steps:
                if "checkov" in str(step.get("uses", "")).lower():
                    bare.append(f"{workflow.name} / {job}: uses {step['uses']}")
                for line in _script_lines(step):
                    if _runs_checkov_outside_the_wrapper(line):
                        bare.append(f"{workflow.name} / {job}: {line.strip()}")
                    for match in WRAPPED_CHECKOV.finditer(line):
                        wrapped.add((workflow.name, " ".join(match.group(1).split())))
    assert not bare, (
        "Checkov runs without .github/scripts/checkov-scan.sh, so a .checkov.yml or a CKV_* "
        f"variable can change what its gate counts: {bare}"
    )
    missing = KNOWN_WRAPPED_SCANS - wrapped
    assert not missing, (
        f"scan(s) {sorted(missing)} not found going through checkov-scan.sh (found {sorted(wrapped)}). "
        "Either a scan moved or the collector stopped matching, and a collector matching nothing "
        "would also find no bare invocation."
    )


def test_the_config_refusal_is_proven_before_each_job_scans():
    """Every job that scans through the wrapper runs its fixture corpus first, under the same condition.

    The refusal never fires on a normal run, so a Checkov or ConfigArgParse release that stopped
    reporting a config file the scan still reads would switch every refusal off with nothing
    going red. The corpus plants configuration against the Checkov the job installed. It has to
    run in that job, before the job's first scan, under the scan's own ``if:`` so that it runs
    whenever the scan does, and without ``continue-on-error``, which would make its failure as
    quiet as the one it catches.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a scanning job has no corpus step, runs it after its first scan,
        runs it under another condition or lets it fail quietly, or when the two known scanning
        jobs are not both found.
    """
    checked = set()
    workflows = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    for workflow in workflows:
        for job, steps in _steps_by_job(workflow).items():
            scans = [i for i, step in enumerate(steps) if any(WRAPPED_CHECKOV.search(line) for line in _script_lines(step))]
            if not scans:
                continue
            checked.add((workflow.name, job))
            corpus = [i for i, step in enumerate(steps) if any(CORPUS_CALL.search(line) for line in _script_lines(step))]
            where = f"{workflow.name} / {job}"
            assert corpus, f"{where} scans through checkov-scan.sh without running checkov-scan-test.sh"
            assert corpus[0] < scans[0], f"{where} runs checkov-scan-test.sh after its first scan, which has already been read"
            proof, first_scan = steps[corpus[0]], steps[scans[0]]
            assert proof.get("if") == first_scan.get("if"), (
                f"{where}: the corpus runs under if={proof.get('if')!r} and the first scan under "
                f"if={first_scan.get('if')!r}, so the scan can run without the proof"
            )
            assert not proof.get("continue-on-error"), f"{where}: the corpus step may fail without failing the job"
    assert {("security.yml", "scan"), ("deploy-infra.yml", "plan")} <= checked, (
        f"expected the security scan job and the infra plan job among the scanning jobs, found {sorted(checked)}"
    )
