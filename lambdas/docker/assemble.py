"""Lays the Lambda tree out inside the container image, and says what that layout is.

**This module is the single definition of the image's layout.** The Dockerfile runs it to build
the image and deletes it in the same layer; ``test_image_layout.py`` imports it to assert what the
image must contain. Two hand-synced copies of a layout is how a guard comes to agree with a
fixture instead of with the artefact, so there is one copy and both sides read it.

It is Python rather than shell for a measured reason: the AWS Lambda Python base image ships no
``find`` and no ``xargs``. A ``RUN find … -delete`` prune fails with exit 127, and the interpreter
is the one tool a Python runtime image is guaranteed to have.

**The layout reproduced what a layer and a zip produced**, so no import statement anywhere in
``lambdas/`` changed when the fleet moved onto the image, and none changed when the layers were
retired behind it:

* every shared source's package at ``/opt/python/<package>/``, and ``shared-space-common``'s flat
  modules as top-level modules beside them — which is where a Lambda layer landed its ``python/``
  directory, and is why that path is the one used;
* every function directory's modules at ``${LAMBDA_TASK_ROOT}``, with the function directory's own
  level stripped and anything below it preserved, which is exactly what a zip of that directory
  gives — so ``api/routes/objects_upload.py`` becomes ``/var/task/routes/objects_upload.py``.

That second half is a **flatten**, not a copy-then-prune, and the difference is the whole hazard.
A recursive copy of ``lambdas/`` would carry every directory that is not a function into the task
root — the shared sources among them — where they sit ahead of ``/opt/python`` on the runtime's
search path and shadow the very modules they are copies of. A second copy of every shared module,
winning a resolution it is supposed to lose, at cold start.

Dependencies are deliberately NOT placed on ``/opt/python``; the Dockerfile installs them into the
interpreter's own site-packages. A layer mixed its package with its pip-installed dependencies in
one directory, so reproducing that exactly would make "the set of packages under ``/opt/python``
equals what the shared sources publish" false by construction, and the guard would decay into a
hand-maintained dependency list. Both locations are on the search path either way.

Attributes:
  PRUNE_PREFIXES: Filename prefixes never copied from a FUNCTION directory, by name at any depth
    rather than by a top-level glob — the shallow version of this rule once shipped two functions'
    ``conftest.py``.
  PRUNE_NAMES: Exact filenames never copied from a function directory, for the same reason.
  NOT_SHIPPED: What a SHARED directory does not publish AT ITS TOP LEVEL, matched as a PREFIX —
    which is exact for the three filenames, since a candidate has already been filtered to
    ``.py``. Deliberately a different rule from the two above and not to be merged with them: a
    function ships its own ``fakes.py`` and its ``__init__.py`` like any other module, and a
    shared directory must publish neither at its top level. **Inside a package the pruning is
    ``copytree``'s, not this**, and the two lists differ: that one drops ``test_*`` and
    ``conftest.py`` but not ``fakes.py``, so a test double nested inside a package would ship.
    No shared source has one today — every suite, ``conftest.py`` and ``fakes.py`` under
    ``lambdas/*-common/`` sits at the top level — and the layer build this replaced pruned less
    still, dropping only ``__pycache__``. Stated rather than quietly assumed, because the gap is
    exactly one filename wide. ``fakes.py`` is the entry worth naming: it matches none of the
    image's offender patterns, so shipping it would put a test double carrying bare ``assert``s on
    every function's import surface, entirely green.
  NOT_SHARED: The directories under ``lambdas/`` that are neither functions nor shared code, each
    with the reason it contributes nothing to ``/opt/python``. The partition guard in
    ``test_image_layout.py`` fails on any directory that is none of the three, so a new one has to
    be classified rather than silently defaulting into shared code — which is how a heuristic
    quietly starts shipping a test double to the whole fleet.
  SHARED_SUFFIX: What makes a directory shared code. A POSITIVE recognizer, and that is the whole
    point: with shared code as the default bucket, the partition is total by construction and its
    guard cannot fail — measured, on a planted ``lambdas/notes-scratch/`` that joined
    ``/opt/python`` in silence. Every shared source ends in it, and no function directory or
    exemption does.
"""

import argparse
import ast
import pathlib
import shutil

PRUNE_PREFIXES = ("test_",)
PRUNE_NAMES = ("conftest.py",)


class LayoutError(Exception):
    """A layout the tree cannot satisfy.

    Raised rather than asserted because these are build-time refusals: an ``assert`` is stripped
    under ``-O``, and every one of these checks exists to stop an image being built that is wrong
    in a way only a cold start would reveal.
    """


