"""The container image's layout, guarded on the source side of the artefact.

**These are the fast half of a two-sided guard, and they are not the authoritative half.** The
image itself is asserted by `.github/scripts/lambda-image-matrix.sh`, which runs the built
artefact; an absence asserted against a source tree proves nothing about an image. What lives here
is everything that can be decided without a Docker daemon — so a change to the tree that would
produce a wrong image reddens in the ordinary pytest job, minutes before the image build gets to it.

The division is deliberate and worth stating, because it is easy to put a guard on the wrong side:

* a rule about **what the assembler will do** with the tree is checkable here, since the assembler
  is an importable module and the tree is on disk;
* a rule about **what the image contains** is not, and belongs in the matrix. The two collision
  guards below exist in both places for that reason — here they fail early, there they are true.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda source tree.
  DOCKERFILE: The image recipe, read as text by the reproducibility guard.
  SHARED_SOURCES: The directories whose contents make up `/opt/python`, DECLARED here rather than
    asked of the assembler. An expectation derived from the thing under test cannot see a shrink:
    delete a shared source and both sides lose it together, and the comparison agrees.
  SHARED_PACKAGES / SHARED_FLAT_MODULES: What those directories publish, declared for the same
    reason and at the granularity that matters. Pinning the directories alone leaves the CONTENTS
    unpinned in both directions, and both were reachable: a stray package added inside a shared
    source ships to all 86 functions, and a deleted flat module vanishes — in each case the walk
    below and the assembler move together and agree. Measured on a planted
    `table-builder-common/helpers/` and a deleted `shared-space-common/teardown.py`, each of which
    left the whole suite green. Under the layer table these were a table entry and a `LayoutError`
    respectively; nothing replaced either until this pair.
  NOT_SHIPPED: What a shared source does not publish, written out here rather than imported from
    the assembler for the same reason — it is the expectation, and an expectation that moves when
    the rule moves is not one.
  MATRIX_SCRIPT: The behaviour matrix, whose fixture environment is compared against what the
    fleet actually reads at import time.
  RUNTIME_PROVIDED_ENV: Variables the Lambda runtime sets on every invocation, which the matrix
    must supply and no repository module declares. `AWS_REGION` is set by the runtime itself, and
    a module constructing a boto3 client at import fails without it — measured: `post_confirmation`
    raises `NoRegionError` in an empty environment.
  HARNESS_ONLY_ENV: Variables the matrix sets for the emulator rather than for the fleet, so they
    are excluded from the comparison below. The emulator's default invocation timeout is one
    second, which is not enough to import polars once.
  NETWORK_TOOLS: Commands whose presence in the recipe would mean the build reaches a host other
    than the package index and the base image registry.
"""

import ast
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
DOCKERFILE = LAMBDAS / "Dockerfile"
MATRIX_SCRIPT = ROOT / ".github" / "scripts" / "lambda-image-matrix.sh"

SHARED_SOURCES = (
    "archive-common",
    "control-plane-common",
    "data-quality-common",
    "file-ops-common",
    "file-send-common",
    "results-conversion-common",
    "shared-space-common",
    "table-builder-common",
    "table-share-common",
)
NOT_SHIPPED = ("test_", "conftest.py", "fakes.py", "__init__.py")

SHARED_PACKAGES = frozenset(
    {"arcommon", "cpcommon", "dqcommon", "focommon", "fscommon", "rccommon", "tbcommon", "tscommon"}
)
SHARED_FLAT_MODULES = frozenset(
    {
        "auth",
        "cache",
        "casio",
        "config",
        "membership",
        "membership_index",
        "messages",
        "notify",
        "registry",
        "teardown",
    }
)

RUNTIME_PROVIDED_ENV = frozenset({"AWS_REGION", "AWS_DEFAULT_REGION"})
HARNESS_ONLY_ENV = frozenset({"AWS_LAMBDA_FUNCTION_TIMEOUT"})
NETWORK_TOOLS = ("curl", "wget", "dnf", "yum", "microdnf", "apt-get", "apk", "git clone", "aws ")

