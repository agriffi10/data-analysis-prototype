"""The cold-start probe, driven rather than read.

A gate owes a fixture corpus asserting the failure REASON, including cases that assert silence —
half a gate's regressions are false positives. This one is a shell script that decides whether a
deploy is green, so it gets the same treatment `point-lambda.sh` has: a stubbed `aws` on `PATH` and
one case per branch, each asserting what the script SAID and not merely that it exited non-zero.
The neighbouring branch returns the same code, which is what makes an exit-code assertion vacuous.

**Every fixture states where its shape came from, and they come from ONE world.** An earlier
version paired a production response envelope (`FunctionError: Unhandled`) with a log tail measured
under the runtime interface emulator — a combination neither world produces, and the inconsistency
is what hid a defect for two rounds. The emulator answers 502 with no `X-Amz-Function-Error` at all;
production answers 200 with one. So the init-failure logs below are **AWS's documented production
output** for a `Runtime.ExitError`, and the healthy ones are ordinary invocation logs.

Three designs were tried and each is pinned by a case here, because a regression to any of them is
the likeliest way this gate goes quiet: `START RequestId` (written before init, and truncated away
by the 4 KB tail), an `errorType` namespace (an import-time `RuntimeError` has no prefix), and a
bare `REPORT RequestId` (production writes one on an init failure too).

Attributes:
  SCRIPT: The gate under test.
  TABLE: A two-function probe table, so a per-function failure is distinguishable from a total one.
"""

import json
import os
import pathlib
import stat
import subprocess
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "probe-cold-start.sh"
TABLE = {"probe": ["alpha", "beta"], "exempt": {}}


