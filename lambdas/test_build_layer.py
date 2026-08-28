"""The layer builder's ONE contract: one tab-separated record on stdout, per layer.

Runs the real script against a fake ``aws``, because the bug it exists for is not visible in the
script's text: ``aws --output text`` auto-paginates and applies ``--query`` to EACH PAGE, so a
single-value query returns one value per page. The full account is in
``lambdas/info/deployment.md``.

Attributes:
  ROOT: The repository root.
  SCRIPT: The builder under test.
  _PAGE_SIZE: What the CLI pages ListLayerVersions at, and therefore what the fake reproduces.
"""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "build-layer.sh"

_PAGE_SIZE = 50


def _fake_aws(tmp_path: pathlib.Path, versions: int) -> pathlib.Path:
    """Writes an ``aws`` stand-in that answers a listing the way the paginating CLI does.

    It applies the caller's ``--query`` PER PAGE, which is the CLI's documented behaviour with
    ``--output text`` and the whole mechanism this suite exists for. The fake understands the
    two queries this script has used, so the test asserts against the mechanism rather than
    against a fixture shaped to pass.

    Args:
      tmp_path: The directory the stand-in is written into; the caller puts it first on PATH.
      versions: How many layer versions the fake reports.

    Returns:
      The directory holding the stand-in.

    Raises:
      None.
    """
    binaries = tmp_path / "bin"
    binaries.mkdir()
    pages = [
        list(range(start + 1, min(start + _PAGE_SIZE, versions) + 1))
        for start in range(0, versions, _PAGE_SIZE)
    ]
    arn = "arn:aws:lambda:us-east-1:1:layer:dat-prod-probe"
    per_row = "\n".join(
        "\n".join(f"{version}\t{arn}:{version}" for version in page) for page in pages
    )
    single_value = "\n".join(f"{arn}:{max(page)}" for page in pages)
    script = binaries / "aws"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        "  *list-layer-versions*max_by*)\n"
        f"    cat <<'ROWS'\n{single_value}\nROWS\n"
        "    ;;\n"
        "  *list-layer-versions*)\n"
        f"    cat <<'ROWS'\n{per_row}\nROWS\n"
        "    ;;\n"
        "  *) echo 'unexpected aws call' >&2; exit 1 ;;\n"
        "esac\n"
    )
    script.chmod(0o755)
    return binaries


def _run(tmp_path: pathlib.Path, versions: int) -> subprocess.CompletedProcess:
    """Builds a probe layer with publishing off, so the reuse path is the one exercised.

    Args:
      tmp_path: The working directory.
      versions: How many layer versions the fake ``aws`` reports.

    Returns:
      The completed process, with stdout and stderr captured.

    Raises:
      None.
    """
    package = tmp_path / "probe_pkg"
    package.mkdir()
    (package / "__init__.py").write_text('"""A package with something in it."""\n')
    table = tmp_path / "layers.json"
    table.write_text(
        json.dumps(
            [
                {
                    "flag": "probe",
                    "layerName": "probe",
                    "package": str(package),
                    "description": "probe layer",
                }
            ]
        )
    )
    env = {
        **os.environ,
        "PATH": f"{_fake_aws(tmp_path, versions)}:{os.environ['PATH']}",
        "LAYERS_JSON_FILE": str(table),
        "PROJECT_NAME": "dat",
        "ENVIRONMENT": "prod",
    }
    return subprocess.run(  # noqa: S603
        [shutil.which("bash"), str(SCRIPT), "probe", "false"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(autouse=True)
def _needs_a_shell():
    """Skips where the tools the script itself needs are absent, rather than failing for a
    reason that is about the machine and not the code."""
    for tool in ("bash", "jq", "awk", "du"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not available")


@pytest.mark.parametrize("versions", [1, _PAGE_SIZE * 2 + 27])
def test_the_builder_emits_one_record_naming_the_highest_version(tmp_path, versions) -> None:
    """The regression, and why the parametrisation crosses the page boundary.

    At one page the old single-value query was right; at three it returned three ARNs, the
    record became three records keyed by an ARN, and the job's own map guard failed the deploy
    after every layer had already been built. The version is chosen by MAX because
    ListLayerVersions documents no ordering — picking the first row would re-point every
    function attaching this layer at an arbitrary older version.

    Args:
      tmp_path: The working directory.
      versions: How many layer versions the fake reports.

    Returns:
      None.

    Raises:
      AssertionError: If more than one record is emitted, or it names the wrong version.
    """
    result = _run(tmp_path, versions)

    assert result.returncode == 0, result.stderr
    assert len(result.stdout.strip().split("\n")) == 1, (
        f"the builder emitted {result.stdout!r} — the caller reads each line as one layer"
    )
    flag, arn, _ = result.stdout.strip().split("\t")
    assert flag == "probe"
    assert arn.endswith(f":{versions}")


def test_a_layer_never_published_reports_it_and_emits_no_record(tmp_path) -> None:
    """An empty listing is not a failure — it is a brand-new layer on a push that did not appear
    to change it — but it must not become an empty ARN in the map either, because the deploy
    would then attach nothing and every function using that layer would die at cold start.

    Args:
      tmp_path: The working directory.

    Returns:
      None.

    Raises:
      AssertionError: If the builder stays quiet or emits a record.
    """
    result = _run(tmp_path, 0)

    assert "publishing despite no detected change" in result.stderr
    assert result.returncode != 0 or result.stdout.strip() == ""