sys.path.insert(0, str(LAMBDAS / "docker"))
import assemble
import fleet


def _publishes(directory: pathlib.Path) -> tuple[set[str], set[str]]:
    """What one shared source directory puts on `/opt/python`, walked independently.

    A second implementation of `assemble.shared_layout`'s inner rule, on purpose. The point of
    the comparison below is that two derivations agree; importing the assembler's own walk would
    make it one derivation compared with itself, which passes however wrong it is. When the two
    diverge this reddens — including when someone widens `assemble.NOT_SHIPPED` and a real module
    silently stops shipping.

    That last case is **mostly** covered elsewhere, and the measurement is worth stating rather
    than the usual over-claim: nine of the ten flat modules are imported at module scope by a
    handler outside `*-common/`, so dropping one raises `ModuleNotFoundError` in the image
    matrix's own import block. `casio` is the tenth and has no such importer. What this guard
    adds for the other nine is not coverage but LATENCY — it reddens in the pytest job, seconds
    in, rather than after a Docker build.

    Args:
      directory: One shared source directory.

    Returns:
      Its package names, and its flat module names.

    Raises:
      None.
    """
    packages = {
        child.name
        for child in directory.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }
    flat = {
        child.stem
        for child in directory.iterdir()
        if child.is_file() and child.suffix == ".py" and not child.name.startswith(NOT_SHIPPED)
    }
    return packages, flat


def test_the_declared_shared_sources_are_the_ones_the_assembler_finds() -> None:
    """The population of `/opt/python`'s sources is pinned, so a deletion cannot pass quietly.

    Everything else about the shared layout is now derived from the tree, which is what retired
    the layer table and the whole class of failure where a module on disk is missing from a list.
    A derived expectation has one blind spot the table did not: it shrinks with the thing it
    measures. Delete `archive-common` and `assemble.shared_sources` returns seven directories, an
    expectation asking it the same question returns seven, and they agree. This is the one place
    that answer is written down instead.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a declared source is missing, or an undeclared one has appeared.
    """
    for name in SHARED_SOURCES:
        assert (LAMBDAS / name).is_dir(), (
            f"{name} is declared as a shared source and is not a directory. Every function that "
            "imports from it fails at cold start on an image built from this tree."
        )
    found = {directory.name for directory in assemble.shared_sources(LAMBDAS)}
    assert found == set(SHARED_SOURCES), (
        f"the assembler finds {sorted(found)} shared sources; this file declares "
        f"{sorted(SHARED_SOURCES)}. Only found: {sorted(found - set(SHARED_SOURCES))}. Only "
        f"declared: {sorted(set(SHARED_SOURCES) - found)}."
    )


