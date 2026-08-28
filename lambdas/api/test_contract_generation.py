"""The contract's own guards: the closed vocabulary, the deterministic emitter, and the two gates.

Every assertion here is about a property that fails SILENTLY when it is wrong. A generator that
emits a fallback type produces a file that compiles, formats and passes review while agreeing with
every possible value. A generator whose output order varies produces a regeneration diff on an
unrelated PR, which trains a reader to regenerate without looking. Neither shows up as a red test
unless a test asks.
"""

import importlib.util
import pathlib
import re
import sys
from typing import TypedDict

import pytest
from apicommon import contract

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GENERATOR = ROOT / "scripts" / "generate_api_contract.py"

PATH_RULE = re.compile(r"^/v1/[a-z0-9-]+(/[^/]+)*$")

PAGING_ALIASES = ("continuationToken", "pageToken", "cursor", "offset", "page", "total")


def _generator():
    """Imports the generator as a module.

    Loaded by path rather than by name because ``scripts/`` is not a package and is not on the
    path under pytest.

    Args:
      None.

    Returns:
      The imported generator module.

    Raises:
      ImportError: If the module cannot be loaded.
    """
    spec = importlib.util.spec_from_file_location("generate_api_contract", GENERATOR)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_generated_file_on_disk_is_current() -> None:
    """The local twin of the CI gate, so drift is caught before the push rather than by it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the committed file differs from what the declaration produces.
    """
    generator = _generator()
    committed = (ROOT / generator.OUTPUT).read_text(encoding="utf-8")

    assert committed == generator.generate(), (
        "run scripts/generate_api_contract.py — the committed TypeScript and the Python "
        "declaration have drifted"
    )


def test_a_shape_outside_the_vocabulary_raises_rather_than_falling_back() -> None:
    """The requirement that can silently succeed.

    A fallback type agrees with every possible value, so the day the emitter meets a shape it
    does not understand is the day the contract stops being checked — and nothing goes red.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an unsupported shape is accepted.
    """

    class Unsupported(TypedDict):
        """A shape the vocabulary deliberately cannot express."""

        thing: dict[str, object]

    with pytest.raises(contract.UnsupportedTypeError):
        contract.walk(Unsupported)


def test_the_status_map_is_total_and_its_image_is_the_closed_set() -> None:
    """Every declared code has exactly one status, and no status outside the set is reachable.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the map is partial or its image escapes the set.
    """
    from typing import get_args

    declared = set(get_args(contract.ErrorCode))

    assert set(contract.ERROR_STATUS) == declared
    assert set(contract.ERROR_STATUS.values()) <= contract.ROUTE_STATUSES


def _with_routes(routes, action):
    """Runs an action against a replaced route table, restoring it afterwards.

    Args:
      routes: The route tuple to install for the duration.
      action: The zero-argument callable to run.

    Returns:
      Whatever the action returned.

    Raises:
      Exception: Whatever the action raised.
    """
    original = contract.ROUTES
    contract.ROUTES = routes  # type: ignore[misc]
    try:
        return action()
    finally:
        contract.ROUTES = original  # type: ignore[misc]
