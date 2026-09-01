"""Reports what the Lambda image actually contains, from inside it, under the real runtime.

This file is **bind-mounted into the task root at test time and is never in the image**. It is
invoked as the image's handler through the Runtime Interface Emulator that ships in the AWS base
image, which is the whole point: the emulator runs ``/var/runtime/bootstrap``, so ``sys.path`` here
is the one a deployed function gets, built by the runtime rather than reconstructed by the test.

**Why that matters more than it sounds.** Running ``docker run --entrypoint python`` instead gives
a path with neither ``/opt/python`` nor its site-packages on it — measured — so a sweep taken that
way would have to rebuild the search path by hand, and a rebuilt path that is a superset of the
real one passes an import that production would fail. That is the exact shape of the outage this
whole arc exists to prevent, rebuilt by the tool meant to prevent it. Here there is nothing to
rebuild: the path is read from the interpreter the bootstrap started.

**Each import runs in its own subprocess**, carrying that same path forward as ``PYTHONPATH`` and
running under ``-P`` so the interpreter does not prepend a directory of its own. One process
importing all of them would let one module's import satisfy the next module's, which is a way to
pass while the deployed artefact fails. The subprocess path is returned too, so the caller can
assert it matches the runtime's rather than take this docstring's word for it.

Everything is returned as data. This module asserts nothing; ``lambda-image-matrix.sh`` decides
what the numbers have to be, because the expectations are host-side facts about the repository and
this process cannot see the repository.

Attributes:
  TASK_ROOT: ``${LAMBDA_TASK_ROOT}`` — where a zip's modules land, and where this file is mounted.
  OPT_PYTHON: Where a layer's ``python/`` directory lands.
  SELF_PREFIX: The filename prefix this module uses so it can exclude itself from every listing
    it produces. Mounted rather than built in, it is not part of the image under test.
  OFFENDER_PATTERNS: What must not be in the image, expressed as patterns rather than filenames —
    a list of names would pass the day someone adds a suite this test has never heard of.
  IMPORT_PROBE: The program each subprocess runs. It imports one handler module and checks the
    attribute the runtime would look up.
"""

import ast
import fnmatch
import json
import os
import pathlib
import subprocess
import sys

TASK_ROOT = pathlib.Path(os.environ.get("LAMBDA_TASK_ROOT", "/var/task"))
OPT_PYTHON = pathlib.Path("/opt/python")
SELF_PREFIX = "_matrix_"
OFFENDER_PATTERNS = ("test_*.py", "conftest.py", "__pycache__", "requirements*.txt")
IMPORT_PROBE = (
    "import importlib, sys;"
    "module = importlib.import_module(sys.argv[1]);"
    "handler = getattr(module, 'handler', None);"
    "assert callable(handler), 'handler exists but is not callable'"
)


def _offenders(root: pathlib.Path) -> tuple[list[str], int]:
    """Finds anything under a tree matching a pattern the image must not ship.

    The number of paths examined is returned beside the findings, because the finding is an
    ABSENCE: a walk that examined nothing reports no offenders and reads exactly like a clean
    image. The caller refuses a zero rather than trusting the empty list.

    Args:
      root: The tree to walk.

    Returns:
      The offending paths, sorted, and how many paths were examined.

    Raises:
      None.
    """
    found = []
    examined = 0
    for path in root.rglob("*"):
        if path.name.startswith(SELF_PREFIX):
            continue
        examined += 1
        if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in OFFENDER_PATTERNS):
            found.append(str(path))
    return sorted(found), examined


def _handler_modules() -> list[str]:
    """Finds every top-level module in the task root that defines a top-level ``handler``.

    This is the same definition of "is a Lambda" the deploy matrix and the assembler use, applied
    to the artefact instead of to the source tree. The caller compares the count against the
    number of function directories in the repository, so a module that failed to copy shows up as
    a shortfall rather than as a shorter sweep nobody notices.

    Args:
      None.

    Returns:
      Module names, sorted.

    Raises:
      SyntaxError: When a module in the task root does not parse. A tree that cannot be read is a
        broken image, not an image with fewer Lambdas.
    """
    modules = []
    for path in sorted(TASK_ROOT.glob("*.py")):
        if path.name.startswith(SELF_PREFIX):
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        if any(isinstance(n, ast.FunctionDef) and n.name == "handler" for n in tree.body):
            modules.append(path.stem)
    return modules


def _site_packages_names() -> list[str]:
    """Lists the top-level importable names the installed dependencies provide.

    Needed because this image puts the repository's shared code AHEAD of the dependencies on the
    search path, which a layer never did. A repository module sharing a name with a dependency
    would shadow it silently, and the names most at risk are exactly the generic ones the flat
    layer already uses.

    Args:
      None.

    Returns:
      Top-level names, sorted and de-duplicated.

    Raises:
      None.
    """
    names = set()
    for entry in sys.path:
        directory = pathlib.Path(entry)
        if "site-packages" not in entry or not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.name.startswith((".", "_")) or child.name.endswith((".dist-info", ".pth")):
                continue
            names.add(child.stem if child.suffix == ".py" else child.name)
    return sorted(names)


def handler(event, context):
    """Reports the image's layout and the result of importing every handler module.

    Args:
      event: Ignored. The emulator requires a payload; this sweep takes no input.
      context: Ignored.

    Returns:
      A mapping the matrix script asserts against: the interpreter version, the two search paths,
      what is on ``/opt/python`` and in the task root, anything matching an offender pattern, and
      one entry per handler module that failed to import, and how many paths the offender walk
      examined so the caller can tell an absence from an empty walk.

    Raises:
      SyntaxError: Propagated from the task-root scan, so an unreadable module fails the matrix.
    """
    opt_offenders, opt_examined = _offenders(OPT_PYTHON)
    task_offenders, task_examined = _offenders(TASK_ROOT)
    runtime_path = [entry for entry in sys.path if entry]
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join(runtime_path))

    modules = _handler_modules()
    failures = {}
    for module in modules:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-P", "-c", IMPORT_PROBE, module],
            capture_output=True,
            text=True,
            env=environment,
            cwd=str(TASK_ROOT),
        )
        print(f"  {'ok  ' if result.returncode == 0 else 'FAIL'} {module}", file=sys.stderr)
        if result.returncode != 0:
            lines = (result.stderr or "").strip().splitlines()
            failures[module] = lines[-1] if lines else "no stderr"

    observed = subprocess.run(
        [sys.executable, "-P", "-c", "import json, sys; print(json.dumps(sys.path))"],
        capture_output=True,
        text=True,
        env=environment,
        cwd=str(TASK_ROOT),
    )

    return {
        "python": ".".join(str(part) for part in sys.version_info[:2]),
        "runtime_path": runtime_path,
        "subprocess_path": json.loads(observed.stdout) if observed.returncode == 0 else None,
        "opt_packages": sorted(
            child.name for child in OPT_PYTHON.iterdir() if child.is_dir()
        ),
        "opt_flat_modules": sorted(child.stem for child in OPT_PYTHON.glob("*.py")),
        "task_top_level": sorted(
            child.stem if child.suffix == ".py" else child.name
            for child in TASK_ROOT.iterdir()
            if not child.name.startswith(SELF_PREFIX)
        ),
        "site_packages_names": _site_packages_names(),
        "offenders": opt_offenders + task_offenders,
        "paths_examined": opt_examined + task_examined,
        "handler_count": len(modules),
        "import_failures": failures,
    }