def test_the_shared_layout_is_exactly_what_the_shared_sources_publish() -> None:
    """`/opt/python` must hold every shared package and flat module, and nothing invented.

    This is the guard SPEC-214 inherited rather than deleted. It asked the layer table what the
    answer should be; the table is gone, so it asks the source directories on disk — walked here
    rather than through the assembler, so the two sides remain two.

    **Three sides, not two, and the third is what a derived expectation cannot give.** The walk
    catches the assembler computing the wrong answer from a right tree — widen
    `assemble.NOT_SHIPPED` and it reddens. It cannot catch the TREE changing, because the walk
    changes with it: add a package inside a shared source and both sides gain it, delete a flat
    module and both sides lose it, and the comparison agrees either way. So what is published is
    declared here as well. Adding shared code that the whole fleet can import is then a
    deliberate two-line change rather than a side effect of dropping a file in a directory.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the assembler, the directories and the declaration do not all agree.
    """
    packages, flat = assemble.shared_layout(ROOT)

    walked_packages: set[str] = set()
    walked_flat: set[str] = set()
    for name in SHARED_SOURCES:
        directory_packages, directory_flat = _publishes(LAMBDAS / name)
        walked_packages |= directory_packages
        walked_flat |= directory_flat

    assert walked_packages, "the shared sources publish no package — the walk is not working."
    assert walked_flat, "the shared sources publish no flat module — the walk is not working."

    assert walked_packages == set(SHARED_PACKAGES), (
        f"the shared source directories hold packages {sorted(walked_packages)}; this file "
        f"declares {sorted(SHARED_PACKAGES)}. Everything under a `*-common/` directory reaches "
        "/opt/python for all 86 functions, so a package appearing there is a change to the "
        "fleet's whole import surface and is declared here deliberately."
    )
    assert walked_flat == set(SHARED_FLAT_MODULES), (
        f"the shared source directories hold flat modules {sorted(walked_flat)}; this file "
        f"declares {sorted(SHARED_FLAT_MODULES)}. A flat module that disappears is an import "
        "failure at cold start for whoever used it; one that appears is a new top-level name "
        "every function in the fleet can resolve."
    )

    assert set(packages) == walked_packages, (
        f"the assembler puts {sorted(packages)} on /opt/python; the shared sources hold "
        f"{sorted(walked_packages)}. A package the assembler drops is a ModuleNotFoundError at "
        "the first cold start of every function that imports it."
    )
    assert set(flat) == walked_flat, (
        f"the assembler puts {sorted(flat)} on /opt/python as flat modules; the shared sources "
        f"hold {sorted(walked_flat)}."
    )


def _classifiable_directories() -> set[str]:
    """Every directory directly under `lambdas/` that git does not ignore.

    Scoped by `git check-ignore` rather than by `git ls-files`, and the difference matters in both
    directions. `lambdas/htmlcov/` is a coverage report — gitignored, but not hidden, so a name
    filter would sweep it in. A directory added in the working tree and not yet staged is the
    opposite case: `git ls-files` cannot see it, so a new plane's source would sit unclassified
    until someone ran `git add`, which is exactly when nobody is looking at the test output.

    Args:
      None.

    Returns:
      The directory names to classify.

    Raises:
      AssertionError: When git cannot answer. A failed command returns no output, and no output
        subtracts to nothing — a broken read would otherwise leave every directory looking clean.
    """
    on_disk = sorted(
        directory.name
        for directory in LAMBDAS.iterdir()
        if directory.is_dir() and not directory.name.startswith((".", "_"))
    )
    assert len(on_disk) > 50, (
        f"only {len(on_disk)} directories found under lambdas/ — the fleet is 86 functions plus "
        "its shared sources, so this walk has stopped working and the partition below would be "
        "over almost nothing."
    )

    git = shutil.which("git") or "git"
    finished = subprocess.run(  # noqa: S603 — resolved binary, arguments built here
        [git, "check-ignore", "--stdin"],
        cwd=ROOT,
        input="\n".join(f"lambdas/{name}" for name in on_disk),
        capture_output=True,
        text=True,
        check=False,
    )
    assert finished.returncode in (0, 1), (
        f"`git check-ignore` exited {finished.returncode}: {finished.stderr.strip()!r}. It reports "
        "0 when something is ignored and 1 when nothing is; anything else means the read failed, "
        "and a failed read here reports every directory as classifiable."
    )
    ignored = {
        line.split("/", 1)[1] for line in finished.stdout.splitlines() if line.startswith("lambdas/")
    }
    return set(on_disk) - ignored


