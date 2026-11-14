"""Every image this repo builds is pushed as one manifest, and the Lambda fleet's cannot be anything else.

Docker adds a provenance attestation by default, and an image carrying one is pushed as an OCI
image index. Lambda refuses an index at `UpdateFunctionCode`, in another workflow, after the push
has reported success; the image it replaces keeps running, so nothing looks broken until the next
deploy fails for every function at once. ECS runs an index, but its untagged children take slots in
the SPA registry's lifecycle count and shrink the rollback window.

Attributes:
  ROOT: The repository root.
  WORKFLOWS: The workflows directory.
  CHECK: The script that refuses any shape but a single manifest.
  FLEET_BUILDS: The two workflows that build the Lambda fleet's image.
  IMAGE_BUILDS: Every workflow that builds an image.
"""

import os
import pathlib
import subprocess

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
CHECK = ROOT / ".github" / "scripts" / "assert-single-manifest.sh"
FLEET_BUILDS = ("lambda-image.yml", "deploy-lambda-image.yml")
IMAGE_BUILDS = (*FLEET_BUILDS, "spa-image.yml", "deploy-spa-image.yml")


def _steps(name: str) -> list[dict]:
    """Returns every step of every job in a workflow, in order.

    Args:
      name: The workflow's file name.

    Returns:
      The steps.

    Raises:
      None.
    """
    jobs = yaml.safe_load((WORKFLOWS / name).read_text())["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


@pytest.mark.parametrize("name", IMAGE_BUILDS)
def test_every_image_build_adds_no_attestation(name: str) -> None:
    """Without both flags the push is an index: Lambda refuses it, and ECR counts its children."""
    builds = [" ".join(step["run"].split()) for step in _steps(name) if "docker build" in step.get("run", "")]
    assert len(builds) == 1, f"{name} has {len(builds)} build steps"
    assert "--provenance=false" in builds[0], f"{name} adds a provenance attestation"
    assert "--sbom=false" in builds[0], f"{name} adds an SBOM attestation"


@pytest.mark.parametrize("name", FLEET_BUILDS)
def test_the_fleet_image_is_checked_after_the_build_and_before_any_push(name: str) -> None:
    """Checked on the built image, so a refused shape never reaches a registry it cannot leave."""
    runs = [step.get("run", "") for step in _steps(name)]
    build = next(i for i, run in enumerate(runs) if "docker build" in run)
    check = next(i for i, run in enumerate(runs) if "assert-single-manifest.sh" in run)
    pushes = [i for i, run in enumerate(runs) if "docker push" in run]
    assert build < check and all(check < push for push in pushes)


@pytest.mark.parametrize(
    ("media", "passes"),
    [
        ("application/vnd.docker.distribution.manifest.v2+json", True),
        ("application/vnd.oci.image.manifest.v1+json", True),
        ("application/vnd.oci.image.index.v1+json", False),
        ("application/vnd.docker.distribution.manifest.list.v2+json", False),
        ("", False),
    ],
)
def test_the_check_passes_a_single_manifest_and_refuses_everything_else(tmp_path, media: str, passes: bool) -> None:
    """An allowlist: an index, a list, or nothing at all fails closed, naming why."""
    stub = tmp_path / "docker"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{media}'\n")
    stub.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [str(CHECK), "lambda-fleet:test"],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if not passes:
        assert "Not a single manifest" in result.stderr
