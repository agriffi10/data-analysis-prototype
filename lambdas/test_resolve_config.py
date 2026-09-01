"""The resolver, driven as the deploy drives it.

``resolve-config.sh`` is what stands between Terraform's state and a published
configuration document, and the failure it replaces was silent: an unset repository
variable interpolated to the empty string, satisfied every presence test, and surfaced as
an ``s3:///_config/...`` copy failing far from its cause. So these run the real script
against captured ``tofu output -json`` documents and assert the WORDING — the
configuration key and the Terraform output both named — rather than an exit code. The
absent branch and the empty branch return the same code, which is exactly what would let
one of them rot unnoticed.

The real ``tofu output`` invocation is not exercised here and cannot be: it needs the
remote state and the deploy role. What that costs is recorded beside the workflow tests.

Attributes:
  ROOT: The repository root.
  SCRIPT: The resolver under test.
  MAPPING: The real map, used so these tests fail when it and the script disagree.
"""

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "resolve-config.sh"
MAPPING = ROOT / ".github" / "config-outputs.json"


def _document(**overrides: object) -> dict:
    """Builds a ``tofu output -json`` document covering the whole map.

    Args:
      **overrides: Output names to override. A value of ``None`` drops the output
        entirely, which is the absent case; any other value replaces it.

    Returns:
      The document, in OpenTofu's ``{name: {value: ...}}`` shape.

    Raises:
      None.
    """
    mapping = json.loads(MAPPING.read_text())
    document = {name: {"value": f"resolved-{name}"} for name in mapping}
    for name, value in overrides.items():
        if value is None:
            document.pop(name, None)
        else:
            document[name] = {"value": value}
    return document


def _run(tmp_path: pathlib.Path, document: dict) -> tuple[subprocess.CompletedProcess, str]:
    """Runs the resolver against a captured outputs document.

    Args:
      tmp_path: A pytest temporary directory for the document and the step-output file.
      document: The ``tofu output -json`` document to resolve from.

    Returns:
      The completed process, and the contents of the step-output file it wrote.

    Raises:
      None.
    """
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps(document))
    step_output = tmp_path / "step-output"
    step_output.touch()

    completed = subprocess.run(  # noqa: S603
        [
            str(SCRIPT),
            "--mapping",
            str(MAPPING),
            "--outputs",
            str(outputs),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GITHUB_OUTPUT": str(step_output)},
    )
    return completed, step_output.read_text()


def test_it_resolves_every_mapped_key(tmp_path: pathlib.Path) -> None:
    """The happy path, and the guard-the-guard for every refusal below.

    A resolver that emitted nothing would make each refusal test pass for the wrong
    reason, so this asserts the whole map arrives before anything asserts a failure.

    Args:
      tmp_path: pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: If the run fails or any configuration key is missing.
    """
    completed, written = _run(tmp_path, _document())

    assert completed.returncode == 0, completed.stderr
    for config_key in json.loads(MAPPING.read_text()).values():
        assert f"{config_key}<<" in written


def test_an_absent_output_fails_the_job_naming_both(tmp_path: pathlib.Path) -> None:
    """An output missing from the state stops the deploy, and says which one.

    Args:
      tmp_path: pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: If the run succeeds, or the message names neither the key nor the
        output, or reports the wrong branch.
    """
    completed, _ = _run(tmp_path, _document(cognito_domain=None))

    assert completed.returncode != 0
    assert "cognitoDomain" in completed.stderr
    assert "cognito_domain" in completed.stderr
    assert "absent from the state" in completed.stderr


def test_an_empty_output_fails_the_job_the_same_way(tmp_path: pathlib.Path) -> None:
    """The branch the old arrangement could not see.

    An empty value satisfies every presence test there is, so emptiness is the thing
    checked. The message must distinguish it from the absent case, or a reader fixing a
    genuinely absent output would go looking for an empty one.

    Args:
      tmp_path: pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: If the run succeeds, or the message does not name the empty branch.
    """
    completed, _ = _run(tmp_path, _document(s3_user_space_bucket_name=""))

    assert completed.returncode != 0
    assert "userSpaceBucket" in completed.stderr
    assert "s3_user_space_bucket_name" in completed.stderr
    assert "is empty" in completed.stderr
    assert "absent from the state" not in completed.stderr


def test_it_reports_every_missing_value_at_once(tmp_path: pathlib.Path) -> None:
    """One deploy cycle per missing value is the cost this avoids.

    Args:
      tmp_path: pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: If the run stops at the first fault.
    """
    completed, _ = _run(tmp_path, _document(api_origin=None, cognito_domain=""))

    assert completed.returncode != 0
    assert "apiBaseUrl" in completed.stderr
    assert "cognitoDomain" in completed.stderr


def test_an_empty_map_is_refused(tmp_path: pathlib.Path) -> None:
    """A map that parsed to nothing would resolve nothing and report success.

    That is the one failure mode with no downstream symptom: the deploy would carry on
    and publish a document built entirely from values nobody supplied.

    Args:
      tmp_path: pytest's temporary directory.

    Returns:
      None.

    Raises:
      AssertionError: If an empty map is accepted.
    """
    empty = tmp_path / "empty.json"
    empty.write_text("{}")
    outputs = tmp_path / "outputs.json"
    outputs.write_text("{}")
    step_output = tmp_path / "step-output"
    step_output.touch()

    completed = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--mapping", str(empty), "--outputs", str(outputs)],
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GITHUB_OUTPUT": str(step_output)},
    )

    assert completed.returncode != 0
    assert "declares no entries" in completed.stderr