def test_every_directory_under_lambdas_is_a_function_shared_code_or_named_exempt() -> None:
    """The partition has to be total, and it is not total by construction.

    The assembler decides what a directory is by asking two positive questions — does it hold a
    module defining a top-level `handler`, and does its name end in `-common` — and everything
    else is named in `assemble.NOT_SHARED` with a reason. Nothing is a default, and that is the
    whole design: an earlier draft made shared code the default bucket, which made the partition
    total by construction and this guard unable to fail. Measured on a planted
    `lambdas/notes-scratch/`, which joined `/opt/python` in silence.

    So a new directory has to be classified before it can ship. It is a function, or it is shared
    code every function in the fleet can import, or someone says in one line why it is neither.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a directory is none of the three, or an exemption names one that has
        gone.
    """
    directories = _classifiable_directories()
    functions = set(assemble.function_directories(LAMBDAS))
    shared = {directory.name for directory in assemble.shared_sources(LAMBDAS)}
    exempt = set(assemble.NOT_SHARED)

    assert functions and shared, (
        f"{len(functions)} function directories and {len(shared)} shared sources resolved. With "
        "either side empty the subtraction below reports every directory as unclassified or none "
        "of them, and neither answer is a measurement."
    )

    unclassified = sorted(directories - functions - shared - exempt)
    assert not unclassified, (
        f"{unclassified} under lambdas/ are neither a function directory, a shared source, nor "
        f"named in assemble.NOT_SHARED. A directory the assembler cannot classify is one whose "
        "contents reach the image, or fail to, by accident — add a handler, rename it to "
        f"*{assemble.SHARED_SUFFIX}, or name it in NOT_SHARED with its reason."
    )

    vanished = sorted(exempt - directories)
    assert not vanished, (
        f"{vanished} are named in assemble.NOT_SHARED and are not directories under lambdas/. An "
        "exemption for something that is gone reads as coverage and provides none — and if the "
        "directory was renamed rather than deleted, the new name is now unclassified and this "
        "test would have said so."
    )

    contradicted = sorted(exempt & (functions | shared))
    assert not contradicted, (
        f"{contradicted} are named in assemble.NOT_SHARED and are also a function directory or a "
        "shared source. The partition has to be DISJOINT as well as total: a subtraction is "
        "satisfied by an over-wide exemption exactly as it is by a correct one, so an entry "
        "claiming a live shared source contributes nothing would pass while documenting the "
        "opposite of what the assembler does with it."
    )


def test_no_two_function_directories_collide_in_the_task_root() -> None:
    """Every function shares one task root in the image, which no zip ever did.

    Two directories contributing the same relative path would leave whichever was copied second,
    and every function in the fleet would import that one. Measured empty today; the image is what
    makes it possible, and nothing else in this repository would notice.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: Propagated from the resolver, which refuses a duplicate destination.
    """
    layout = assemble.task_root_layout(ROOT)
    assert len(layout) > 100, (
        f"only {len(layout)} modules resolved for the task root — the sweep that finds them has "
        "stopped working, and a collision check over almost nothing cannot fail."
    )


def test_nothing_in_the_task_root_shadows_a_shared_module() -> None:
    """The task root precedes `/opt/python` on the runtime's path, so a shared name loses.

    A function module named `config.py` would shadow the shared-space layer's `config` for every
    verb that imports it — silently, at cold start, with the wrong module. The names at risk are
    exactly the generic ones the flat layer already uses.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a task-root top-level name is also a shared name.
    """
    packages, flat = assemble.shared_layout(ROOT)
    shared = set(packages) | set(flat)
    assert shared, "no shared names resolved — this comparison would be vacuous."

    top_level = {
        relative.parts[0][:-3] if len(relative.parts) == 1 else relative.parts[0]
        for relative in assemble.task_root_layout(ROOT)
    }
    collisions = sorted(shared & top_level)
    assert not collisions, (
        f"{collisions} exist both in the task root and on /opt/python. The task root wins for "
        "every function in the fleet, so the shared copy would never be imported again."
    )


def test_the_function_definition_matches_the_deploy_matrix() -> None:
    """The assembler and the deploy matrix must agree on what a Lambda is.

    Two sweeps over one fleet that disagree is how a function silently stops being covered by one
    of them. They share a definition — a directory holding a top-level module that defines a
    top-level `handler` — and this is what pins that they still do.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two derivations differ.
    """
    declared = set(fleet.function_names(ROOT))
    found = set(assemble.function_directories(LAMBDAS))
    assert found == declared, (
        f"the assembler finds {len(found)} function directories and Terraform declares "
        f"{len(declared)}. Only in the assembler: {sorted(found - declared)}. Only in Terraform: "
        f"{sorted(declared - found)}."
    )


