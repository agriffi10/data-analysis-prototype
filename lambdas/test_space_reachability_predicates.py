"""Three predicates answer "may this actor, or this share, reach that space" — and only two
of them may be called outside the module that defines them.

``is_active`` is the weakest of the three and the easiest to reach for: it tests a status and
nothing else. That was adequate while a space's status and its usability were the same thing.
They are not any more — a deleted space keeps ``status: "active"``, because nothing about its
objects or its database changed, and what ends is its membership. So a caller deciding
reachability from ``is_active`` admits a workspace every surface tells the user is gone.

The two callers that did decide reachability that way have moved to ``may_receive_share``, and
this sweep is what stops a third appearing:
``is_active`` is now an ingredient of the other two and is not called anywhere else. Its
population is DERIVED from the tree rather than listed, because a hand-maintained list of
callers rots and this one was already wrong once — an enumeration written for this change named
five modules when there were seven.
"""

import ast
import pathlib

LAMBDAS = pathlib.Path(__file__).resolve().parent

#: The module that defines all three, and the only place ``is_active`` may be called.
DEFINER = LAMBDAS / "control-plane-common" / "cpcommon" / "registry.py"

#: The predicates this sweep tracks. Adding a fourth without adding it here is the failure mode
#: the sweep exists to prevent, so the set is asserted against the definer's own contents below.
PREDICATES = frozenset({"is_active", "is_active_member", "may_receive_share"})

#: Callable only inside the definer.
INTERNAL_ONLY = frozenset({"is_active"})


def _source_files():
    """Every non-test Python module under ``lambdas/``.

    Args:
      None.

    Returns:
      The module paths.

    Raises:
      None.
    """
    return [
        path
        for path in sorted(LAMBDAS.rglob("*.py"))
        if "__pycache__" not in path.parts
        and not path.name.startswith("test_")
        and path.name not in ("conftest.py", "fakes.py")
    ]


def _referenced_predicates(path):
    """The tracked predicate names this module names, however it reaches them.

    Attribute access and bare names both count: ``reg.is_active(...)`` and a
    ``from … import is_active`` followed by ``is_active(...)`` are the same call, and a sweep
    seeing only one of them undercounts its own population.

    Args:
      path: The module to read.

    Returns:
      The predicate names it references.

    Raises:
      SyntaxError: If the module does not parse.
    """
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Attribute) and node.attr in PREDICATES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in PREDICATES:
            found.add(node.id)
        elif isinstance(node, ast.ImportFrom):
            found |= {a.name for a in node.names if a.name in PREDICATES}
    return found


def test_the_sweep_found_its_population():
    """Guards the guard: a walk that matches nothing makes every assertion below vacuous."""
    callers = {p for p in _source_files() if p != DEFINER and _referenced_predicates(p)}

    assert len(callers) >= 6, sorted(str(p.relative_to(LAMBDAS)) for p in callers)


def test_every_tracked_predicate_is_actually_defined_where_this_says():
    # A name that has been renamed or deleted would make its rule below unenforceable while the
    # sweep stayed green.
    defined = {
        node.name
        for node in ast.walk(ast.parse(DEFINER.read_text()))
        if isinstance(node, ast.FunctionDef)
    }

    assert defined >= PREDICATES, sorted(PREDICATES - defined)


def test_is_active_is_never_called_outside_the_module_that_defines_it():
    offenders = sorted(
        str(path.relative_to(LAMBDAS))
        for path in _source_files()
        if path != DEFINER and _referenced_predicates(path) & INTERNAL_ONLY
    )

    assert offenders == [], (
        f"{offenders} decide reachability from a status alone. An emptied space keeps "
        "`status: \"active\"`, so use may_receive_share (a destination) or is_active_member "
        "(an actor) instead."
    )
