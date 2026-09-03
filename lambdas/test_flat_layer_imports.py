"""No function outside the shared-space plane may import its flat top-level modules.

**The container image made the fleet's import surface strictly larger, and this sweep is what
keeps that from mattering — the packaging does not.** A function used to import only the layers
attached to it, so a table decided the surface. In one image every function can import everything
on `/opt/python`, including `shared-space-common`'s flat modules, whose names — `config`, `auth`,
`registry`, `cache`, `notify`, `messages`, `membership`, `membership_index`, `casio`, `teardown` —
are generic enough to be imported from another plane by accident and would resolve.

Stated plainly rather than dressed as parity: the image gives every function a wider surface than
its zip had. Nothing about that is fixed by copying files differently, and the honest guard is a
sweep over what the code actually imports.

**Attribute-style usage counts.** `import registry` followed by `registry.load()` is a consumer,
and a scan that only looks at `from x import y` undercounts them — this repository has measured
that undercount before.

**The guarded names are resolved, not written out.** Ten today; nine when this spec was drafted,
because `membership_index` landed after it was written. A list in this file would have been wrong
on the day it was committed. They came from `.github/lambda-layers.json` until the layers were
retired, and now come from the assembler that lays `/opt/python` out — the same answer from the
one place that decides it. `test_image_layout.py` is what holds that answer honest against the
source directories on disk, so this module consumes it rather than deriving it a third time.

Attributes:
  ROOT: The repository root.
  LAMBDAS: The Lambda source tree.
  EXEMPT_DIRECTORIES: The function directories allowed to import them, by EXACT path — the
    shared-space plane's own verbs, which is the plane the modules belong to. Exact paths rather
    than a prefix so a new `shared-space-`-named directory does not inherit the exemption by
    being called the right thing.

The swept population is the FUNCTION directories, which is not the same as every directory under
`lambdas/`. `shared-space-common` is the flat modules' own source, and they import each other by
design; sweeping it would report four offenders and invite the wrong repair — adding a
non-function directory to the exemption list, which would widen the sweep's blind spot rather
than narrow it. The definition of a function directory is `assemble.function_directories`, shared
with the image assembler and every other sweep over the fleet so they cannot drift into covering
different sets.
"""

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"

sys.path.insert(0, str(LAMBDAS / "docker"))
import assemble

EXEMPT_DIRECTORIES = (
    "lambdas/shared-space-acknowledge-membership",
    "lambdas/shared-space-add-members",
    "lambdas/shared-space-backfill-ever-active",
    "lambdas/shared-space-create",
    "lambdas/shared-space-delete",
    "lambdas/shared-space-forget",
    "lambdas/shared-space-leave",
    "lambdas/shared-space-notify-failure",
    "lambdas/shared-space-remove-members",
    "lambdas/shared-space-transfer-ownership",
    "lambdas/shared-space-validate",
)


def guarded_names() -> set[str]:
    """The flat top-level module names the shared sources publish.

    Args:
      None.

    Returns:
      Every module name that lands on `/opt/python` without a package around it.

    Raises:
      AssertionError: When none resolve, which would make the sweep vacuous.
    """
    _, flat = assemble.shared_layout(ROOT)
    names = set(flat)
    assert names, (
        "no flat module resolves onto /opt/python. A sweep with an empty guarded set matches "
        "nothing and passes over any import at all."
    )
    return names