def test_the_dockerfile_pins_its_base_by_digest() -> None:
    """A mutable tag would make "the sha identifies what is running" false.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the base is not digest-pinned.
    """
    bases = re.findall(r"^FROM\s+(\S+)", DOCKERFILE.read_text(), re.MULTILINE)
    assert bases, "no FROM found in the Dockerfile."
    for base in bases:
        assert "@sha256:" in base, (
            f"{base} is pinned by tag, not by digest. A rebuild of an unchanged commit could then "
            "produce a different image, which is what the commit-sha tagging exists to deny."
        )


def test_the_build_reaches_no_host_but_the_index_and_the_base() -> None:
    """The build must be reproducible from a clean checkout with only two network dependencies.

    Satisfied by construction rather than by luck, and this is what keeps it that way: a `curl`
    or a package-manager install added later would pass every other gate in this repository.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the recipe reaches a third host.
    """
    recipe = DOCKERFILE.read_text()
    body = "\n".join(
        line for line in recipe.splitlines() if not line.lstrip().startswith("#")
    )
    assert "RUN" in body, "no RUN instruction found — this check is reading the wrong file."
    found = [tool for tool in NETWORK_TOOLS if tool in body]
    assert not found, (
        f"the build invokes {found}, which reaches a host beyond the package index and the base "
        "image registry. That makes the build unreproducible from a clean checkout."
    )


def _module_scope_required_env() -> dict[str, str]:
    """Finds every fail-fast environment read that runs at IMPORT time across `lambdas/`.

    Module scope only: a visitor that descends into a `def` body reports reads that run on some
    later branch, which is a different question and a much longer list. Measured — the naive
    version reports four names where one is actually resolved at import, and the container agrees
    with the strict one.

    Args:
      None.

    Returns:
      Variable name to the module that reads it.

    Raises:
      None.
    """

    class ModuleScope(ast.NodeVisitor):
        """Walks module-scope statements without entering a function or class body."""

        def __init__(self) -> None:
            """Starts with no hits.

            Args:
              None.

            Returns:
              None.

            Raises:
              None.
            """
            self.hits: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            """Refuses to descend into a function body.

            Args:
              node: The function definition.

            Returns:
              None.

            Raises:
              None.
            """

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]
        visit_ClassDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            """Records a fail-fast read with a literal name.

            Args:
              node: The call.

            Returns:
              None.

            Raises:
              None.
            """
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else None
            )
            if name in ("require", "_require") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    self.hits.append(first.value)
            self.generic_visit(node)

    found: dict[str, str] = {}
    for path in sorted(LAMBDAS.rglob("*.py")):
        relative = path.relative_to(LAMBDAS)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if path.name.startswith("test_") or path.name in ("conftest.py", "fakes.py"):
            continue
        visitor = ModuleScope()
        for statement in ast.parse(path.read_text()).body:
            visitor.visit(statement)
        for hit in visitor.hits:
            found.setdefault(hit, str(relative))
    return found


