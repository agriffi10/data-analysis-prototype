"""`point-lambda.sh` is RUN here, against a stub `aws`, not read.

The script decides which of two incompatible deploy paths a function takes, from a field it reads
at runtime. Reading it cannot tell you whether it dispatches correctly, and getting it wrong is not
a subtle failure: `update-function-code --s3-bucket` against an Image function is an
`InvalidParameterValueException`, and `--image-uri` against a Zip one is the same in reverse. So
the script is executed with a fake `aws` on PATH that records every call.

What this cannot cover, said plainly: the real API's asynchrony, and the waiters. Those settle on a
real deploy. What it does cover is the branch, the read-back, and the refusals — the parts that are
decisions rather than calls.

Attributes:
  SCRIPT: The script under test.
  DEPLOY_LAMBDA: The zip-path script it execs, stubbed here so the branch is observable.
"""

import os
import pathlib
import subprocess
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "point-lambda.sh"

REPOSITORY = "123456789012.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda"


def _harness(tmp_path, package_type, *, landed=None, status="Successful",
             image_present=True, function_present=True):
    """Builds a bin/ holding a fake `aws` and a fake `deploy-lambda.sh`.

    The fake `aws` answers only the queries this script makes and logs every invocation, so a
    test can assert on what was CALLED rather than on the exit code alone — the neighbouring path
    usually returns the same code, which is what makes an exit-code assertion vacuous.

    Args:
      tmp_path: The pytest temporary directory.
      package_type: What `get-function` should report.
      landed: What `Code.ImageUri` reads back as, defaulting to the tag that was asked for.
      status: What `LastUpdateStatus` reports.
      image_present: Whether `describe-images` finds the tag.
      function_present: Whether `get-function` finds the function.

    Returns:
      A tuple of (bin directory, call-log path).

    Raises:
      None.
    """
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "calls.log"
    landed = REPOSITORY + ":" + "abc123" if landed is None else landed

    (binary / "aws").write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        echo "$*" >> {log}
        case "$*" in
          *"get-function --function-name"*"--query Configuration.PackageType"*)
            [ "{function_present}" = "True" ] || exit 254
            echo "{package_type}" ;;
          *"get-function --function-name"*"--query Code.ImageUri"*)
            echo "{landed}" ;;
          *"get-function --function-name"*)
            [ "{function_present}" = "True" ] || exit 254 ;;
          *"describe-repositories"*)
            echo "{REPOSITORY}" ;;
          *"describe-images"*)
            [ "{image_present}" = "True" ] || exit 254 ;;
          *"wait function-updated-v2"*)
            # The REAL waiter has a terminal failure state on LastUpdateStatus == Failed and
            # exits non-zero. A stub that always succeeds makes the script's failure branch
            # unreachable and its test vacuous — which is exactly what the first version did.
            [ "{status}" = "Successful" ] || exit 255 ;;
          # ORDER MATTERS: "LastUpdateStatus" is a prefix of "LastUpdateStatusReason", so the
          # broader pattern must come second or it swallows the narrower one — which it did, and
          # the script's error line reported the status where the reason belongs.
          *"get-function-configuration"*"LastUpdateStatusReason"*)
            echo "a reason" ;;
          *"get-function-configuration"*"LastUpdateStatus"*)
            echo "{status}" ;;
          *) : ;;
        esac
        """))
    (binary / "aws").chmod(0o755)

    (binary / "deploy-lambda.sh").write_text(
        f'#!/usr/bin/env bash\necho "DEPLOY_LAMBDA_SH_RAN $1" >> {log}\n'
    )
    (binary / "deploy-lambda.sh").chmod(0o755)

    # WITHOUT THIS the two longest refusal paths are unreachable: both poll 30 times at 10s, which
    # no sane test timeout survives. `_harness` advertised `image_present` and `function_present`
    # from the start and neither was usable until the sleep was stubbed out.
    (binary / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (binary / "sleep").chmod(0o755)
    return binary, log


def _run(binary, script_dir, timeout=30):
    """Runs the script with the stub bin/ first on PATH.

    Args:
      binary: The stub bin directory.
      script_dir: The directory holding the copy of point-lambda.sh under test.
      timeout: Seconds before the run is abandoned.

    Returns:
      The completed process.

    Raises:
      None.
    """
    env = dict(os.environ)
    env.update(
        PATH=f"{binary}:{env['PATH']}",
        PROJECT_NAME="dat",
        ENVIRONMENT="prod",
        GITHUB_SHA="abc123",
    )
    # Running the script IS the test, and `bash` resolves from the STUBBED PATH deliberately
    # — that is what makes the fake `aws` reachable to it.
    return subprocess.run(  # noqa: S603
        ["bash", str(script_dir / "point-lambda.sh"), "archive-copy-objects"],  # noqa: S607
        capture_output=True, text=True, env=env, timeout=timeout,
    )


@pytest.fixture
def staged(tmp_path):
    """A copy of the script beside the stub `deploy-lambda.sh` it execs.

    The script resolves its sibling with `dirname $0`, so the stub has to sit next to the copy
    under test rather than merely on PATH.

    Args:
      tmp_path: The pytest temporary directory.

    Returns:
      The directory holding the staged script.

    Raises:
      None.
    """
    staged_dir = tmp_path / "scripts"
    staged_dir.mkdir()
    (staged_dir / "point-lambda.sh").write_text(SCRIPT.read_text(encoding="utf-8"))
    return staged_dir


def test_a_zip_function_goes_through_deploy_lambda_sh(tmp_path, staged):
    """The zip branch is a dispatch, not a reimplementation.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a Zip function is not handed to the existing script.
    """
    binary, log = _harness(tmp_path, "Zip")
    (staged / "deploy-lambda.sh").write_text(
        f'#!/usr/bin/env bash\necho "DEPLOY_LAMBDA_SH_RAN $1" >> {log}\n'
    )
    (staged / "deploy-lambda.sh").chmod(0o755)

    result = _run(binary, staged)
    calls = log.read_text()

    assert result.returncode == 0, result.stderr
    assert "DEPLOY_LAMBDA_SH_RAN archive-copy-objects" in calls
    assert "update-function-code" not in calls, (
        "the zip branch must not point at an image; --image-uri against a Zip function is an "
        "InvalidParameterValueException"
    )


def test_an_image_function_is_pointed_at_this_commit_s_image(tmp_path, staged):
    """The image branch asks for the tag, waits, and reads the effect back.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When the update is not made, or not verified.
    """
    binary, log = _harness(tmp_path, "Image")
    result = _run(binary, staged)
    calls = log.read_text()

    assert result.returncode == 0, result.stderr + calls
    assert f"update-function-code --function-name dat-prod-archive-copy-objects --image-uri {REPOSITORY}:abc123" in calls
    assert "wait function-updated-v2" in calls, "a container update is asynchronous"
    # The OTHER waiter, pinned separately: a just-created function sits in Pending and
    # update-function-code against it is a ResourceConflictException (SPEC-088). Deleting this
    # wait passed every other assertion in this file.
    assert "wait function-active-v2" in calls, (
        "the script must wait for the function to be Active before updating it; the cutover is "
        "the run most likely to catch one mid-create"
    )
    assert "--query Code.ImageUri" in calls, (
        "the script must read the effect back; the API call returning is not the deploy landing"
    )
    assert "DEPLOY_LAMBDA_SH_RAN" not in calls


def test_an_update_that_finishes_as_failed_fails_the_function(tmp_path, staged):
    """The waiter is not the whole check — LastUpdateStatus is read and named.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a failed update reports success.
    """
    binary, log = _harness(tmp_path, "Image", status="Failed")
    result = _run(binary, staged)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    # The REASON, not just the exit code. The waiter exits non-zero on a terminal failure, so a
    # script that let `set -e` abort on it would fail with botocore's generic waiter message and
    # never reach the read that names what AWS actually said.
    assert "finished its update as Failed" in output, output
    assert "a reason" in output, output
    assert "LastUpdateStatusReason" in log.read_text()


def test_an_image_that_did_not_land_is_refused(tmp_path, staged):
    """Reading back a DIFFERENT image than the one asked for is a failure, not a shrug.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When a mismatch passes.
    """
    binary, _ = _harness(tmp_path, "Image", landed=f"{REPOSITORY}:an-older-sha")
    result = _run(binary, staged)

    assert result.returncode != 0
    assert "an-older-sha" in result.stdout + result.stderr


def test_the_read_back_uses_the_tag_not_the_digest():
    """`Code.ResolvedImageUri` is a digest and never equals the tag that was requested.

    A read-back against it would fail on every function, which is a failure that looks like a
    broken deploy rather than a broken assertion — so the script's query is pinned here.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the script reads the resolved digest.
    """
    # COMMENTS STRIPPED FIRST. The script explains at length why ResolvedImageUri is the wrong
    # field, and the first version of this assertion read that explanation and failed — a guard
    # reporting the file does the thing the file says it must not do.
    code = "\n".join(
        line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "Code.ImageUri" in code, "the script never reads the image back"
    assert "ResolvedImageUri" not in code, (
        "the read-back uses Code.ResolvedImageUri, which is a digest and never equals the tag "
        "that was requested — it would fail on every function"
    )


def test_an_unknown_package_type_is_refused_rather_than_guessed(tmp_path, staged):
    """Neither of the two known values means the script cannot know which call is correct.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When an unknown packaging is guessed at.
    """
    binary, log = _harness(tmp_path, "Something")
    result = _run(binary, staged)

    assert result.returncode != 0
    assert "neither Zip nor Image" in result.stdout + result.stderr
    assert "update-function-code" not in log.read_text()


def test_a_function_that_never_appears_is_refused_by_name(tmp_path, staged):
    """The race this script exists to survive, at its limit.

    Deploy Infrastructure and Deploy Lambdas fire on the same push, so the function may not exist
    yet. What must not happen is an update against a function that is not there.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal is silent or an update is attempted anyway.
    """
    binary, log = _harness(tmp_path, "Image", function_present=False)
    result = _run(binary, staged)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "not ready after" in output, output
    assert "Deploy Infrastructure" in output, "the refusal must name what to run"
    assert "update-function-code" not in log.read_text()


def test_an_image_tag_that_never_appears_is_refused_naming_the_image_workflow(tmp_path, staged):
    """Pointing at a tag the registry does not hold fails with a message about the FUNCTION.

    So the script waits for the tag itself and refuses with a message about the IMAGE, naming the
    workflow that produces it — the image build fires on the same push and can lose the race.

    Args:
      tmp_path: Temporary directory.
      staged: The staged script directory.

    Returns:
      None.

    Raises:
      AssertionError: When the refusal blames the wrong thing, or an update is attempted.
    """
    binary, log = _harness(tmp_path, "Image", image_present=False)
    result = _run(binary, staged)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "not in the registry" in output, output
    assert "Deploy Lambda image" in output, "the refusal must name the workflow to look at"
    assert "update-function-code" not in log.read_text()
