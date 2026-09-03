"""Control for the shared-layer snapshot fixture in this tree's ``conftest.py``.

That fixture snapshots and restores the module namespaces every suite globally patches, over two
populations matched differently: the LAYER packages by import name, and ``shared-space-common``'s
FLAT modules by the directory their file sits in. The name half is hard to get wrong. The path half
was wrong from the day it was written and stayed wrong silently — it compared the normalised layer
directory as a SUBSTRING of ``__file__``, which is False for every flat module, because every
shared-space suite puts the layer on ``sys.path`` through a literal ``..`` and the imported module's
``__file__`` keeps that segment. Nothing reddened: an empty snapshot restores nothing, and a fixture
with nothing to restore behaves identically to one that never found anything.

So the job here is to prove the collector COLLECTS, and to prove it collects the whole population,
before anything is asserted about what it restores. Two review frames found the same class of hole
in earlier drafts of this file — first no control over the path half, then none over the name half
or the population — each time with the full suite green. The answer to a defect class that keeps
recurring is structure rather than another hand-picked check, so nothing here is hand-picked: the
population is PINNED below and every assertion is derived from it, in the way
``test_membership_index.py`` pins its writer list. A module joining or leaving the layer reddens
this file, which is the point; update the pin deliberately.

Both populations are pinned, because the fixture has two and only one of them was ever broken. The
LAYER-PACKAGE half works and is the larger by far — 103 of the 113 modules snapshotted at this
file's own setup — and it had no control at all: six of its eight prefixes could be deleted with
this file green AND the whole suite green, ``apicommon`` among them, which is the entry the
conftest's own comment argues hardest for. Controlling the half that was broken and not the half
that was merely uncontrolled would have left the same rule half-applied.

Known and NOT closed here, so a later reader does not mistake this file for complete. The snapshot
is ``dict(vars(module))``, which copies bindings: a module-level dict or list mutated IN PLACE is
the same object in the snapshot and survives the restore. Two such caches exist in the layers and
both are handled by a purpose-built fixture in ``lambdas/api/conftest.py`` rather than by this
mechanism. Adding a ``.py`` file to the layer reddens the pin below with an instruction; adding a
PACKAGE to it does not, and is silently uncovered, because the population is built from a listing of
``.py`` files and a package's top-level name is not a layer prefix either.

Attributes:
  EXPECTED_FLAT_MODULES: The flat modules ``shared-space-common`` publishes, pinned as a literal
    ON PURPOSE. Deriving it from the conftest's own constant would agree with a population that had
    silently shrunk, and re-deriving it from a directory listing would be the conftest's filter rule
    written a second time, wrong in one copy the day either moves.
  EXPECTED_LAYER_PREFIXES: The layer packages the fixture matches by import name, pinned for the
    same reason and read back the same way. Not derived from the ``*-common`` directories on disk:
    ``apicommon`` ships inside the API function's own package rather than as a layer directory, and
    ``dqcommon``'s directory is not among the ones the conftest puts on ``sys.path``, so a
    directory-derived expectation would be wrong in two places at once.
  LAYER: The layer directory, normalised.
  LAYER_AS_A_SUITE_SPELLS_IT: The same directory reached by going UP and back down, which is the
    shape every shared-space suite puts on ``sys.path``. Where the pardir sits is load-bearing and
    easy to get wrong: ``shared-space-common/../shared-space-common`` resolves to the same place but
    still contains the normalised directory as a substring, so a path built that way lets the broken
    comparison pass and this whole file confirms nothing. The pardir has to sit OUTSIDE the layer's
    own path, as a sibling suite's does. Derived from this directory rather than named after a
    suite, so renaming a suite cannot quietly break the import.
  FOREIGN_DIR: A directory inside the Lambda tree that is NOT the layer, for the impostor the
    matcher has to reject. It need not contain the file named after it — realpath normalises a path
    that does not exist.
  ROOT_CONFTEST: Path of the conftest under test, which is also the name pytest registers it under.
  SENTINEL: The attribute name the mutating test ADDS, to every snapshotted module except the one
    it rebinds. Kept off that one deliberately: a restore conditioned on a key having been added
    puts back nothing for a test that only rebinds, which is what almost every suite here does, and
    a module carrying both mutations cannot tell the two apart.
  ORIGINAL_VALID_ACTIONS: The action vocabulary as imported, captured at collection time and so
    before any test could have moved it.
  MUTATED_VALID_ACTIONS: The value the mutating test writes over it.
"""

import os
import sys
import types

