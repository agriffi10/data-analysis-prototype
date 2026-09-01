"""Lays the Lambda tree out inside the container image, and says what that layout is.

**This module is the single definition of the image's layout.** The Dockerfile runs it to build
the image and deletes it in the same layer; ``test_image_layout.py`` imports it to assert what the
image must contain. Two hand-synced copies of a layout is how a guard comes to agree with a
fixture instead of with the artefact, so there is one copy and both sides read it.

It is Python rather than shell for a measured reason: the AWS Lambda Python base image ships no
``find`` and no ``xargs``. A ``RUN find … -delete`` prune fails with exit 127, and the interpreter
is the one tool a Python runtime image is guaranteed to have.

**The layout reproduces what a layer and a zip produce today**, so no import statement anywhere in
``lambdas/`` changes:

* every layer's package at ``/opt/python/<package>/``, and ``shared-space-common``'s flat modules
  as top-level modules beside them — which is where a Lambda layer lands its ``python/`` directory;
* every function directory's modules at ``${LAMBDA_TASK_ROOT}``, with the function directory's own
  level stripped and anything below it preserved, which is exactly what a zip of that directory
  gives — so ``api/routes/objects_upload.py`` becomes ``/var/task/routes/objects_upload.py``.

That second half is a **flatten**, not a copy-then-prune, and the difference is the whole hazard.
A recursive copy of ``lambdas/`` would carry the ten directories that are not functions — seven
layer packages and the flat-module source — into the task root, where they sit ahead of
``/opt/python`` on the runtime's search path and shadow the very modules they are copies of. A
second copy of every shared module, winning a resolution it is supposed to lose, at cold start.

Dependencies are deliberately NOT placed on ``/opt/python``; the Dockerfile installs them into the
interpreter's own site-packages. Today a layer mixes its package with its pip-installed
dependencies in one directory, so reproducing that exactly would make "the set of packages under
``/opt/python`` equals the set the layer table declares" false by construction, and the guard would
decay into a hand-maintained dependency list. Both locations are on the search path either way.

Attributes:
  PRUNE_PREFIXES: Filename prefixes never copied. Matches what ``deploy-lambda.sh`` prunes from a
    function package, by name at any depth rather than by a top-level glob — the shallow version
    of this rule once shipped two functions' ``conftest.py``.
  PRUNE_NAMES: Exact filenames never copied, for the same reason.
"""

import argparse
import ast
import json
import pathlib
import shutil

PRUNE_PREFIXES = ("test_",)
PRUNE_NAMES = ("conftest.py",)


class LayoutError(Exception):
    """A layout the layer table and the tree cannot jointly satisfy.

    Raised rather than asserted because these are build-time refusals: an ``assert`` is stripped
    under ``-O``, and every one of these checks exists to stop an image being built that is wrong
    in a way only a cold start would reveal.
    """