def _stub(tmp_path, meta, payload, *, exit_code=0, stderr=""):
    """Builds a bin/ holding a fake `aws lambda invoke`.

    The stub writes the payload to the outfile the real CLI writes to — the LAST positional
    argument — because the script reads `errorType` from that file and not from stdout. A stub that
    only printed metadata would leave every payload branch unreachable.

    Args:
      tmp_path: The pytest temporary directory.
      meta: The JSON the CLI prints on stdout (LogResult, FunctionError).
      payload: The JSON written to the response file.
      exit_code: What the fake CLI exits with.
      stderr: What it writes to stderr.

    Returns:
      The bin directory.

    Raises:
      None.
    """
    binary = tmp_path / "bin"
    binary.mkdir(parents=True, exist_ok=True)
    script = binary / "aws"
    script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        printf '%s' {json.dumps(stderr)} >&2
        [ {exit_code} -eq 0 ] || exit {exit_code}
        for arg in "$@"; do OUTFILE="$arg"; done
        printf '%s' {json.dumps(json.dumps(payload))} > "$OUTFILE"
        printf '%s' {json.dumps(json.dumps(meta))}
        """)
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return binary


def _tail(text):
    """Base64-encodes a log tail the way the CLI returns it.

    Args:
      text: The log text.

    Returns:
      The base64 string.

    Raises:
      None.
    """
    import base64

    return base64.b64encode(text.encode()).decode()


def _run(tmp_path, binary, table=None):
    """Runs the probe with the stub first on PATH.

    Args:
      tmp_path: The pytest temporary directory.
      binary: The stub bin directory.
      table: The probe table, defaulting to two functions.

    Returns:
      The completed process.

    Raises:
      None.
    """
    path = tmp_path / "probes.json"
    path.write_text(json.dumps(TABLE if table is None else table))
    env = dict(os.environ)
    env.update(
        PATH=f"{binary}:{env['PATH']}",
        PROJECT_NAME="dat",
        ENVIRONMENT="prod",
        PROBE_TABLE=str(path),
    )
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],  # noqa: S607
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_an_exception_raised_at_import_is_caught_though_its_errorType_looks_ordinary(
    tmp_path,
) -> None:
    """THE case both earlier designs passed, and the fleet's most likely init failure.

    A module that raises at import — which is what `observability.init` running at module scope
    invites — reports `RuntimeError`, indistinguishable from a handler exception by name. The log
    below is AWS's documented production output for that class: `START`, `END` **and** `REPORT` are
    all present, so all three earlier designs pass it. What catches it is `Status: error`, a field
    Lambda writes only when a phase failed.
    """
    binary = _stub(
        tmp_path,
        {"FunctionError": "Unhandled",
         "LogResult": _tail(
             "START RequestId: 5b866fb1 Version: $LATEST\n"
             "END RequestId: 5b866fb1\n"
             "REPORT RequestId: 5b866fb1\tDuration: 133.61 ms\tBilled Duration: 214 ms\t"
             "Init Duration: 80.00 ms\tStatus: error\tError Type: Runtime.ExitError\n")},
        {"errorType": "RuntimeError", "errorMessage": "init blew up", "requestId": ""},
    )

    result = _run(tmp_path, binary)

    assert result.returncode == 1, result.stdout
    assert "reported a failed phase" in result.stdout
    assert "RuntimeError" in result.stdout


def test_a_handler_error_is_a_pass_and_a_runtime_error_is_not(tmp_path) -> None:
    """The two that ARE separable by name, kept because the runtime saying so directly is the
    clearer failure and should not have to wait for the log."""
    handler_error = _stub(
        tmp_path / "ok",
        {"FunctionError": "Unhandled",
         "LogResult": _tail("START RequestId: abc\n[ERROR] KeyError\nEND RequestId: abc\n"
                            "REPORT RequestId: abc\tDuration: 3 ms\n")},
        {"errorType": "KeyError", "errorMessage": "Records"},
    )
    result = _run(tmp_path / "ok", handler_error)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "handler ran and refused the payload (KeyError)" in result.stdout

    init_error = _stub(
        tmp_path / "bad",
        {"FunctionError": "Unhandled",
         "LogResult": _tail("START RequestId: abc\n[ERROR] Runtime.ImportModuleError\n")},
        {"errorType": "Runtime.ImportModuleError",
         "errorMessage": "Unable to import module 'x': No module named 'y'"},
    )
    result = _run(tmp_path / "bad", init_error)
    assert result.returncode == 1
    assert "did not start: Runtime.ImportModuleError" in result.stdout


def test_a_clean_return_passes_and_says_so(tmp_path) -> None:
    """No FunctionError at all — the scheduled functions' ordinary answer."""
    binary = _stub(tmp_path, {"LogResult": _tail("START RequestId: a\nEND RequestId: a\nREPORT RequestId: a\n")}, {"ok": True})

    result = _run(tmp_path, binary)

    assert result.returncode == 0, result.stdout
    assert "returned without error" in result.stdout
    # The COUNT, not just the sentence. A gate that prints a number nothing reads is a number that
    # can go to zero unnoticed — measured: blanking the counter left all twelve tests green.
    assert "All 2 probed functions reached their handler (2 confirmed)." in result.stdout


def test_a_chatty_healthy_function_is_not_failed_by_a_truncated_log(tmp_path) -> None:
    """The false-positive direction, and why the signal had to move to the end of the log.

    `--log-type Tail` returns the LAST 4 KB. `log-sweep` is probed and emits per-wave events, so
    its preamble — and with it `START RequestId` — is gone by the time the tail is taken. `REPORT`
    is the final line and survives, which is the whole reason it is the signal.
    """
    binary = _stub(
        tmp_path,
        {"FunctionError": "Unhandled",
         "LogResult": _tail("…truncated…\n[ERROR] ValueError: bad envelope\n"
                            "END RequestId: a\nREPORT RequestId: a\tDuration: 900 ms\n")},
        {"errorType": "ValueError", "errorMessage": "bad envelope"},
    )

    result = _run(tmp_path, binary)

    assert result.returncode == 0, result.stdout
    assert "handler ran and refused the payload (ValueError)" in result.stdout


