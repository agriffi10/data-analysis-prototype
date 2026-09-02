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
  LAYER_TABLE: The declaration of what shared code exists, which the assembler reads.
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
import json
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
DOCKERFILE = LAMBDAS / "Dockerfile"
LAYER_TABLE = ROOT / ".github" / "lambda-layers.json"
MATRIX_SCRIPT = ROOT / ".github" / "scripts" / "lambda-image-matrix.sh"

RUNTIME_PROVIDED_ENV = frozenset({"AWS_REGION", "AWS_DEFAULT_REGION"})
HARNESS_ONLY_ENV = frozenset({"AWS_LAMBDA_FUNCTION_TIMEOUT"})
NETWORK_TOOLS = ("curl", "wget", "dnf", "yum", "microdnf", "apt-get", "apk", "git clone", "aws ")

sys.path.insert(0, str(LAMBDAS / "docker"))
import assemble
import fleet


def _table() -> list[dict]:
    """Reads the layer table.

    Args:
      None.

    Returns:
      Its entries.

    Raises:
      None.
    """
    return json.loads(LAYER_TABLE.read_text())


def test_the_shared_layout_is_exactly_what_the_layer_table_declares() -> None:
    """`/opt/python` must hold every layer package and flat module, and nothing invented.

    This is the guard SPEC-214 inherits rather than deletes: when the layer table goes, this
    expectation repoints at the layer source directories. It is named here so the coupling is
    visible from both ends.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the assembler and the table disagree.
    """
    packages, flat = assemble.shared_layout(ROOT)
    expected_packages = {pathlib.Path(e["package"]).name for e in _table() if e.get("package")}
    expected_flat = {m for e in _table() if e.get("sourceDir") for m in e.get("modules", [])}

    assert expected_packages, "the layer table declares no packages — it is not being read."
    assert expected_flat, "the layer table declares no flat modules — it is not being read."
    assert set(packages) == expected_packages
    assert set(flat) == expected_flat


#: Layer source directories packaged by an EXPLICIT per-file module list (a ``modules`` key in the
#: layer table), mapped to nothing — the set is what matters. Every other layer copies a whole
#: package directory, so a new module there ships automatically and there is no list to drift from.
EXPLICIT_COPY_LISTS = {"shared-space-common"}

#: Files under a layer source directory that are deliberately NOT shipped.
_NOT_SHIPPED = ("test_", "conftest.py", "fakes.py", "__init__.py")


def _copy_list(directory: str) -> set[str]:
    """The module names the layer table lists for one source directory.

    Args:
      directory: The layer source directory's name.

    Returns:
      The listed module names.

    Raises:
      AssertionError: When the table has no entry for it, or the entry names no modules — either
        way the comparison below would have nothing to compare and would pass.
    """
    for entry in _table():
        if entry.get("sourceDir", "").endswith(directory):
            listed = set(entry.get("modules", []))
            assert listed, f"the layer entry for {directory} names no modules"
            return listed
    raise AssertionError(f"no layer entry with a sourceDir for {directory} in {LAYER_TABLE.name}")


def test_the_layer_copy_list_matches_the_layer_directory() -> None:
    """The explicit module list and the directory it is built from agree, both directions.

    **This is the guard SPEC-137 cost this project nine days of broken sign-ups to learn.** All ten
    flat modules ship behind ONE table entry, so nothing that reasons about the ENTRY can see
    whether a given module reached `/opt/python`: a module added to the directory and left out of
    the list simply never ships, and the function importing it raises `ModuleNotFoundError` at cold
    start, after a green suite and a green deploy.

    **It lives here because its previous home was deleted a PR too early.** It was in
    `test_deploy_matrix.py`, which went when the FUNCTION table did — and the reasoning that
    retired it ("there is no list any more, the assembler copies the directory") is true of where
    this spec ENDS, not of here: `assemble.shared_layout` still reads this list. Measured on the
    commit that dropped it: a module planted on disk and absent from the list passed all 2,388
    tests, and importing it lazily from a verb passed the image's behaviour matrix too. The guard
    goes when the list does, and not before.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the list and the directory disagree in either direction.
    """
    for directory in sorted(EXPLICIT_COPY_LISTS):
        listed = _copy_list(directory)
        on_disk = {
            path.stem
            for path in (LAMBDAS / directory).glob("*.py")
            if not path.name.startswith(_NOT_SHIPPED)
        }
        assert listed == on_disk, (
            f"{directory}'s copy list and its directory disagree: only in the list "
            f"{sorted(listed - on_disk)}, only on disk {sorted(on_disk - listed)}. A module on "
            "disk and not in the list never reaches /opt/python, and the function importing it "
            "raises ModuleNotFoundError at cold start"
        )


