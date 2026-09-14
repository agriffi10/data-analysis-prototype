"""The shared image-tag check, and the deploy steps that run it, are EXECUTED here, not read.

A dispatch's ``image_tag`` is typed by a person, looked up in the registry and printed. Outside the
tag grammar the AWS CLI respells it before looking it up, so a padded or quoted tag is found and
then handed on as typed; and a refusal that prints it lets a newline start a workflow command of
the caller's choosing. So the check is run over inputs of both kinds, and each step that reads the
input first is run as a script with the value a dispatch would carry. The assertions are on what
the step asked the registry and what it printed, never on the exit code alone: a refusal for the
wrong reason exits the same way.

The stub ``aws`` models the CLI's respelling as measured on aws-cli 2.35.1's own unpacked
parameter: ``' abc '``, ``"'abc'"``, ``'"abc"'`` and ``abc`` followed or preceded by a newline, or
followed by a carriage return or a no-break space, are all sent as ``abc``; a newline inside the
value is kept. A stub comparing the raw argument would refuse a padded tag as unknown where the real
CLI finds it, so a step that lost its check would fail here differently from how it fails in
production.

Everything runs under ``C.UTF-8``, where a non-ASCII character is one character to the regex
rather than several bytes. The suite runs on the machine it is invoked on and nowhere else, which
bounds two claims. That ``$`` matches only at the end of the string rests on bash compiling ``=~``
without ``REG_NEWLINE``, which POSIX then defines. And the check's pin to the C locale is visible
only where a locale orders a bracket range by collation: glibc's ``en_US.UTF-8`` puts an accented
``e``, a fullwidth ``A`` and an Arabic-Indic three inside ``[A-Za-z0-9]``, which macOS never does,
ordering every range by code point. The non-ASCII rows below pass here with or without the pin;
one test stages the hazard where the platform allows it and skips, saying so, where it cannot.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The directory holding the workflows under test.
  CHECK: The shared check under test.
  FAKE_AWS: The stub ``aws``. It logs every call as a JSON list, answers ``describe-repositories``
    with a fixed URI and ``describe-images`` from ``FAKE_EXISTING_TAGS``, and logs the tag of a
    ``describe-images`` call as the CLI would send it.
  HEAD: The sha a run stands on.
  HELD: A tag the stub registry holds.
  UNKNOWN: A bare tag the stub registry does not hold.
  REPOSITORY_URI: What the stub answers ``describe-repositories`` with.
  ACCEPTED: Inputs the check admits, by label.
  REFUSED: Inputs the check refuses, by label. Every one carries ``HELD``, so its absence from the
    output is what proves the refusal did not print the input.
  RESPELLED: The refused inputs the CLI would reduce to ``HELD``, plus one that carries a workflow
    command after a newline — the two hazards a step without the check reaches.
  ENTRY_STEPS: The steps that read a dispatch's ``image_tag`` first, as (workflow, job, step id).
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile
from typing import NamedTuple

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CHECK = ROOT / ".github" / "scripts" / "check-image-tag.sh"

FAKE_AWS = """#!/usr/bin/env python3
import json, os, sys

argv = sys.argv[1:]
record = argv[:2]
if argv[:2] == ["ecr", "describe-images"]:
    sent = [a for a in argv if a.startswith("imageTag=")][0].split("=", 1)[1].strip()
    if len(sent) > 1 and sent[0] == sent[-1] and sent[0] in "'\\"":
        sent = sent[1:-1]
    record = [*record, sent]