EXPECTED_LAYER_PREFIXES = frozenset(
    {
        "apicommon",
        "arcommon",
        "cpcommon",
        "dqcommon",
        "focommon",
        "fscommon",
        "tbcommon",
        "tscommon",
    }
)

EXPECTED_FLAT_MODULES = frozenset(
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

HERE = os.path.dirname(os.path.abspath(__file__))
LAYER = os.path.join(HERE, "shared-space-common")
LAYER_AS_A_SUITE_SPELLS_IT = os.path.join(
    HERE, os.pardir, os.path.basename(HERE), "shared-space-common"
)
FOREIGN_DIR = os.path.join(HERE, "control-plane-common")
sys.path.insert(0, LAYER_AS_A_SUITE_SPELLS_IT)

import config

ROOT_CONFTEST = os.path.join(HERE, "conftest.py")
SENTINEL = "_planted_by_the_snapshot_control"
ORIGINAL_VALID_ACTIONS = config.VALID_ACTIONS
MUTATED_VALID_ACTIONS = frozenset(ORIGINAL_VALID_ACTIONS | {"annex_space"})

_mutated_modules = []


def _root_conftest(request):
    """The conftest module under test, fetched from pytest rather than imported.

    ``import conftest`` cannot be used: four conftest files in this tree share that bare module
    name, so ``sys.modules["conftest"]`` holds whichever pytest imported last, which in a full run
    is not this one. pytest registers each as a plugin under its own absolute path, so the path is
    the unambiguous handle.

    Args:
      request: The pytest request fixture, for its plugin manager.

    Returns:
      The module object for this tree's root ``conftest.py``.

    Raises:
      None.
    """
    return request.config.pluginmanager.get_plugin(ROOT_CONFTEST)


def _imported_flat_modules():
    """The pinned flat modules that are actually imported right now, by name.

    A single-file run of this file imports fewer of them than a full suite run does, so every
    assertion over the population is made against what is loaded rather than against the pin, and
    the pin is checked separately.

    Args:
      None.

    Returns:
      A dict of module name to module object, for the pinned names present in ``sys.modules``.

    Raises:
      None.
    """
    return {name: sys.modules[name] for name in EXPECTED_FLAT_MODULES if name in sys.modules}


def _imported_layer_package_modules():
    """Every loaded module belonging to one of the pinned layer packages, by name.

    Args:
      None.

    Returns:
      A dict of module name to module object.

    Raises:
      None.
    """
    return {
        name: module
        for name, module in list(sys.modules.items())
        if module is not None and name.split(".")[0] in EXPECTED_LAYER_PREFIXES
    }


def _collected_from_the_layer(conftest):
    """The modules the collector yields whose file sits in the layer directory.

    Computed from each module's own ``__file__`` rather than from the conftest's name filter, so a
    regression that widens the filter shows up here as a module this file did not expect — the
    layer's own test modules and ``fakes.py`` are what a missing name check lets in.

    Args:
      conftest: The conftest module under test.

    Returns:
      The set of ``__name__`` values for collected modules whose file is in the layer.

    Raises:
      None.
    """
    layer = os.path.realpath(LAYER)
    found = set()
    for module in conftest._shared_modules():
        path = getattr(module, "__file__", "") or ""
        if path and os.path.dirname(os.path.realpath(path)) == layer:
            found.add(module.__name__)
    return found


def test_the_snapshot_covers_exactly_the_modules_its_two_populations_name(request):
    """The collector reaches every loaded module in both populations, and nothing else from the layer.

    This is the check that makes the POPULATIONS real rather than advertised, and both halves are
    measured rather than argued. Shrinking ``_FLAT_SHARED_MODULES`` to a single name leaves the whole
    suite green; so does deleting the name test, which instead widens the flat population to the
    layer's own test modules and ``fakes.py``; and so does dropping six of the eight layer prefixes,
    which silently stops snapshotting 66 modules. None of the three is visible to any assertion about
    restoring one module.

    Args:
      request: The pytest request fixture.

    Returns:
      None.

    Raises:
      None.
    """
    conftest = _root_conftest(request)

    assert conftest._FLAT_SHARED_MODULES == EXPECTED_FLAT_MODULES, (
        "the layer's flat modules have changed; update the pin in this file deliberately"
    )
    assert frozenset(conftest._LAYER_PREFIXES) == EXPECTED_LAYER_PREFIXES, (
        "the fixture's layer packages have changed; update the pin in this file deliberately"
    )

    loaded_flat = _imported_flat_modules()
    assert loaded_flat, "no flat shared-space module is imported, so this file asserts nothing"
    assert _collected_from_the_layer(conftest) == set(loaded_flat)

    loaded_packages = _imported_layer_package_modules()
    assert loaded_packages, "no layer package is imported, so the half below asserts nothing"
    collected = set(conftest._shared_modules())
    missed = sorted(name for name, module in loaded_packages.items() if module not in collected)
    assert not missed, f"the snapshot fixture is not collecting {missed}"


def test_the_matcher_needs_both_the_name_and_the_directory(request):
    """A module is collected only when its name is published AND its file sits in the layer.

    Three assertions, each covering a regression the other two miss. Without the foreign-directory
    rejection the entire path comparison can be deleted with the suite green. Without the pardir
    acceptance that spelling is pinned only by whichever module imported the layer first, which is
    a race this file used to assert on and which a resolved-path import elsewhere in the tree wins.
    Without the excluded-name rejection the name test can be deleted, which widens the population to
    the layer's own test modules and `fakes.py` — the full suite catches that one through the
    population check above, but only because a full run has those modules loaded to be wrongly
    collected; a single-file run has nothing for it to bite on, and this assertion does not care.

    Stubs are legitimate here and nowhere else in this file. The objection to a stub is that it
    agrees with whatever the matcher does; these disagree by construction, one carrying the exact
    shape the suites produce and the others chosen to be wrong in one respect each. The test above
    anchors them to the real modules.

    Args:
      request: The pytest request fixture.

    Returns:
      None.

    Raises:
      None.
    """
    conftest = _root_conftest(request)
    name = min(EXPECTED_FLAT_MODULES)

    through_pardir = types.ModuleType(name)
    through_pardir.__file__ = os.path.join(LAYER_AS_A_SUITE_SPELLS_IT, f"{name}.py")
    impostor = types.ModuleType(name)
    impostor.__file__ = os.path.join(FOREIGN_DIR, f"{name}.py")
    excluded = types.ModuleType("fakes")
    excluded.__file__ = os.path.join(LAYER_AS_A_SUITE_SPELLS_IT, "fakes.py")

    assert conftest._is_flat_shared(name, through_pardir), (
        "the matcher rejects the pardir spelling every shared-space suite imports through"
    )
    assert not conftest._is_flat_shared(name, impostor), (
        f"a module named {name} outside the layer is being snapshotted, so the matcher is "
        "deciding on the bare name alone"
    )
    assert not conftest._is_flat_shared("fakes", excluded), (
        "a file the layer publishes but does not export is being snapshotted, so the matcher is "
        "deciding on the directory alone"
    )


def test_every_loaded_snapshotted_module_is_left_mutated_for_the_next_test():
    """Mutates every module in both populations and does NOT restore any of them.

    Half of an ordered pair, and deliberately untidy: the fixture is what has to put these back, and
    a test that cleaned up after itself would pass whether or not the fixture works. Its honesty
    rests on staying untidy, which nothing but this sentence enforces.

    The two mutation kinds are kept on DIFFERENT modules on purpose. Rebinding a constant is what
    almost every suite here does; ADDING an attribute is the only kind that can see a restore which
    updates a namespace without clearing it first. Put both on one module and a restore conditioned
    on a key having been added satisfies the rebinding assertion too, and puts back nothing for the
    ordinary case — measured: that plant passes a control whose two mutations share a module.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    config.VALID_ACTIONS = MUTATED_VALID_ACTIONS

    snapshotted = dict(_imported_flat_modules())
    snapshotted.update(_imported_layer_package_modules())
    for name, module in snapshotted.items():
        if module is config:
            continue
        setattr(module, SENTINEL, name)
        _mutated_modules.append(name)

    assert [name for name in _mutated_modules if name.split(".")[0] in EXPECTED_LAYER_PREFIXES], (
        "the sweep reached no layer package, so the next test only covers the flat half"
    )


def test_the_next_test_sees_every_snapshotted_module_as_it_was():
    """Nothing the test above did survived into this one, because the fixture put it all back.

    The first assertion is what keeps the rest honest. Selected alone, or reordered so the mutating
    test runs after it, this test would pass while proving nothing, so it fails loudly instead.

    Args:
      None.

    Returns:
      None.

    Raises:
      None.
    """
    assert _mutated_modules, (
        "the mutating test did not run before this one, so a pass here says nothing about the "
        "snapshot fixture"
    )

    assert "annex_space" not in config.VALID_ACTIONS
    assert config.VALID_ACTIONS == ORIGINAL_VALID_ACTIONS

    leaked = sorted(name for name in _mutated_modules if hasattr(sys.modules[name], SENTINEL))
    assert not leaked, f"the fixture did not restore {leaked}"
