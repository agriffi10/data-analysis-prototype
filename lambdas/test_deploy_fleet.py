"""`deploy-fleet.sh` is RUN here, beside a stub `point-lambda.sh`, not read.

The script decides which functions get an attempt, how many run at once, and what is recorded and
printed as each finishes — decisions a reading cannot check, and two of them fail silently: a
function dropped from the fan-out is never pointed while every other one reports success, and a
record or log held until the end is lost when the job is killed by its timeout. So the script runs
against a stub that logs each call and fails on demand, and the tests assert on what was CALLED
and RECORDED, not on the exit code alone.

What this cannot cover: the real waiters and Lambda's API under load. Those settle on a real
deploy, and `test_point_lambda.py` covers the per-function script itself.

Attributes:
  ROOT: The repository root.
  SCRIPT: The script under test.
  WORKFLOW: The deploy that runs it.
  STUB: A stand-in for `point-lambda.sh` that logs a start and an end line per call, sleeps
    ``FAKE_SECONDS`` (``FAKE_SLOW`` names sleep 30s instead), exits 255 — what an `aws ... wait`
    timeout propagates — for each name in ``FAKE_FAIL``, and SIGKILLs its worker for each name in
    ``FAKE_KILL``.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "deploy-fleet.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-lambdas.yml"

sys.path.insert(0, str(ROOT / "lambdas"))
import fleet

STUB = """\
#!/usr/bin/env bash
echo "start $1" >> "$CALLS"
case " ${FAKE_KILL:-} " in *" $1 "*) kill -KILL "$PPID"; exit 0 ;; esac
case " ${FAKE_SLOW:-} " in *" $1 "*) sleep 30 ;; esac
sleep "${FAKE_SECONDS:-0}"
echo "end $1" >> "$CALLS"
case " ${FAKE_FAIL:-} " in *" $1 "*) echo "::error::$1 broke"; exit 255 ;; esac
echo "pointed $1"
"""


@pytest.fixture
def staged(tmp_path):
    """A copy of the script beside the stub it resolves as `point-lambda.sh`.

    The script finds `point-lambda.sh` through its own directory, so the stub has to sit next to
    the copy under test rather than on PATH.

    Args:
      tmp_path: The pytest temporary directory.

    Returns:
      The directory holding the staged script.

    Raises:
      None.
    """
    staged_dir = tmp_path / "scripts"
    staged_dir.mkdir()
    (staged_dir / SCRIPT.name).write_text(SCRIPT.read_text(encoding="utf-8"))
    (staged_dir / "point-lambda.sh").write_text(STUB)
    return staged_dir


def _env(tmp_path, planned, *, concurrency=8, fail=(), kill=(), slow=(), seconds=0):
    """The environment one run of the staged script gets.

    ``RUNNER_TEMP`` is the test's own directory, so a run killed before its cleanup trap leaves its
    scratch files where pytest removes them rather than in the machine's shared temp directory.
    Not ``TMPDIR``: macOS `mktemp -d` was measured ignoring it.

    Args:
      tmp_path: The pytest temporary directory.
      planned: The plan's function names, or a raw string to hand over unparsed.
      concurrency: ``DEPLOY_CONCURRENCY``.
      fail: Names the stub fails.
      kill: Names whose worker the stub kills.
      slow: Names the stub holds for 30s.
      seconds: How long each stub call sleeps.

    Returns:
      The environment.

    Raises:
      None.
    """
    env = dict(os.environ)
    env.update(
        PLANNED=planned if isinstance(planned, str) else json.dumps(planned),
        DEPLOY_CONCURRENCY=str(concurrency),
        RUNNER_TEMP=str(tmp_path),
        FAKE_FAIL=" ".join(fail),
        FAKE_KILL=" ".join(kill),
        FAKE_SLOW=" ".join(slow),
        FAKE_SECONDS=str(seconds),
        CALLS=str(tmp_path / "calls.log"),
    )
    return env


def _run(staged, tmp_path, planned, **settings):
    """Runs the staged script over a plan and returns what it did.

    Args:
      staged: The directory holding the staged script and stub.
      tmp_path: The pytest temporary directory.
      planned: The plan's function names, or a raw string to hand over unparsed.
      **settings: Passed to ``_env``.

    Returns:
      A tuple of (completed process, the stub's call lines, the recorded names).

    Raises:
      None.
    """
    calls = tmp_path / "calls.log"
    record = tmp_path / "deployed.txt"
    result = subprocess.run(  # noqa: S603
        ["bash", str(staged / SCRIPT.name), str(record)],  # noqa: S607
        capture_output=True, text=True, env=_env(tmp_path, planned, **settings), timeout=120,
    )
    lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    recorded = record.read_text(encoding="utf-8").split() if record.exists() else []
    return result, lines, recorded


def _started(lines):
    """The names the stub was started for, one entry per call.

    Args:
      lines: The stub's call lines.

    Returns:
      The started names, in start order.

    Raises:
      None.
    """
    return [line.split(" ", 1)[1] for line in lines if line.startswith("start ")]


def test_every_planned_function_is_pointed_exactly_once_and_recorded(tmp_path, staged):
    """The whole fleet gets one attempt each, and the record is the fleet.

    Run over the REAL fleet, because the guard this replaces held the shards' union equal to it:
    a fan-out that drops a function leaves every other one reporting success.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a function is skipped, attempted twice, or missing from the record.
    """
    names = fleet.function_names(ROOT)
    assert names, "the fleet derived empty, so every assertion below would be vacuous"

    result, lines, recorded = _run(staged, tmp_path, names)

    assert result.returncode == 0, result.stdout + result.stderr
    started = _started(lines)
    assert sorted(started) == sorted(names), (
        f"dropped {sorted(set(names) - set(started))}, unexpected {sorted(set(started) - set(names))}"
    )
    assert len(started) == len(names), "a function was attempted more than once"
    assert sorted(recorded) == sorted(names)
    assert f"All {len(names)} functions deployed." in result.stdout


def test_functions_run_side_by_side_but_never_more_than_the_cap(tmp_path, staged):
    """Several functions are in flight at once, and never more than ``DEPLOY_CONCURRENCY``.

    The parallelism is the whole cost saving, so a fan-out that quietly ran one at a time would
    pass every other test here while billing the old wall clock.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When nothing overlaps, or more than the cap does.
    """
    names = [f"fn-{index}" for index in range(12)]

    result, lines, _ = _run(staged, tmp_path, names, concurrency=3, seconds=0.3)

    assert result.returncode == 0, result.stdout + result.stderr
    in_flight = peak = 0
    for line in lines:
        in_flight += 1 if line.startswith("start ") else -1
        peak = max(peak, in_flight)
    assert peak > 1, "every function ran alone, so the deploy is serial again"
    assert peak <= 3, f"{peak} functions were in flight with a cap of 3"


def test_one_failure_fails_the_run_and_names_only_that_one(tmp_path, staged):
    """A broken function fails the run by name and holds back nothing else.

    It fails with 255, which is what an `aws ... wait` timeout propagates and what makes `xargs`
    stop launching altogether if a worker ever passes it through.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When the failure stops other functions, goes unnamed, or is recorded.
    """
    names = [f"fn-{index}" for index in range(10)]

    result, lines, recorded = _run(staged, tmp_path, names, concurrency=2, fail=("fn-0",))

    assert result.returncode == 1
    assert sorted(_started(lines)) == sorted(names), "a failure stopped unrelated functions"
    assert sorted(recorded) == sorted(set(names) - {"fn-0"})
    assert "1 function(s) failed to deploy: fn-0" in result.stdout
    assert "fn-0 broke" in result.stdout, "the failed function's own log was not printed"


def test_every_function_gets_its_attempt_however_many_fail(tmp_path, staged):
    """A run where everything fails still attempts everything, and names every failure.

    There is deliberately no early stop — the job's timeout is the cost bound — so a stop that crept
    back in would leave functions unattempted on a run where most fail fast and would have retried
    for free.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a failure stops any later function from being attempted.
    """
    names = [f"fn-{index}" for index in range(12)]

    result, lines, recorded = _run(staged, tmp_path, names, concurrency=2, fail=tuple(names))

    assert result.returncode == 1
    assert sorted(_started(lines)) == sorted(names), "failures stopped later functions"
    assert recorded == []
    assert f"12 function(s) failed to deploy: {' '.join(names)}" in result.stdout


def test_a_finished_function_is_printed_and_recorded_before_the_run_ends(tmp_path, staged):
    """A function's log and its record land when IT finishes, not when the run does.

    A run killed by its timeout prints and records nothing it was holding back: a log printed only
    at the end leaves the reader no reason for any failure, and a record written only at the end
    reports every function that landed as un-pointed. That is the one run where both matter most.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a finished function's log or record is held back while another runs.
    """
    record = tmp_path / "deployed.txt"
    process = subprocess.Popen(  # noqa: S603
        ["bash", str(staged / SCRIPT.name), str(record)],  # noqa: S607
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        env=_env(tmp_path, ["a", "b", "c"], concurrency=3, fail=("a",), slow=("b",)),
    )
    seen = b""
    deadline = time.monotonic() + 15
    try:
        os.set_blocking(process.stdout.fileno(), False)
        while not (b"a broke" in seen and b"pointed c" in seen) and time.monotonic() < deadline:
            chunk = process.stdout.read()
            seen += chunk or b""
            time.sleep(0.1)
        assert b"a broke" in seen and b"pointed c" in seen, (
            "a finished function's log was held back while another function was still running: "
            f"{seen.decode()!r}"
        )
        assert process.poll() is None
        assert record.read_text(encoding="utf-8").split() == ["c"], (
            "the landed function was not recorded while another was still running"
        )
    finally:
        os.killpg(process.pid, 9)
        process.wait(timeout=10)


def test_a_worker_killed_mid_run_leaves_its_functions_named(tmp_path, staged):
    """A worker that dies without an outcome fails the run and names what has none.

    `xargs` gives up when a worker is killed by a signal, so the functions it never started have no
    outcome either; the reconciliation would go red over them anyway, but only this says why.

    Args:
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When the run passes, or the functions without an outcome go unnamed.
    """
    result, _, recorded = _run(staged, tmp_path, ["a", "b", "c"], concurrency=1, kill=("b",))

    assert result.returncode == 1
    assert "no outcome was recorded for 2 function(s)" in result.stdout
    assert result.stdout.rstrip().endswith(": b c"), result.stdout
    assert recorded == ["a"]


@pytest.mark.parametrize("value", ["0", "eight", "-1", "8 "])
def test_a_concurrency_that_is_not_a_positive_whole_number_is_refused(value, tmp_path, staged):
    """A concurrency that is not a whole number of at least 1 starts nothing.

    GNU `xargs -P 0` runs the whole fleet at once, and a non-number fails inside `xargs` only after
    the plan has been accepted.

    Args:
      value: The malformed concurrency.
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When anything starts, or the refusal says something else.
    """
    result, lines, _ = _run(staged, tmp_path, ["a", "b"], concurrency=value)

    assert result.returncode == 1
    assert "::error::DEPLOY_CONCURRENCY must be a whole number of at least 1" in result.stdout
    assert lines == []


@pytest.mark.parametrize(
    ("planned", "reason"),
    [
        ([], "named no functions"),
        (["api", "api"], "more than once"),
        (["api", "bad name"], "outside [A-Za-z0-9_-]"),
        (["../escape"], "outside [A-Za-z0-9_-]"),
    ],
)
def test_a_plan_that_cannot_be_deployed_is_refused_before_anything_starts(
    planned, reason, tmp_path, staged,
):
    """An empty, duplicated or unnameable plan starts nothing and says why.

    Args:
      planned: The plan handed over.
      reason: The text the refusal must carry.
      tmp_path: The pytest temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When anything starts, or the refusal gives another reason.
    """
    result, lines, _ = _run(staged, tmp_path, planned)

    assert result.returncode == 1
    assert reason in result.stdout
    assert lines == [], "a refused plan still started functions"


def test_the_workflow_uploads_the_file_the_script_records_into() -> None:
    """The deploy job runs this script over the plan, and uploads the record it writes.

    The reconciliation reads only the uploaded record, so a step writing one file and an upload
    naming another would report the whole fleet un-pointed after a deploy that worked.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the job stops running the script, or the two file names part.
    """
    deploy = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["deploy"]
    runs = [step for step in deploy["steps"] if SCRIPT.name in step.get("run", "")]
    assert len(runs) == 1, f"expected one step running {SCRIPT.name}, found {len(runs)}"
    record = runs[0]["run"].split(SCRIPT.name, 1)[1].split()[0]

    uploads = [step for step in deploy["steps"] if "upload-artifact" in step.get("uses", "")]
    assert len(uploads) == 1
    assert uploads[0]["with"]["path"] == record
    assert uploads[0].get("if") == "always()", "a failed deploy must still hand over its record"
    assert "needs.plan.outputs.functions" in deploy["env"]["PLANNED"]