def imported_top_level_names(source: str) -> set[str]:
    """Collects every top-level name a module imports, in both spellings.

    `import x` and `import x.y` both make `x` a consumer, and so does `from x import y`. The
    attribute-style spelling is the one a submodule-path scan misses, and missing it undercounts
    consumers rather than overcounting them — the direction that lets a real import through.

    Relative imports are excluded: `from . import registry` names a sibling inside a package, not
    the flat layer's module.

    Args:
      source: A module's text.

    Returns:
      The top-level names it imports.

    Raises:
      SyntaxError: When the source does not parse.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def offenders(lambdas: pathlib.Path, exempt: tuple[str, ...]) -> dict[str, set[str]]:
    """Finds every non-exempt function directory importing a guarded name.

    Args:
      lambdas: The Lambda source tree.
      exempt: Repository-relative directory paths allowed to import them.

    Returns:
      Directory name to the guarded names it imports. Empty when the rule holds.

    Raises:
      SyntaxError: Propagated, so an unparseable module is a failure rather than a skip.
    """
    guarded = guarded_names()
    exempt_names = {pathlib.PurePath(path).name for path in exempt}
    functions = assemble.function_directories(lambdas)
    assert functions, (
        "no function directories found. A sweep over an empty population reports no offenders "
        "and passes, which is the failure this whole module is a guard against."
    )
    found: dict[str, set[str]] = {}
    for name in functions:
        directory = lambdas / name
        if name in exempt_names:
            continue
        for path in sorted(directory.rglob("*.py")):
            relative = path.relative_to(directory)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            hits = imported_top_level_names(path.read_text()) & guarded
            if hits:
                found.setdefault(directory.name, set()).update(hits)
    return found


def test_no_function_outside_the_shared_space_plane_imports_a_flat_module() -> None:
    """The rule itself.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a non-exempt directory imports a guarded name.
    """
    found = offenders(LAMBDAS, EXEMPT_DIRECTORIES)
    assert not found, (
        "these directories import a shared-space flat module and are not part of that plane: "
        + "; ".join(f"{name} imports {sorted(names)}" for name, names in sorted(found.items()))
        + ". In the container image every function can resolve those names, so an accidental "
        "import succeeds instead of failing at a cold start — which is worse, not better."
    )


@pytest.mark.parametrize("path", EXEMPT_DIRECTORIES)
def test_every_exempted_path_exists(path: str) -> None:
    """An exemption naming a directory that has gone is an exemption guarding nothing.

    It also silently widens the sweep's blind spot if the directory is renamed rather than
    deleted, because the new name is no longer exempt but the old entry still reads as coverage.

    Args:
      path: One exempted repository-relative directory path.

    Returns:
      None.

    Raises:
      AssertionError: When the path does not exist.
    """
    assert (ROOT / path).is_dir(), f"{path} is exempted from the sweep but does not exist"


def test_the_exemption_list_is_not_wider_than_the_plane() -> None:
    """Every exempted directory must actually import a guarded name.

    An exemption that nothing needs is a hole nobody is watching, and it is the shape an
    exemption list rots into: a directory stops importing the module, keeps its exemption, and
    the next import anyone adds to it goes unnoticed.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When an exempted directory imports none of the guarded names.
    """
    unused = [
        path
        for path in EXEMPT_DIRECTORIES
        if not offenders(LAMBDAS, tuple(p for p in EXEMPT_DIRECTORIES if p != path)).get(
            pathlib.PurePath(path).name
        )
    ]
    assert not unused, (
        f"{unused} are exempted but import no shared-space flat module. An exemption nothing "
        "needs is a directory the sweep has stopped watching for no reason."
    )


def test_the_sweep_reports_a_planted_offender() -> None:
    """The positive control: prove the sweep can fail before trusting that it passes.

    `assert not found` is true of an empty dict, so a sweep that collected nothing — a wrong
    root, a filter that excludes everything, a guarded set read from a file that moved — passes
    exactly like a clean tree. The other tests here cannot tell those apart.

    **The fixture is synthesised, never written to disk.** A module planted under `lambdas/` would
    be copied into the image by the assembler, would be reported by the sweep it is validating,
    and would show up in a diff this spec promises leaves `lambdas/**/*.py` unchanged.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the collector reports nothing for a module that plainly offends.
    """
    guarded = sorted(guarded_names())
    plain = f"import {guarded[0]}\n"
    attribute_style = f"import {guarded[0]}\n\n\ndef go():\n    return {guarded[0]}.thing()\n"
    from_style = f"from {guarded[0]} import thing\n"

    for label, source in (
        ("a bare import", plain),
        ("attribute-style usage", attribute_style),
        ("a from-import", from_style),
    ):
        assert imported_top_level_names(source) & guarded_names(), (
            f"the collector does not see {label} of {guarded[0]!r}. Every 'no offenders' result "
            "in this module is vacuous until it does."
        )

    assert not imported_top_level_names("from . import registry\n") & guarded_names(), (
        "a relative import is being counted as a flat-layer import. That would report a package's "
        "own sibling as an offender and make the exemption list grow for the wrong reason."
    )
