"""The TF_VAR guard over the variable sets a deploy can present, silence included.

Silence is what every correct deploy sees, so it is pinned as carefully as each refusal: a guard
that refused a correct deploy would be switched off, and one that passed a stray variable is the
defect it exists for. Every refusal is asserted by its reason, because the neighbouring refusal
returns the same exit code.

Attributes:
  ROOT: The repository root.
  GUARD_PATH: The script under test.
  GUARD: The script under test, imported by path because `.github/scripts` is not a package.
  NAMES: The variables the corpus's module declares, spelled as OpenTofu matches them.
  GIVEN: A step environment shaped like the deploy's plan step, including an input handed over
    from a differently named variable.
  CORPUS: Variable sets, the step environment each meets, and the problems the guard must report.
"""

import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / ".github" / "scripts" / "tf_var_guard.py"

_spec = importlib.util.spec_from_file_location("tf_var_guard", GUARD_PATH)
GUARD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GUARD)

NAMES = {"github_repo", "spa_subdomain", "max_upload_bytes", "project_name", "environment", "workgroup_name"}

GIVEN = {
    "PATH": "/usr/bin",
    "TF_VAR_github_repo": "owner/repo",
    "TF_VAR_spa_subdomain": "portal",
    "TF_VAR_max_upload_bytes": "5368709120",
}

CORPUS = [
    pytest.param({}, GIVEN, [], id="nothing set"),
    pytest.param({"AWS_REGION": "eu-west-2", "VITE_APP_URL": "https://x"}, GIVEN, [], id="not a Terraform variable"),
    pytest.param(
        {"TF_VAR_GITHUB_REPO": "owner/repo", "TF_VAR_SPA_SUBDOMAIN": "portal"},
        GIVEN,
        [],
        id="handed over unchanged, upper-cased as GitHub stores it",
    ),
    pytest.param(
        {"TF_VAR_PROJECT_NAME": "acme"},
        GIVEN,
        ["TF_VAR_PROJECT_NAME is set, and this run does not give it to Terraform"],
        id="never handed over",
    ),
    pytest.param(
        {"TF_VAR_MAX_UPLOAD_BYTES": "1024"},
        GIVEN,
        ["TF_VAR_MAX_UPLOAD_BYTES is set, and Terraform is given a different value under that name"],
        id="that name is handed over from another variable",
    ),
    pytest.param(
        {"TF_VAR_SPA_SUBDOMAIN": "custom"},
        {"PATH": "/usr/bin", "TF_VAR_SPA_SUBDOMAIN": "custom"},
        ["TF_VAR_SPA_SUBDOMAIN is set, and this run does not give it to Terraform"],
        id="handed over under the upper-cased spelling OpenTofu ignores",
    ),
    pytest.param(
        {"TF_VAR_SPA_SUBDOMIAN": "custom"},
        {"PATH": "/usr/bin", "TF_VAR_spa_subdomian": "custom"},
        ["TF_VAR_SPA_SUBDOMIAN is set, and this run does not give it to Terraform"],
        id="handed over under a name the module does not declare",
    ),
    pytest.param(
        {"TF_VAR_workgroup_name": "wg", "TF_VAR_GITHUB_REPO": "owner/repo", "TF_VAR_ENVIRONMENT": "staging"},
        GIVEN,
        [
            "TF_VAR_ENVIRONMENT is set, and this run does not give it to Terraform",
            "TF_VAR_WORKGROUP_NAME is set, and this run does not give it to Terraform",
        ],
        id="every offender named, sorted, beside one that is fine",
    ),
]


