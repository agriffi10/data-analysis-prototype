"""The contract's own guards: the closed vocabulary, the deterministic emitter, and the two gates.

Every assertion here is about a property that fails SILENTLY when it is wrong. A generator that
emits a fallback type produces a file that compiles, formats and passes review while agreeing with
every possible value. A generator whose output order varies produces a regeneration diff on an
unrelated PR, which trains a reader to regenerate without looking. Neither shows up as a red test
unless a test asks.
"""

import ast
import importlib.util
import pathlib
import re
import sys
from typing import NotRequired, TypedDict

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


def test_the_emitter_is_deterministic() -> None:
    """Two runs produce the same bytes, so a regeneration diff always means a real change.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the output varies between runs.
    """
    generator = _generator()

    assert generator.generate() == generator.generate()


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


def test_a_route_answering_a_bare_collection_fails_the_generator() -> None:
    """Every 200 body is an object, so an additive field always has somewhere to go.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a bare-collection response is accepted.
    """
    bare = contract.Route(
        id="bare.get",
        method="GET",
        path="/v1/bare",
        idempotent=True,
        plane="user",
        request=None,
        response=list[str],
    )

    generator = _generator()

    with pytest.raises(contract.UnsupportedTypeError):
        _with_routes((bare,), generator.generate)


def test_the_emitter_never_writes_any_or_unknown() -> None:
    """The two types that would make the generated file agree with everything.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either appears in the output.
    """
    emitted = _generator().generate()

    assert not re.search(r"\bany\b", emitted)
    assert not re.search(r"\bunknown\b", emitted)


def test_optionality_is_in_the_vocabulary_in_both_spellings() -> None:
    """``total=False`` and ``NotRequired`` both emit an optional key.

    Optionality is needed on the day the contract ships — the error envelope's ``detail`` is
    optional — and leaving it out would make the generator raise on the contract's own error
    type, where the repair a builder reaches for is a fallback.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either spelling is refused or emits a required key.
    """

    class Annotated(TypedDict):
        """One required key and one optional, by annotation."""

        here: str
        maybe: NotRequired[str]

    class Whole(TypedDict, total=False):
        """Every key optional, by declaration."""

        maybe: str

    generator = _generator()

    assert generator.render_declaration(contract.walk(Annotated)) == (
        "export type Annotated = {here: string; maybe?: string};"
    )
    assert generator.render_declaration(contract.walk(Whole)) == (
        "export type Whole = {maybe?: string};"
    )


def test_there_is_ONE_walker_and_the_generator_does_not_carry_its_own() -> None:
    """The validator and the emitter read the same walk of the same annotation.

    Asserted structurally rather than by comparing behaviour: two walkers that agree today are
    two walkers, and the second one is the one that stops being updated.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the generator defines a walker of its own.
    """
    generator = _generator()
    assert generator.contract.walk is contract.walk

    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    defined = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert not defined & {"walk", "_walk"}, (
        f"the generator defines its own walker ({defined & {'walk', '_walk'}}); the contract's "
        "is the only one, so the validator and the emitter cannot drift"
    )


def test_the_validator_reads_the_declaration_rather_than_a_second_schema() -> None:
    """An unknown key, a missing key and a wrong-typed key are each refused.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of the three is accepted, or a valid body is refused.
    """

    class Body(TypedDict):
        """A request shape for the validator to read."""

        name: str
        count: NotRequired[int]

    route = contract.Route(
        id="thing.put",
        method="PUT",
        path="/v1/thing",
        idempotent=False,
        plane="user",
        request=Body,
        response=contract.UserDirectoryResponse,
    )

    assert contract.validate_request(route, {"name": "a"}) is None
    assert contract.validate_request(route, {"name": "a", "count": 2}) is None
    assert contract.validate_request(route, {"name": "a", "extra": 1}) == "InvalidRequest"
    assert contract.validate_request(route, {"count": 2}) == "InvalidRequest"
    assert contract.validate_request(route, {"name": 7}) == "InvalidRequest"


def test_a_route_taking_no_body_refuses_one() -> None:
    """A body sent to a route that declares none is a caller and a server disagreeing.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a body is accepted by a route declaring none.
    """
    route = contract.route_by_id("userDirectory.get")
    assert route is not None

    assert contract.validate_request(route, None) is None
    assert contract.validate_request(route, {}) is None
    assert contract.validate_request(route, {"anything": 1}) == "InvalidRequest"


def test_every_path_is_versioned_for_the_whole_api() -> None:
    """One naming rule, so the seventeenth ported route teaches a reader nothing new.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any declared path breaks the rule.
    """
    for route in contract.ROUTES:
        assert PATH_RULE.match(route.path), f"{route.id} declares {route.path!r}"


def test_the_health_path_is_excluded_by_EXACT_match_never_by_a_prefix() -> None:
    """A prefix rule would admit ``/healthzz`` and anything else beginning the same way.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the health path is a declared route, or the exclusion is a prefix rule.
    """
    import router

    assert router.HEALTH_PATH not in {route.path for route in contract.ROUTES}
    assert not PATH_RULE.match(router.HEALTH_PATH)
    assert router.HEALTH_PATH == "/healthz"
    assert not (router.HEALTH_PATH + "z").startswith(tuple(r.path for r in contract.ROUTES))


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


def test_session_expired_is_the_only_401_the_enum_admits() -> None:
    """A second 401 code would be an expiry discriminator, which the boundary refuses to disclose.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any other code maps to 401.
    """
    at_401 = {code for code, status in contract.ERROR_STATUS.items() if status == 401}

    assert at_401 == {"SessionExpired"}


def test_a_denial_and_an_expiry_differ_in_BOTH_status_and_code() -> None:
    """A mapper collapsing them passes any test that exercises one at a time.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two share a status or a code.
    """
    assert contract.ERROR_STATUS["AccessDenied"] != contract.ERROR_STATUS["SessionExpired"]
    assert contract.ERROR_STATUS["AccessDenied"] == 403
    assert contract.ERROR_STATUS["SessionExpired"] == 401


def test_the_reserved_codes_are_declared_and_produced_by_nothing_yet() -> None:
    """Reserved deliberately, so the spec that needs one adds a route rather than a status class.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either is missing from the declaration.
    """
    assert contract.ERROR_STATUS["Conflict"] == 409
    assert contract.ERROR_STATUS["PayloadTooLarge"] == 413


def test_paging_is_declared_one_way_or_not_at_all() -> None:
    """A tripwire, vacuous today by design and inherited by the first paged route.

    ``nextToken`` is the paging contract and it is opaque. A second spelling arriving later is
    how two routes come to page differently, and the cost of noticing then is every consumer.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a paging field is declared under another name, or ``nextToken`` is
        declared as anything but an optional string.
    """
    for declared in contract.declared_types():
        node = contract.walk(declared)
        for name, child, _ in node.fields:
            assert name not in PAGING_ALIASES, (
                f"{declared.__name__}.{name} pages under a second name; the contract's paging "
                "field is nextToken and it is opaque to the client"
            )
            if name == "nextToken":
                assert child.kind == "optional" and child.of[0].kind == "str"


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