def test_the_matrix_supplies_exactly_the_environment_the_fleet_reads_at_import() -> None:
    """The matrix's fixture environment must match what the fleet demands at import.

    The matrix cannot import a module that resolves a required variable at module scope, and
    supplying nothing would mean testing a state that never occurs — a deployed function always
    has these. The list lives in the shell script because that script runs before any Python is
    available to it; this is the assertion that keeps the two honest, the same split
    `spa-image-matrix.sh` uses for its own required-environment block.

    A new module-scope `require` therefore reddens here rather than in the image build, which is
    the cheaper place to find out.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two sets differ.
    """
    script = MATRIX_SCRIPT.read_text()
    block = re.search(r"FIXTURE_ENV=\((.*?)\n\)", script, re.DOTALL)
    assert block, "no FIXTURE_ENV block found in the matrix script."
    supplied = set(re.findall(r"-e\s+([A-Z_][A-Z0-9_]*)=", block.group(1)))
    assert supplied, "the FIXTURE_ENV block supplies nothing — this comparison would be vacuous."

    demanded = _module_scope_required_env()
    assert demanded, (
        "no module-scope fail-fast read found anywhere in lambdas/. The sweep has stopped "
        "working, and an empty demand set matches any fixture."
    )

    supplied -= HARNESS_ONLY_ENV
    assert supplied == set(demanded) | RUNTIME_PROVIDED_ENV, (
        f"the matrix supplies {sorted(supplied)}; the fleet reads {sorted(demanded)} at import "
        f"and the runtime provides {sorted(RUNTIME_PROVIDED_ENV)}. A name the fleet demands and "
        "the matrix does not supply fails every import in that plane; one the matrix supplies "
        "and nothing reads is a fixture nobody removed."
    )


@pytest.mark.parametrize("name", sorted(_module_scope_required_env()))
def test_each_import_time_variable_is_read_by_a_module_that_exists(name: str) -> None:
    """Every name the sweep found must trace back to a real module.

    Args:
      name: One variable name the sweep reported.

    Returns:
      None.

    Raises:
      AssertionError: When the module it was found in has gone.
    """
    module = _module_scope_required_env()[name]
    assert (LAMBDAS / module).is_file(), f"{name} was reported from {module}, which is missing"


def _tree(
    tmp_path: pathlib.Path,
    functions: dict[str, dict],
    shared: dict[str, dict] | None = None,
) -> pathlib.Path:
    """Builds a miniature repository the assembler can be pointed at.

    Built under ``tmp_path`` and never under ``lambdas/``, deliberately. A fixture module written
    into the real tree would be copied into the image by the assembler, would be reported by the
    sweep in ``test_flat_layer_imports`` that it is meant to validate, and would be classified by
    the partition guard above as a directory nobody named.

    Args:
      tmp_path: pytest's per-test temporary directory.
      functions: Directory name to a map of relative path to file contents.
      shared: Shared source directory name to the same, for the refusals that need one. Names
        here have to end in the assembler's shared suffix or they are not shared sources at all,
        which would make a refusal test pass for the wrong reason.

    Returns:
      The repository root of the miniature tree.

    Raises:
      None.
    """
    for name, files in {**functions, **(shared or {})}.items():
        directory = tmp_path / "lambdas" / name
        directory.mkdir(parents=True, exist_ok=True)
        for relative, contents in files.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
    return tmp_path


HANDLER = "def handler(event, context):\n    return None\n"


def test_the_assembler_refuses_two_directories_contributing_one_path(
    tmp_path: pathlib.Path,
) -> None:
    """The collision refusal must fire, and must name both owners.

    The guard above asserts the real tree has no collision, which is true and would stay true if
    the refusal had been deleted. This is what proves the refusal is reachable at all.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(
        tmp_path,
        {
            "alpha": {"alpha.py": HANDLER, "shared/util.py": "X = 1\n"},
            "beta": {"beta.py": HANDLER, "shared/util.py": "X = 2\n"},
        },
    )
    with pytest.raises(assemble.LayoutError) as raised:
        assemble.task_root_layout(repo)
    message = str(raised.value)
    assert "alpha" in message and "beta" in message, (
        f"the collision refusal names neither owner: {message}"
    )


def test_the_assembler_refuses_a_shared_source_that_publishes_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """A shared source contributing nothing must fail the BUILD, and must be named.

    **This replaces the two refusals the layer table used to own.** Those fired when the table
    named a package or a module that was not on disk, and the table is gone: there is no name to
    be wrong any more, because a shared directory now ships what it contains. What is left is the
    case that survived the change — a directory that is a shared source and publishes nothing —
    which is the shape of one that has been emptied or renamed. The layer build refused it for
    the same reason: an empty layer published fine and failed every function that attached it.

    The fixture holds a healthy shared source beside the broken one, so a refusal that fired for
    any other reason would name the wrong directory and this would still catch it.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(
        tmp_path,
        {"alpha": {"alpha.py": HANDLER}},
        shared={
            "good-common": {"goodpkg/__init__.py": "", "goodpkg/thing.py": "X = 1\n"},
            "ghost-common": {"conftest.py": "", "test_ghost.py": "", "__init__.py": ""},
        },
    )
    with pytest.raises(assemble.LayoutError) as raised:
        assemble.shared_layout(repo)
    message = str(raised.value)
    assert "ghost-common" in message and "contributes nothing" in message, (
        f"the refusal does not name the empty shared source and its reason: {message}"
    )
    assert "good-common" not in message, (
        f"the refusal names the healthy shared source: {message}. It fired for something other "
        "than the empty directory, so this test would pass with the guard it is meant to prove "
        "removed."
    )


