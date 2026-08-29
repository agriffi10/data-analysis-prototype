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


def test_a_nested_list_of_optionals_emits_the_type_it_is_declared_as() -> None:
    """The results page is the contract's first nested list and its first ``list[X | None]``.

    Both must survive the walk by recursion rather than by a special case, and the rendered string
    is what a reader compares against the spec — so this asserts the BYTES, not that something
    was emitted. The rule that decides the parentheses reads the contained node's KIND: an earlier
    version looked for a space in the rendered inner type, which a nested list's own parentheses
    satisfied, and it emitted ``((string | null)[])[]`` — the same type, different bytes, and the
    regeneration gate is a byte comparison.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the emitted type is not the declared one.
    """
    generator = _generator()

    rendered = generator.render(contract.walk(list[list[str | None]]))

    assert rendered == "(string | null)[][]"


def test_a_type_with_no_fields_emits_something_that_still_CHECKS() -> None:
    """``{}`` in TypeScript agrees with every non-null value, which is a fallback by another name.

    The empty body arrives with the first route whose 200 carries no payload. Emitted as ``{}``,
    its response type would accept a string, a number or an array — so the one place the contract
    is supposed to be strongest would be the one place it checked nothing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an empty object emits as ``{}``.
    """
    generator = _generator()

    class _Empty(TypedDict):
        """A response carrying nothing."""

    rendered = generator.render_declaration(contract.walk(_Empty))

    assert rendered == "export type _Empty = Record<string, never>;"


def test_the_route_table_publishes_the_parameters_each_path_names() -> None:
    """The browser is typed from these names, so they are emitted rather than re-derived in TS.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a templated route emits no parameters, or a fixed one emits some.
    """
    generator = _generator()

    emitted = generator.generate()

    assert (
        "'athena.results': {method: 'GET', path: '/v1/queries/{queryExecutionId}/results', "
        "idempotent: true, params: ['queryExecutionId']}," in emitted
    )
    assert "path: '/v1/user-directory', idempotent: true, params: []}," in emitted