def defines_handler(path: pathlib.Path) -> bool:
    """Reports whether a module defines a top-level ``handler`` function.

    This is the fleet's one definition of "is a Lambda", and every harness over the fleet reads
    it here rather than restating it — two definitions are two fleets that drift.

    It is deliberately NOT how the fleet's expected SIZE is computed: `lambdas/fleet.py` derives
    that from Terraform, because a count taken from this rule would sit on both sides of its own
    comparison and a renamed handler would leave the two agreeing.

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

    Deliberately keeps ``fakes.py`` and ``__init__.py``: an ``__init__.py`` is how a package is a
    package, and a function's ``fakes.py`` ships like any other module. The zip packaging this
    reproduced pruned neither either, which is why the rule reads the way it does.

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


NOT_SHARED = {
    "docker": "the assembler itself, deleted in the layer it runs in",
    "fixtures": "test data, no importable module",
    "info": "documentation",
    "data-quality-polars": "a requirements file only; the Dockerfile installs it into site-packages",
}

NOT_SHIPPED = ("test_", "conftest.py", "fakes.py", "__init__.py")

SHARED_SUFFIX = "-common"


def shared_sources(lambdas: pathlib.Path) -> list[pathlib.Path]:
    """Every directory whose contents belong on ``/opt/python``.

    Args:
      lambdas: The ``lambdas/`` tree.

    Returns:
      The shared source directories, sorted.

    Raises:
      None.
    """
    return sorted(
        directory
        for directory in lambdas.iterdir()
        if directory.is_dir()
        and not directory.name.startswith((".", "_"))
        and directory.name.endswith(SHARED_SUFFIX)
    )


def shared_layout(repo: pathlib.Path) -> tuple[dict[str, pathlib.Path], dict[str, pathlib.Path]]:
    """Resolves what belongs on ``/opt/python``, from the tree rather than a declaration.

    **This read a JSON table until the layers were retired.** The table said which package each
    layer published and listed ``shared-space-common``'s flat modules by name, and both the image
    build and its guards read it. It is gone, and with it the whole class of failure where a
    module sits on disk, is missing from a hand-written list, never ships, and raises
    ``ModuleNotFoundError`` at a cold start behind a green suite and a green deploy. There is no
    list to be missing from now: a shared directory ships what it contains.

    What replaces the table's other job — saying which directories are shared at all — is a
    positive recognizer plus a named exemption for each directory that is neither shared nor a
    function. A directory matching none of the three fails the partition guard rather than
    defaulting into either bucket.

    Args:
      repo: The repository root.

    Returns:
      A pair of maps: package name to its source directory, and flat module name to its source
      file.

    Raises:
      LayoutError: When a shared source contributes nothing at all, or when two of them claim one
        name. An empty shared directory is not a harmless no-op — it is the shape of a source that
        has been emptied or renamed, and the layer build it replaces refused the same case for the
        same reason: an empty layer published fine and failed every function that attached it at
        cold start.
    """
    packages: dict[str, pathlib.Path] = {}
    flat: dict[str, pathlib.Path] = {}
    owners: dict[str, str] = {}

    def claim(name: str, directory: pathlib.Path) -> None:
        """Records one name against the directory publishing it, refusing a second claim.

        ``/opt/python`` is ONE namespace, so a package and a flat module compete in it exactly as
        two packages do — hence one owner map rather than one per kind.

        Args:
          name: The importable name being published.
          directory: The shared source publishing it.

        Returns:
          None.

        Raises:
          LayoutError: When another shared source already publishes that name.
        """
        if name in owners:
            where = (
                f"{directory.name} publishes {name!r} to /opt/python twice — as a package and as "
                "a module"
                if owners[name] == directory.name
                else f"{directory.name} and {owners[name]} both publish {name!r} to /opt/python"
            )
            raise LayoutError(
                f"{where}, which is one namespace. One would silently win for all 86 functions "
                "and the other would never be imported again — the same hazard task_root_layout "
                "refuses, on the other half of the search path. Rename one."
            )
        owners[name] = directory.name

    for directory in shared_sources(repo / "lambdas"):
        contributed = 0
        for child in sorted(directory.iterdir()):
            if child.is_dir() and (child / "__init__.py").is_file():
                claim(child.name, directory)
                packages[child.name] = child
                contributed += 1
            elif child.is_file() and child.suffix == ".py" and not child.name.startswith(NOT_SHIPPED):
                claim(child.stem, directory)
                flat[child.stem] = child
                contributed += 1
        if not contributed:
            raise LayoutError(
                f"{directory.name} is a shared source and contributes nothing to /opt/python. An "
                "empty one is the shape of a directory that was emptied or renamed, and it ships "
                "an image whose functions fail at cold start on an import that resolves here."
            )
    return packages, flat


def shared_roots(repo: pathlib.Path) -> list[pathlib.Path]:
    """The source directories that make up ``/opt/python``, as import roots.

    **One definition, because there were three.** Two suites needed "the shared surface a deployed
    function can import from" and each computed it as ``lambdas/*-common`` — a naming convention
    that agrees with this module's answer today by coincidence and nothing else. A shared root
    named anything else would leave the environment guard under-reporting demand, which is a false
    pass on exactly the failure it exists to catch, and the import probe granting too little.

    Derived the same way this module assembles, so the roots a test puts on ``sys.path`` are the
    directories the image actually copies.

    Args:
      repo: The repository root.

    Returns:
      The import roots, sorted and unique — a package's PARENT (so ``import cpcommon`` resolves)
      and a flat module's own directory.

    Raises:
      LayoutError: Propagated from ``shared_layout``.
    """
    packages, flat = shared_layout(repo)
    roots = {source.parent for source in packages.values()}
    roots |= {source.parent for source in flat.values()}
    return sorted(roots)


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
        f"assembled {len(packages)} shared packages, {len(flat)} flat modules, "
        f"{len(task_layout)} function modules"
    )


def main() -> None:
    """Runs the assembler from the Dockerfile.

    Args:
      None.

    Returns:
      None.

    Raises:
      LayoutError: Propagated, so a tree the assembler cannot lay out fails the BUILD rather
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