def test_a_traceback_quoting_the_signal_does_not_pass_for_it(tmp_path) -> None:
    """Measured on a real container: an import error whose message quoted a log line put the
    literal `REPORT RequestId` inside the traceback, and an unanchored grep read it as the
    runtime's own line. The anchor is what stops a function's own text answering for it."""
    binary = _stub(
        tmp_path,
        {"FunctionError": "Unhandled",
         "LogResult": _tail('START RequestId: a\nTraceback:\n  line: "REPORT RequestId: a"\n'
                            "RuntimeError: boom\n")},
        {"errorType": "RuntimeError", "errorMessage": "boom"},
    )

    result = _run(tmp_path, binary)

    assert result.returncode == 1, result.stdout
    assert "never completed through the runtime" in result.stdout


def test_an_error_with_no_type_and_no_REPORT_is_refused(tmp_path) -> None:
    """A payload that says nothing and a log that never completed. Nothing can conclude the
    handler ran, so it must not be read as though it did."""
    binary = _stub(tmp_path, {"FunctionError": "Unhandled", "LogResult": _tail("boom")}, {})

    result = _run(tmp_path, binary)

    assert result.returncode == 1
    assert "never completed through the runtime" in result.stdout


def test_a_failed_invocation_is_a_failure_and_names_the_reason(tmp_path) -> None:
    """`AccessDenied` is what a probe with no grant looks like, and it must not read as clean."""
    binary = _stub(tmp_path, {}, {}, exit_code=255, stderr="AccessDeniedException")

    result = _run(tmp_path, binary)

    assert result.returncode == 1
    assert "could not be invoked" in result.stdout
    assert "AccessDeniedException" in result.stdout


def test_a_missing_log_does_not_stop_a_clean_return_from_passing(tmp_path) -> None:
    """The silence case. A function that returned fine but whose log tail is absent has still
    STARTED — failing it would be a false positive, and half a gate's regressions are those."""
    binary = _stub(tmp_path, {}, {"ok": True})

    result = _run(tmp_path, binary)

    assert result.returncode == 0, result.stdout


def test_an_empty_population_is_refused_rather_than_reported_clean(tmp_path) -> None:
    """"Did not run" is never "clean" — a table that parsed to nothing would loop zero times."""
    binary = _stub(tmp_path, {}, {"ok": True})

    result = _run(tmp_path, binary, table={"probe": [], "exempt": {}})

    assert result.returncode == 1
    assert "Refusing to report a pass" in result.stdout


def test_one_failure_among_several_fails_the_job_and_names_only_that_one(tmp_path) -> None:
    """A shard-wide failure and a single broken function must not look alike."""
    binary = tmp_path / "bin"
    binary.mkdir()
    script = binary / "aws"
    script.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env bash
        for arg in "$@"; do OUTFILE="$arg"; done
        case "$*" in
          *beta*) printf '%s' '{{"errorType": "Runtime.HandlerNotFound"}}' > "$OUTFILE"
                  printf '%s' '{{"FunctionError": "Unhandled", "LogResult": "{_tail("x")}"}}' ;;
          *)      printf '%s' '{{"ok": true}}' > "$OUTFILE"
                  printf '%s' '{{"LogResult": "{_tail("x")}"}}' ;;
        esac
        """)
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    result = _run(tmp_path, binary)

    assert result.returncode == 1
    assert "1 of 2 probed functions did not start" in result.stdout
    assert "beta (Runtime.HandlerNotFound)" in result.stdout
    assert "alpha" not in result.stdout.split("did not start:")[1]


@pytest.mark.parametrize(
    "mutation, why",
    [
        ('[[ "$ERROR_TYPE" == Runtime.* ]]', "the runtime-namespace check"),
        ("grep -qE '^REPORT RequestId'", "the ANCHORED completed-invocation signal"),
        ("grep -q 'Status: error'", "the failed-phase signal"),
        ("        --log-type Tail \\\n", "the flag the whole signal depends on, in the CALL and not a comment"),
        ('[ "${#NAMES[@]}" -eq 0 ]', "the empty-population refusal"),
    ],
)
def test_the_script_still_carries_the_checks_these_tests_pin(mutation: str, why: str) -> None:
    """A cheap structural pin, because the cases above are the only thing standing between a
    silent deploy and a fleet that cannot start — and a mutation that deletes a branch would
    otherwise only show up as one of them going quiet."""
    assert mutation in SCRIPT.read_text(encoding="utf-8"), f"{why} is gone from the script"