def defines_handler(path: pathlib.Path) -> bool:
    """Reports whether a module defines a top-level ``handler`` function.

    This is the fleet's one definition of "is a Lambda", shared with
    ``lambdas/test_deploy_matrix.py`` so that harnesses over the fleet cannot drift into covering
    different sets.

    Args:
      path: The module to read.

    Returns:
      True when the module's body defines a function named ``handler``.

    Raises:
      SyntaxError: When the module does not parse — a broken tree rather than a non-Lambda. Note
        this only covers modules the caller reaches: ``function_directories`` stops at the first
        module defining ``handler``, so an unparseable module sorting after it is never read here.
        The image's behaviour matrix imports every module and is what catches that one.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    return any(isinstance(node, ast.FunctionDef) and node.name == "handler" for node in tree.body)


def function_directories(lambdas: pathlib.Path) -> dict[str, str]:
    """Finds every function directory, mapped to its handler module's filename.

    Args:
      lambdas: The ``lambdas/`` tree.

    Returns:
      Directory name to handler module filename, ordered by directory name.

    Raises:
      SyntaxError: Propagated from ``defines_handler``.
    """
    found = {}
    for directory in sorted(lambdas.iterdir()):
        if not directory.is_dir() or directory.name.startswith((".", "_")):
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith(PRUNE_PREFIXES):
                continue
            if defines_handler(path):
                found[directory.name] = path.name
                break
    return found


def packaged_modules(directory: pathlib.Path) -> list[pathlib.PurePath]:
    """Lists the modules a function directory ships, as paths relative to it.

    Deliberately keeps ``fakes.py`` and ``__init__.py``: ``deploy-lambda.sh`` prunes neither from
    a function directory, an ``__init__.py`` is how a package is a package, and this image
    reproduces today's packaging rather than improving on it.

    Args:
      directory: One function directory.

    Returns:
      Relative paths, sorted, with hidden directories and suites excluded.

    Raises:
      None.
    """
    modules: list[pathlib.PurePath] = []
    for path in sorted(directory.rglob("*.py")):
        relative = path.relative_to(directory)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.name.startswith(PRUNE_PREFIXES) or path.name in PRUNE_NAMES:
            continue
        modules.append(relative)
    return modules


def shared_layout(repo: pathlib.Path) -> tuple[dict[str, pathlib.Path], dict[str, pathlib.Path]]:
    """Resolves what belongs on ``/opt/python``, from the layer table rather than a list.

    The table is the same one the layer build reads, so a package added there ships here without
    a second edit. ``shared-space-common``'s flat modules are the one layer packaged by an
    explicit module list, and that list is read rather than restated.

    Args:
      repo: The repository root.

    Returns:
      A pair of maps: package name to its source directory, and flat module name to its source
      file.

    Raises:
      LayoutError: When the table names a source that does not exist, which would otherwise
        produce an image missing a layer nobody notices until a cold start.
    """
    table = json.loads((repo / ".github" / "lambda-layers.json").read_text())
    packages: dict[str, pathlib.Path] = {}
    flat: dict[str, pathlib.Path] = {}
    for entry in table:
        package = entry.get("package")
        if package:
            source = repo / package
            if not source.is_dir():
                raise LayoutError(f"{entry['flag']}: {package} is not a directory")
            packages[source.name] = source
        source_dir = entry.get("sourceDir")
        if source_dir:
            for module in entry.get("modules", []):
                source = repo / source_dir / f"{module}.py"
                if not source.is_file():
                    raise LayoutError(f"{entry['flag']}: {source} is missing")
                flat[module] = source
    return packages, flat


def task_root_layout(repo: pathlib.Path) -> dict[pathlib.PurePath, pathlib.Path]:
    """Resolves what belongs at the task root, keyed by its destination.

    Keying by DESTINATION is what makes a collision between two function directories a visible
    error rather than a silent overwrite: two directories contributing the same relative path
    would otherwise leave whichever was copied second, and every function would import that one.

    Args:
      repo: The repository root.

    Returns:
      Destination path (relative to the task root) to source file.

    Raises:
      LayoutError: When two function directories contribute the same destination.
    """
    lambdas = repo / "lambdas"
    layout: dict[pathlib.PurePath, pathlib.Path] = {}
    owners: dict[pathlib.PurePath, str] = {}
    for name in function_directories(lambdas):
        directory = lambdas / name
        for relative in packaged_modules(directory):
            if relative in layout:
                raise LayoutError(
                    f"{name}/{relative} collides with {owners[relative]}/{relative} at the task "
                    "root. Every function shares one task root in the image, so two directories "
                    "cannot contribute the same path — one would silently win for the fleet."
                )
            layout[relative] = directory / relative
            owners[relative] = name
    return layout


def assemble(repo: pathlib.Path, opt_python: pathlib.Path, task_root: pathlib.Path) -> None:
    """Writes both layouts into the image.

    Args:
      repo: The repository root, as copied into the build stage.
      opt_python: Where a layer's ``python/`` directory lands at runtime.
      task_root: ``${LAMBDA_TASK_ROOT}``.

    Returns:
      None.

    Raises:
      LayoutError: Propagated from the layout resolvers.
    """
    packages, flat = shared_layout(repo)
    opt_python.mkdir(parents=True, exist_ok=True)
    for name, source in packages.items():
        shutil.copytree(
            source,
            opt_python / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("test_*", "conftest.py", "__pycache__"),
        )
    for name, source in flat.items():
        shutil.copy2(source, opt_python / f"{name}.py")

    task_layout = task_root_layout(repo)
    for relative, source in task_layout.items():
        destination = task_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    print(
        f"assembled {len(packages)} layer packages, {len(flat)} flat modules, "
        f"{len(task_layout)} function modules"
    )


def main() -> None:
    """Runs the assembler from the Dockerfile.

    Args:
      None.

    Returns:
      None.

    Raises:
      LayoutError: Propagated, so a layout the table cannot satisfy fails the BUILD rather
        than producing an image that is wrong in a way only a cold start reveals.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=pathlib.Path)
    parser.add_argument("opt_python", type=pathlib.Path)
    parser.add_argument("task_root", type=pathlib.Path)
    arguments = parser.parse_args()
    assemble(arguments.repo, arguments.opt_python, arguments.task_root)


if __name__ == "__main__":
    main()