def test_the_assembler_refuses_two_shared_sources_publishing_one_name(
    tmp_path: pathlib.Path,
) -> None:
    """`/opt/python` is one namespace, so a repeated name is a silent win, not a collision.

    **This refusal is new with the layer table's retirement, and it is new because the hazard is.**
    The table published a named package per entry and one explicit module list, so a `.py` dropped
    into another shared directory reached nothing at all. Now every `*-common/` directory publishes
    what it holds, and two publishing one name resolve by directory sort order: the loser never
    ships and every function in the fleet imports the winner. Measured before this guard existed —
    a planted `table-builder-common/config.py` shadowed `shared-space-common`'s `config` for the
    whole fleet, the flat NAME set was unchanged so every layout guard compared equal, and the
    suite stayed green at 2385 passed.

    `task_root_layout` has refused the same hazard on the other half of the search path since the
    image was built. This is its `/opt/python` half.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(
        tmp_path,
        {"alpha": {"alpha.py": HANDLER}},
        shared={
            "first-common": {"config.py": "X = 1\n"},
            "second-common": {"config.py": "X = 2\n"},
        },
    )
    with pytest.raises(assemble.LayoutError) as raised:
        assemble.shared_layout(repo)
    message = str(raised.value)
    assert "first-common" in message and "second-common" in message, (
        f"the refusal names fewer than both owners: {message}. Which directories collide is the "
        "only thing the reader needs and the only thing they cannot work out from the name."
    )
    assert "config" in message, f"the refusal does not name the colliding name: {message}"


def test_a_package_and_a_flat_module_cannot_share_a_name(tmp_path: pathlib.Path) -> None:
    """The two kinds compete in the same namespace, so the guard cannot be per-kind.

    A package directory and a top-level module publishing one name both land in `/opt/python`, and
    the package wins the import. Keeping one owner map rather than one per kind is what makes this
    reachable; two maps would let this pair through while refusing each kind against itself.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(
        tmp_path,
        {"alpha": {"alpha.py": HANDLER}},
        shared={
            "first-common": {"shared/__init__.py": "", "shared/thing.py": "X = 1\n"},
            "second-common": {"shared.py": "X = 2\n"},
        },
    )
    with pytest.raises(assemble.LayoutError) as raised:
        assemble.shared_layout(repo)
    message = str(raised.value)
    assert "both publish" in message, (
        f"a LayoutError was raised, but not the collision one: {message}. `shared_layout` has two "
        "refusals and the other one — an empty shared source — says 'is a shared source and "
        "contributes nothing', so matching on a fixture name or on the word 'shared' catches "
        "either. Measured: with every flat module suppressed this test passed while its sibling "
        "correctly failed."
    )
    assert "first-common" in message and "second-common" in message, (
        f"the refusal names fewer than both owners: {message}"
    )
