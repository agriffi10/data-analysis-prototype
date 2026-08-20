"""The layer builder's ONE contract: one tab-separated record on stdout, per layer.

The caller collects those lines into the map every function's deploy reads, so a value carrying a
newline does not fail where it is produced — it silently becomes extra entries keyed by whatever the
stray line held, and the job fails at the end with a map that counts wrong.

**This suite runs the real script against a FAKE `aws`**, because the bug it exists for is not
visible in the script's text: `aws --output text` auto-paginates and applies `--query` to EACH PAGE,
so a single-value query returns one value per page. A layer with 127 versions is three pages, and
the deploy that found this was reusing exactly such a layer.

Attributes:
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
    """Writes an `aws` stand-in that answers a listing the way the paginating CLI does.

    **It applies the caller's `--query` PER PAGE**, which is the CLI's documented behaviour with
    `--output text` and the whole mechanism this suite exists for: a single-value query returns one
    value per page, so the answer to "which is the latest version" arrives as one line per fifty
    versions. The fake understands the two queries this script has used, so the test asserts against
    the mechanism rather than against a fixture shaped to pass.

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


def _layer_table(tmp_path: pathlib.Path) -> pathlib.Path:
    """Writes a one-entry layer table pointing at a real package directory.

    Args:
      tmp_path: The working directory.

    Returns:
      The table's path.

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
    return table


def _run(tmp_path: pathlib.Path, versions: int) -> subprocess.CompletedProcess:
    """Builds the probe layer with publishing off, so the reuse path is the one exercised.

    Args:
      tmp_path: The working directory.
      versions: How many layer versions the fake `aws` reports.

    Returns:
      The completed process, with stdout and stderr captured.

    Raises:
      None.
    """
    env = {
        **os.environ,
        "PATH": f"{_fake_aws(tmp_path, versions)}:{os.environ['PATH']}",
        "LAYERS_JSON_FILE": str(_layer_table(tmp_path)),
        "PROJECT_NAME": "dat",
        "ENVIRONMENT": "prod",
    }
    bash = shutil.which("bash")
    return subprocess.run(  # noqa: S603
        [bash, str(SCRIPT), "probe", "false"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(autouse=True)
def _needs_a_shell():
    """Skips where the tools the script itself needs are absent, rather than failing for a reason
    that is about the machine and not the code."""
    for tool in ("bash", "jq", "awk", "du"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} is not available")


@pytest.mark.parametrize("versions", [1, _PAGE_SIZE, _PAGE_SIZE * 2 + 27])
def test_the_builder_emits_exactly_ONE_record_however_many_pages_the_listing_took(
    tmp_path, versions
):
    """The regression, and the reason the parametrisation crosses the page boundary.

    At one page the old single-value query was right; at three it returned three ARNs, the record
    became three records keyed by an ARN, and the job's own map guard failed the deploy after every
    layer had already been built.
    """
    result = _run(tmp_path, versions)

    assert result.returncode == 0, result.stderr
    assert len(result.stdout.strip().split("\n")) == 1, (
        f"the builder emitted {result.stdout!r} — the caller reads each line as one layer"
    )


def test_the_record_names_the_HIGHEST_version_rather_than_the_first_page_s(tmp_path):
    """ListLayerVersions documents no ordering and the CLI's own guide warns a service "might not
    return items in the same order each time", so the version is chosen by MAX. Picking the first
    row would re-point every function attaching this layer at an arbitrary older version — the
    cold-start failure the reuse mechanism exists to avoid, produced by the mechanism itself."""
    versions = _PAGE_SIZE * 2 + 27

    flag, arn, _ = _run(tmp_path, versions).stdout.strip().split("\t")

    assert flag == "probe"
    assert arn.endswith(f":{versions}")


def test_a_layer_that_has_never_been_published_reports_it_and_does_not_emit_a_record(tmp_path):
    """An empty listing is not a failure — it is a brand-new layer on a push that did not appear to
    change it — but it must not become an empty ARN in the map either, because the deploy would then
    attach nothing and every function using that layer would die at cold start."""
    result = _run(tmp_path, 0)

    assert "publishing despite no detected change" in result.stderr
    assert result.returncode != 0 or result.stdout.strip() == ""