def test_no_unchecked_explicit_copy_list_was_added() -> None:
    """A second layer built from a hand-written list would be exempt by omission.

    `EXPLICIT_COPY_LISTS` is what the test above iterates, so a new `modules` entry that nobody
    adds here ships with no agreement check at all — the same silent exemption that cost this
    fleet an outage once already.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a layer names a module list and is not declared here.
    """
    declared = {
        pathlib.Path(entry["sourceDir"]).name for entry in _table() if entry.get("modules")
    }
    assert declared == EXPLICIT_COPY_LISTS, (
        f"layers built from an explicit module list: {sorted(declared)}, declared here: "
        f"{sorted(EXPLICIT_COPY_LISTS)}. An undeclared one is exempt from the agreement check "
        "above, which is the whole failure this pair exists to prevent"
    )


def test_every_declared_layer_source_exists() -> None:
    """A table entry naming a source that is gone must fail here, not at a cold start.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: Propagated from the resolver, which checks each source as it reads it.
    """
    packages, flat = assemble.shared_layout(ROOT)
    for name, source in {**packages, **flat}.items():
        assert source.exists(), f"{name} resolves to {source}, which does not exist"


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


def _tree(tmp_path: pathlib.Path, layers: list[dict], functions: dict[str, dict]) -> pathlib.Path:
    """Builds a miniature repository the assembler can be pointed at.

    Built under ``tmp_path`` and never under ``lambdas/``, deliberately. A fixture module written
    into the real tree would be copied into the image by the assembler, would be reported by the
    sweep in ``test_flat_layer_imports`` that it is meant to validate, and would show up in a diff
    this spec promises leaves ``lambdas/**/*.py`` unchanged.

    Args:
      tmp_path: pytest's per-test temporary directory.
      layers: Layer-table entries to write.
      functions: Directory name to a map of relative path to file contents.

    Returns:
      The repository root of the miniature tree.

    Raises:
      None.
    """
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "lambda-layers.json").write_text(json.dumps(layers))
    for name, files in functions.items():
        for relative, contents in files.items():
            path = tmp_path / "lambdas" / name / relative
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
        [],
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


def test_the_assembler_refuses_a_layer_package_that_is_not_there(
    tmp_path: pathlib.Path,
) -> None:
    """A table entry naming a source that has gone must fail the BUILD.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(tmp_path, [{"flag": "ghost", "package": "lambdas/ghost-common/ghost"}], {})
    with pytest.raises(assemble.LayoutError, match="ghost"):
        assemble.shared_layout(repo)


def test_the_assembler_refuses_a_flat_module_that_is_not_there(
    tmp_path: pathlib.Path,
) -> None:
    """The same for the one layer packaged by an explicit module list.

    That list is the single thing in the layer build that can silently drift from its source
    directory, which is why it is refused rather than skipped.

    Args:
      tmp_path: pytest's per-test temporary directory.

    Returns:
      None.

    Raises:
      None.
    """
    repo = _tree(
        tmp_path,
        [{"flag": "layer", "sourceDir": "lambdas/flat-common", "modules": ["absent"]}],
        {},
    )
    with pytest.raises(assemble.LayoutError, match="absent"):
        assemble.shared_layout(repo)