@pytest.fixture
def module(tmp_path, monkeypatch) -> pathlib.Path:
    """A working directory declaring the corpus's variables, the way `infra/` does.

    Args:
      tmp_path: A private directory for this test.
      monkeypatch: Moves the process into it for the duration of the test.

    Returns:
      The directory.

    Raises:
      None.
    """
    (tmp_path / "variables.tf").write_text(
        "".join(f'variable "{name}" {{\n  type = string\n}}\n\n' for name in sorted(NAMES)), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.mark.parametrize(("variables", "environment", "expected"), CORPUS)
def test_the_guard_names_exactly_the_variables_terraform_does_not_receive(variables, environment, expected) -> None:
    """Each variable set against the environment a step presents, the silent cases included.

    Args:
      variables: The Actions variables, as `toJSON(vars)` would render them.
      environment: The environment of the step that invokes `tofu`.
      expected: The problems the guard must report, in order.

    Returns:
      None.

    Raises:
      AssertionError: If the guard reports anything other than exactly `expected`.
    """
    assert GUARD.unreceived(variables, environment, NAMES) == expected


def test_the_declared_names_are_the_top_level_variable_blocks(tmp_path) -> None:
    """Only a top-level block declares an input; a mention in a comment or a description does not.

    Args:
      tmp_path: A private directory holding the module under test.

    Returns:
      None.

    Raises:
      AssertionError: If a name is missed, or read from anything but a top-level block.
    """
    (tmp_path / "variables.tf").write_text(
        'variable "spa_subdomain" {\n  description = "not variable \\"x\\" {"\n}\n'
        '# variable "commented" {\n'
        '  variable "indented" {\n',
        encoding="utf-8",
    )
    (tmp_path / "main.tf").write_text('variable "github_repo" {}\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text('variable "not_terraform" {\n', encoding="utf-8")

    assert GUARD.declared(tmp_path) == {"spa_subdomain", "github_repo"}


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        pytest.param(dict(GIVEN), "REPO_VARS is not set", id="no REPO_VARS"),
        pytest.param({**GIVEN, "REPO_VARS": "not json"}, "not a JSON object", id="REPO_VARS unparseable"),
        pytest.param({**GIVEN, "REPO_VARS": '["TF_VAR_X"]'}, "not a JSON object", id="REPO_VARS a list"),
        pytest.param(
            {"PATH": "/usr/bin", "REPO_VARS": "{}"}, "not the step that invokes tofu", id="run outside the tofu step"
        ),
    ],
)
def test_the_guard_refuses_to_answer_when_it_cannot_tell(module, monkeypatch, capsys, environment, reason) -> None:
    """Each condition under which a clean answer would be a guess exits 2 and says which.

    Args:
      module: Runs the guard from a directory declaring the corpus's variables.
      monkeypatch: Replaces the process environment the guard reads.
      capsys: Captures the annotation the guard prints.
      environment: The environment the guard runs in.
      reason: The phrase its refusal must carry.

    Returns:
      None.

    Raises:
      AssertionError: If the guard does not exit 2, or its message does not name the reason.
    """
    monkeypatch.setattr(GUARD.os, "environ", environment)

    assert GUARD.main() == 2
    assert reason in capsys.readouterr().out


def test_the_guard_refuses_a_directory_that_declares_nothing(tmp_path, monkeypatch, capsys) -> None:
    """Run from anywhere but the module, every variable would read as unreceived for the wrong reason.

    Args:
      tmp_path: An empty directory to run the guard from.
      monkeypatch: Moves the process there and replaces its environment.
      capsys: Captures the annotation the guard prints.

    Returns:
      None.

    Raises:
      AssertionError: If the guard does not exit 2 naming the directory as the reason.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(GUARD.os, "environ", {**GIVEN, "REPO_VARS": "{}"})

    assert GUARD.main() == 2
    assert "declares no variable" in capsys.readouterr().out


def test_the_guard_fails_a_run_on_a_stray_variable_and_passes_a_clean_one(module, monkeypatch, capsys) -> None:
    """The exit status a workflow step acts on, and the annotation an operator reads.

    Args:
      module: Runs the guard from a directory declaring the corpus's variables.
      monkeypatch: Replaces the process environment the guard reads.
      capsys: Captures the annotations the guard prints.

    Returns:
      None.

    Raises:
      AssertionError: If a stray variable does not fail the run by name, or a clean run prints
        anything or fails.
    """
    monkeypatch.setattr(GUARD.os, "environ", {**GIVEN, "REPO_VARS": json.dumps({"TF_VAR_PROJECT_NAME": "acme"})})
    assert GUARD.main() == 1
    printed = capsys.readouterr().out
    assert "::error title=Unused Terraform input::TF_VAR_PROJECT_NAME is set" in printed
    assert "acme" not in printed

    monkeypatch.setattr(GUARD.os, "environ", {**GIVEN, "REPO_VARS": json.dumps({"TF_VAR_GITHUB_REPO": "owner/repo"})})
    assert GUARD.main() == 0
    assert capsys.readouterr().out == ""
