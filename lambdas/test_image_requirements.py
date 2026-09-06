"""Every requirements file in the tree is one the image actually installs.

`lambdas/Dockerfile` names each requirements file twice — once in a `COPY` and once in the
`pip install` — and nothing derives that list from the tree. Its own comment rejects a glob on
purpose, so the list is hand-kept, and a hand-kept list of files is the shape that rots.

**The failure mode is invisible everywhere it could be caught.** A new
`lambdas/<verb>/requirements.txt` that nobody adds to the Dockerfile is green in the suite,
green in CI (which runs no pytest), green in `tofu validate`, and produces an image whose
site-packages is missing the dependency. The verb then fails at the moment a user first reaches
the code path that imports it — `polars.write_excel` imports `xlsxwriter` lazily, so an Excel
conversion is a `ModuleNotFoundError` in production while Parquet and JSON keep working.

The reverse direction matters too: a `--requirement` naming a file that has been deleted fails
the BUILD, which is loud, but a `COPY` without a matching `--requirement` installs nothing while
looking installed.

Attributes:
  LAMBDAS: The Lambda tree.
  DOCKERFILE: The image definition whose two lists this holds equal to the tree.
  _COPY: A requirements `COPY`, capturing the source path and the name it lands under.
  _REQUIREMENT: An installed requirements file, capturing the name it was copied to.
"""

import pathlib
import re
import sys

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent
DOCKERFILE = LAMBDAS / "Dockerfile"

_COPY = re.compile(r"^COPY\s+(lambdas/\S*requirements\S*\.txt)\s+(/tmp/requirements/\S+)", re.MULTILINE)
_REQUIREMENT = re.compile(r"--requirement\s+(/tmp/requirements/\S+)")


def _dockerfile() -> str:
    """Reads the image definition.

    Args:
      None.

    Returns:
      Its text.

    Raises:
      None.
    """
    return DOCKERFILE.read_text(encoding="utf-8")


def _on_disk() -> set[str]:
    """Every requirements file the tree holds, as repository-relative paths.

    Args:
      None.

    Returns:
      The paths, in the form the Dockerfile's COPY lines write them.

    Raises:
      None.
    """
    return {
        f"lambdas/{path.relative_to(LAMBDAS).as_posix()}"
        for path in LAMBDAS.rglob("requirements*.txt")
    }


def test_the_image_copies_and_installs_every_requirements_file_the_tree_holds():
    """The three lists — the tree, the COPY lines and the install flags — are one list.

    `requirements-dev.txt` is the one deliberate exclusion: it is lint and test tooling that no
    function imports, and the file says so at the top. It is named here rather than pattern-
    matched away, so deleting it or renaming it reddens this instead of silently widening the
    hole.
    """
    copied = dict(_COPY.findall(_dockerfile()))
    installed = set(_REQUIREMENT.findall(_dockerfile()))

    assert copied, "no COPY of a requirements file was found; the pattern has stopped matching"
    on_disk = _on_disk()
    assert "lambdas/requirements-dev.txt" in on_disk, (
        "the dev tooling file is gone, so the exclusion below no longer describes anything"
    )
    shipped = on_disk - {"lambdas/requirements-dev.txt"}

    assert set(copied) == shipped, (
        "the image's COPY list and the tree disagree. A file on disk that is not copied is a "
        "dependency the image does not install, and the verb that needs it fails at the moment "
        "a user first reaches the import"
    )
    assert set(copied.values()) == installed, (
        "a requirements file is copied into the image but never passed to pip, or the reverse. "
        "The first installs nothing while looking installed"
    )


def test_every_requirement_carries_a_version_constraint():
    """The image's own build refuses an unconstrained requirement, and this says so before the
    build does — a five-minute docker build is a slow way to learn about a missing `==`.

    It is the same rule rather than a second one: the check inside the Dockerfile is what
    enforces it, and this only brings the failure forward to the suite. So it runs over the
    SHIPPED files only, which is the population that check sees: `requirements-dev.txt` never
    enters the image and holds `boto3` deliberately unpinned, for reasons its own comment
    gives at length.
    """
    loose = []
    for path in sorted(_on_disk() - {"lambdas/requirements-dev.txt"}):
        full = LAMBDAS.parent / path
        for number, line in enumerate(full.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            spec = stripped.split("#")[0].split(";")[0]
            if not re.search(r"[<>=~!]=|[<>]", spec):
                loose.append(f"{path}:{number} {stripped!r}")
    assert loose == [], f"requirement(s) with no version constraint: {loose}"


@pytest.mark.parametrize("path", ["Dockerfile", "requirements.txt"])
def test_the_files_this_suite_reads_exist(path):
    assert (LAMBDAS / path).exists(), f"{path} is missing, so the assertions over it are vacuous"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