with open(os.environ["FAKE_AWS_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(record) + "\\n")
if argv[:2] == ["ecr", "describe-repositories"]:
    print(os.environ["FAKE_REPOSITORY_URI"])
elif argv[:2] == ["ecr", "describe-images"]:
    sys.exit(0 if record[2] in os.environ["FAKE_EXISTING_TAGS"].split(",") else 254)
else:
    sys.exit(2)
"""

HEAD = "c" * 40
HELD = "5ca1ab1e" * 5
UNKNOWN = "d" * 40
REPOSITORY_URI = "123456789012.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda"

ACCEPTED = {
    "empty": "",
    "commit-sha": HELD,
    "leading-underscore": f"_{HELD}",
    "dots-and-hyphens": f"v1.2.3-rc_{HELD}",
    "the-longest-tag": HELD + "a" * (128 - len(HELD)),
}

REFUSED = {
    "leading-space": f" {HELD}",
    "trailing-space": f"{HELD} ",
    "single-quoted": f"'{HELD}'",
    "double-quoted": f'"{HELD}"',
    "trailing-newline": f"{HELD}\n",
    "leading-newline": f"\n{HELD}",
    "trailing-carriage-return": f"{HELD}\r",
    "trailing-no-break-space": f"{HELD}\u00a0",
    "accented-letter": f"{HELD}\u00e9",
    "fullwidth-letter": f"{HELD}\uff21",
    "arabic-indic-digit": f"{HELD}\u0663",
    "newline-then-command": f"{HELD}\n::notice title=Plan::spoofed",
    "leading-dot": f".{HELD}",
    "leading-hyphen": f"-{HELD}",
    "repository-and-tag": f"dat-prod-lambda:{HELD}",
    "one-past-the-longest": HELD + "a" * (129 - len(HELD)),
}

RESPELLED = {
    "leading-space": f" {HELD}",
    "trailing-space": f"{HELD} ",
    "single-quoted": f"'{HELD}'",
    "trailing-newline": f"{HELD}\n",
    "leading-newline": f"\n{HELD}",
    "unknown-then-command": f"{UNKNOWN}\n::notice title=Rollback::spoofed",
}

ENTRY_STEPS = (
    ("deploy-lambdas.yml", "plan", "image"),
    ("deploy-lambda-image.yml", "push", "names"),
    ("deploy-spa-image.yml", "deploy", "names"),
)


class StepRun(NamedTuple):
    """What one run of a workflow step did.

    Attributes:
      returncode: The step's exit status.
      stdout: What it printed to stdout and stderr together, so a command on either is counted.
      calls: Every ``aws`` call it made, as logged by the stub.
      outputs: What it wrote to ``$GITHUB_OUTPUT``.
    """

    returncode: int
    stdout: str
    calls: list[list[str]]
    outputs: dict[str, str]


def _bash() -> str:
    """Finds the shell the check and the steps are written in.

    Args:
      None.

    Returns:
      An absolute path to ``bash``.

    Raises:
      AssertionError: If there is no ``bash`` on PATH.
    """
    bash = shutil.which("bash")
    assert bash, "no bash on PATH; the tag check is a bash script and cannot be run without one"
    return bash


def _environment(**overrides: str) -> dict[str, str]:
    """Builds the environment every script here runs in.

    Args:
      **overrides: Variables to set on top of the caller's environment.

    Returns:
      The caller's environment under ``C.UTF-8``, with the overrides applied.

    Raises:
      None.
    """
    return {**os.environ, "LC_ALL": "C.UTF-8", **overrides}


def _run_check(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Runs the shared check with the arguments a caller would pass.

    Args:
      *arguments: The check's arguments, normally one tag.

    Returns:
      The completed process.

    Raises:
      None.
    """
    return subprocess.run(  # noqa: S603
        [_bash(), str(CHECK), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_environment(),
        timeout=30,
    )


def _step(workflow: str, job: str, step_id: str) -> dict:
    """Returns a workflow step by id, so a reordering cannot point a test at another step.

    Args:
      workflow: The workflow's file name.
      job: The job holding the step.
      step_id: The step's ``id``.

    Returns:
      The step mapping, including its ``run`` script and ``env`` block.

    Raises:
      AssertionError: If the job has no step with that id.
    """
    document = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    steps = [step for step in document["jobs"][job]["steps"] if step.get("id") == step_id]
    assert steps, f"`{workflow}` has no step with id `{step_id}` in job `{job}`"
    return steps[0]


def _tag_variable(step: dict) -> str:
    """Names the variable a step reads the dispatch's ``image_tag`` through.

    Read from the step's own ``env`` block rather than passed in, so a test cannot set a variable
    the step no longer reads and pass on the empty value the step then sees.

    Args:
      step: The step mapping.

    Returns:
      The one ``env`` key whose value reads ``inputs.image_tag``.

    Raises:
      AssertionError: If the step maps the input to no variable, or to more than one.
    """
    names = [key for key, value in step["env"].items() if "inputs.image_tag" in str(value)]
    assert len(names) == 1, f"the step reads inputs.image_tag through {names}, not one variable"
    return names[0]


def _run_step(workflow: str, job: str, step_id: str, tag: str) -> StepRun:
    """Runs a workflow step's real script against the stub registry, as a dispatch would.

    The layout is the runner's: the step runs from a checkout holding a copy of the shared check
    at the path the workflow names, and its script sits OUTSIDE that checkout, as the runner's does
    under ``$RUNNER_TEMP``. A script written into the checkout would let a path taken relative to
    ``$0`` resolve here and fail on the runner.

    Args:
      workflow: The workflow's file name.
      job: The job holding the step.
      step_id: The step's ``id``.
      tag: The dispatch's ``image_tag`` input.

    Returns:
      What the step did.

    Raises:
      None.
    """
    step = _step(workflow, job, step_id)
    with tempfile.TemporaryDirectory() as work:
        root = pathlib.Path(work)
        binaries, checkout = root / "bin", root / "checkout"
        scripts = checkout / ".github" / "scripts"
        binaries.mkdir()
        scripts.mkdir(parents=True)
        (binaries / "aws").write_text(FAKE_AWS, encoding="utf-8")
        (binaries / "aws").chmod(0o755)
        shutil.copy(CHECK, scripts / CHECK.name)
        output, log, script = root / "output.txt", root / "aws.log", root / "step.sh"
        output.touch()
        log.touch()
        script.write_text(step["run"], encoding="utf-8")
        finished = subprocess.run(  # noqa: S603
            [_bash(), str(script)],
            cwd=checkout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env=_environment(
                PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
                TMPDIR=str(root),
                GITHUB_OUTPUT=str(output),
                GITHUB_SHA=HEAD,
                PROJECT="dat",
                ENVIRONMENT="prod",
                FAKE_AWS_LOG=str(log),
                FAKE_REPOSITORY_URI=REPOSITORY_URI,
                FAKE_EXISTING_TAGS=HELD,
                **{_tag_variable(step): tag},
            ),
        )
        return StepRun(
            finished.returncode,
            finished.stdout + finished.stderr,
            [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()],
            dict(
                line.split("=", 1)
                for line in output.read_text(encoding="utf-8").splitlines()
                if "=" in line
            ),
        )


def _commands(stdout: str) -> list[str]:
    """Returns the lines of output the runner would read as workflow commands.

    Args:
      stdout: What a script printed.

    Returns:
      Every line that begins ``::`` once leading whitespace is dropped.

    Raises:
      None.
    """
    return [line for line in stdout.splitlines() if line.lstrip().startswith("::")]


@pytest.mark.parametrize("tag", list(ACCEPTED.values()), ids=list(ACCEPTED))
def test_the_check_admits_a_bare_tag_and_says_nothing(tag):
    """An empty input means this commit, and a bare tag passes silently to be looked up as typed.

    The leading underscore and the 128-character tag are the grammar's two edges.

    Args:
      tag: An input inside the grammar.

    Returns:
      None.

    Raises:
      AssertionError: If a bare tag is refused, or the check prints anything about it.
    """
    finished = _run_check(tag)

    assert finished.returncode == 0, f"{tag!r} was refused:\n{finished.stdout}{finished.stderr}"
    assert finished.stdout + finished.stderr == "", f"{tag!r} printed {finished.stdout!r}"


@pytest.mark.parametrize("tag", list(REFUSED.values()), ids=list(REFUSED))
def test_the_check_refuses_a_malformed_tag_without_printing_it(tag):
    """Anything outside the grammar is refused with one command, and the input is never echoed.

    The space and newline rows come one per side, which is what a dropped anchor or a widened
    character class lets through; the carriage return is a line break to the runner too; and the
    newline-then-command row is the injection itself.

    Args:
      tag: An input outside the grammar.

    Returns:
      None.

    Raises:
      AssertionError: If the input is admitted, refused for another reason, or printed.
    """
    finished = _run_check(tag)
    printed = finished.stdout + finished.stderr

    assert finished.returncode == 1, f"{tag!r} exited {finished.returncode}:\n{printed}"
    assert _commands(finished.stdout) == [finished.stdout.rstrip("\n")], (
        f"{tag!r} printed something besides one workflow command:\n{printed}"
    )
    assert finished.stdout.startswith("::error title=Malformed tag::"), printed
    assert HELD not in printed, f"the refusal of {tag!r} printed the input:\n{printed}"


def test_the_check_refuses_a_letter_a_collating_locale_puts_inside_a_range():
    """Under a locale that orders a range by collation, the check still admits only ASCII.

    The hazard is staged before it is asserted over: bash on this platform must itself put an
    accented ``e`` inside ``[A-Za-z0-9]`` under ``en_US.UTF-8``, or the check's C-locale pin cannot
    be told apart from its absence and the test skips rather than pass over nothing. glibc stages
    it; macOS cannot, because it orders every range by code point.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a non-ASCII letter passes the check where the locale would admit it.
    """
    collating = _environment(LC_ALL="en_US.UTF-8")
    staged = subprocess.run(  # noqa: S603
        [_bash(), "-c", "[[ $1 =~ ^[A-Za-z0-9]$ ]]", "_", "\u00e9"],
        capture_output=True,
        env=collating,
        timeout=30,
    )
    if staged.returncode != 0:
        pytest.skip("this platform keeps U+00E9 outside [A-Za-z0-9] under en_US.UTF-8")

    finished = subprocess.run(  # noqa: S603
        [_bash(), str(CHECK), f"{HELD}\u00e9"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=collating,
        timeout=30,
    )

    assert finished.returncode == 1, f"a non-ASCII letter passed:\n{finished.stdout}"
    assert finished.stdout.startswith("::error title=Malformed tag::"), finished.stdout


@pytest.mark.parametrize("arguments", [(), (HELD, HELD)], ids=["no-argument", "two-arguments"])
def test_the_check_refuses_a_call_that_does_not_pass_one_tag(arguments):
    """A caller that forgets the tag is refused, rather than told every value is fine.

    An empty tag is a legitimate input and passes, so a missing argument defaulting to empty would
    let a step that dropped its ``"$TAG"`` pass every dispatch unchecked.

    Args:
      arguments: What the caller passed instead of one tag.

    Returns:
      None.

    Raises:
      AssertionError: If the call passes, or fails for a reason other than its arguments.
    """
    finished = _run_check(*arguments)

    assert finished.returncode == 2, f"exited {finished.returncode}:\n{finished.stdout}"
    assert "takes exactly one argument" in finished.stdout, finished.stdout


@pytest.mark.parametrize("step", ENTRY_STEPS, ids=[workflow for workflow, _, _ in ENTRY_STEPS])
@pytest.mark.parametrize("tag", list(RESPELLED.values()), ids=list(RESPELLED))
def test_each_entry_step_refuses_a_malformed_tag_before_the_registry_sees_it(step, tag):
    """The first step to read a dispatch's tag refuses it before any ``aws`` call, and says so once.

    Each respelled row is found in the registry once the CLI has trimmed it, then handed on as
    typed; the command row, refused as unknown, would print a spoofed notice as a command of its
    own. Nothing may be written for a later step to read.

    Args:
      step: The workflow, job and step id under test.
      tag: A malformed input.

    Returns:
      None.

    Raises:
      AssertionError: If the step calls ``aws``, refuses for another reason, prints a second
        command, or writes an output.
    """
    run = _run_step(*step, tag)

    assert run.returncode != 0, f"{tag!r} was accepted:\n{run.stdout}"
    assert "::error title=Malformed tag::" in run.stdout, (
        f"{tag!r} was refused for another reason:\n{run.stdout}"
    )
    assert len(_commands(run.stdout)) == 1, f"{tag!r} printed:\n{run.stdout}"
    assert run.calls == [], f"{tag!r} reached aws as {run.calls}"
    assert run.outputs == {}, f"a refused dispatch still wrote {run.outputs}"


@pytest.mark.parametrize(
    ("tag", "refused", "printed", "looked_up"),
    [
        (
            HELD,
            False,
            f"::notice title=Rollback::pointing every function at dat-prod-lambda:{HELD}",
            [HELD],
        ),
        (
            UNKNOWN,
            True,
            f"::error title=Unknown tag::dat-prod-lambda:{UNKNOWN} is not in the registry.",
            [UNKNOWN],
        ),
        (
            "",
            False,
            f"::notice title=Deploy::pointing every function at dat-prod-lambda:{HEAD}",
            [],
        ),
    ],
    ids=["held", "unknown", "empty"],
)
def test_the_rollback_check_asks_the_registry_about_a_bare_tag_as_typed(
    tag, refused, printed, looked_up
):
    """A bare rollback tag reaches the registry verbatim; an empty one means this commit's image.

    The positive half of the refusal above: without it, a step that never called ``aws`` at all
    would pass that test for the wrong reason.

    Args:
      tag: The dispatch's ``image_tag`` input.
      refused: Whether the step must fail.
      printed: The workflow command the step must print.
      looked_up: The tags ``describe-images`` must be asked about, as sent.

    Returns:
      None.

    Raises:
      AssertionError: If the step passes or fails the wrong way, or asks the registry about
        anything else.
    """
    run = _run_step("deploy-lambdas.yml", "plan", "image", tag)

    assert (run.returncode != 0) == refused, f"{tag!r} exited {run.returncode}:\n{run.stdout}"
    assert printed in run.stdout, run.stdout
    assert [call[2] for call in run.calls if call[:2] == ["ecr", "describe-images"]] == looked_up
    assert len(_commands(run.stdout)) == 1, run.stdout


@pytest.mark.parametrize(
    ("tag", "outputs", "looked_up"),
    [
        (HELD, {"tag": HELD, "build": "skip"}, [HELD, HELD]),
        (UNKNOWN, {}, [UNKNOWN]),
        ("", {"tag": HEAD, "build": "run"}, [HEAD]),
    ],
    ids=["held", "unknown", "empty"],
)
def test_the_image_names_step_resolves_a_bare_tag_as_typed(tag, outputs, looked_up):
    """A bare tag the registry holds is reported and not rebuilt; one it lacks is refused by name.

    An empty input is this commit's sha, which is asked about only to decide whether to build.

    Args:
      tag: The dispatch's ``image_tag`` input.
      outputs: The ``tag`` and ``build`` answers the step must write beside the registry's names,
        or nothing for a refusal.
      looked_up: The tags ``describe-images`` must be asked about, as sent.

    Returns:
      None.

    Raises:
      AssertionError: If the step writes other answers, refuses the wrong input, or asks the
        registry about anything else.
    """
    run = _run_step("deploy-lambda-image.yml", "push", "names", tag)

    names = {"repo": REPOSITORY_URI, "name": "dat-prod-lambda"} if outputs else {}
    assert run.outputs == {**names, **outputs}, run.stdout
    assert (run.returncode != 0) == (not outputs), f"{tag!r} exited {run.returncode}:\n{run.stdout}"
    assert ("::error title=Unknown tag::" in run.stdout) == (not outputs), run.stdout
    assert [call[2] for call in run.calls if call[:2] == ["ecr", "describe-images"]] == looked_up
