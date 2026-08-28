"""The wire contract, declared once. Every other statement about the wire is derived from here.

The API is Python and the browser is TypeScript, and something has to hold them in agreement.
Two hand-edited copies rot. A contract test both sides hand-wrote against each other compares a
copy of the answer with itself, and it agrees most confidently exactly when both were written by
the same session on the same afternoon. So this module is the single declaration, and
``scripts/generate_api_contract.py`` emits the TypeScript from it.

Python is the source rather than TypeScript because the runtime request validator and the wire
types must read ONE declaration. A validator written against a separate schema is a third copy,
and the third copy is the one nobody regenerates.

**The type vocabulary is closed, and that is the load-bearing part.** ``walk`` raises on anything
it does not understand rather than falling back, because a fallback type agrees with every
possible value: the day the emitter meets a shape it cannot express is the day the contract stops
being checked, and nothing goes red. The generator and the validator consume the SAME walk of the
SAME annotation, so neither can drift into supporting something the other refuses.

Attributes:
  ErrorCode: The closed set of machine codes a failure may carry. A code outside it never reaches
    the wire, including on an unhandled exception.
  ERROR_STATUS: Every code to the one status it produces. Total by construction, and its image is
    a subset of the statuses the router may emit.
  ROUTE_STATUSES: Every status the router is permitted to emit. The gateway's own 413, 429, 502
    and 504 are produced ABOVE the router, are not envelope-shaped, and are deliberately absent.
  ROUTES: Every route the API serves. The router dispatches from this table, the plane table
    derives from it, and the generated TypeScript is emitted from it — so a route cannot exist
    in one of those places and not the others.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import (
    Any,
    Final,
    Literal,
    NotRequired,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

ErrorCode = Literal[
    "InvalidRequest",
    "SessionExpired",
    "AccessDenied",
    "NotFound",
    "Conflict",
    "PayloadTooLarge",
    "UnsupportedMediaType",
    "RateLimited",
    "IdentityUnavailable",
    "InternalError",
    "ApiUnavailable",
]

ERROR_STATUS: Final[dict[str, int]] = {
    "InvalidRequest": 400,
    "SessionExpired": 401,
    "AccessDenied": 403,
    "NotFound": 404,
    "Conflict": 409,
    "PayloadTooLarge": 413,
    "UnsupportedMediaType": 415,
    "RateLimited": 429,
    "IdentityUnavailable": 500,
    "InternalError": 500,
    "ApiUnavailable": 503,
}

ROUTE_STATUSES: Final[frozenset[int]] = frozenset(
    {200, 400, 401, 403, 404, 409, 413, 415, 429, 500, 503}
)


class ApiErrorDetail(TypedDict):
    """The inner object of every failure body.

    ``detail`` is operator text authored at the raise site, read in a devtools panel and in the
    log store, and rendered nowhere. Nothing here is phrased for a user: the browser owns every
    user-facing sentence, and a server that returns one reverses that quietly, because the
    sentence would look fine in every screenshot.

    Attributes:
      code: The machine code, drawn from the closed set.
      requestId: The gateway's id for the request, so a user-reported failure is findable.
      detail: Optional operator text. Never a stringified exception.
    """

    code: ErrorCode
    requestId: str
    detail: NotRequired[str]


class ApiErrorBody(TypedDict):
    """The only wrapped shape in the API. A success body is the payload itself.

    Attributes:
      error: The failure's code, correlation id and optional operator text.
    """

    error: ApiErrorDetail


class UserDirectoryResponse(TypedDict):
    """The published username directory, as the browser receives it.

    Carries no document version and no count: the document's shape is the server's business now,
    and a field the browser does not read is a field a later change has to keep true.

    Attributes:
      usernames: Catalog-safe usernames, re-checked server-side.
      generatedAt: When the directory was built, or None when it is unavailable or unusable.
    """

    usernames: list[str]
    generatedAt: str | None


@dataclass(frozen=True)
class Route:
    """One route, declared whole.

    Every field is required, which is the point: a route cannot be added without choosing a
    credential plane and stating whether it may be retried. Both belong to the ROUTE rather than
    to the handler, so a guard can see them without running anything.

    Attributes:
      id: The name every call site uses. A call site names this, never a URL.
      method: The HTTP method.
      path: The path, versioned for the whole API rather than per route.
      idempotent: Whether a caller above the transport may retry. NEVER derived from the method —
        a POST that resolves a free name is a read, and a PUT that appends is not.
      plane: Which credentials the route may reach for. The user plane is the caller's own
        assumed session; the API plane is the function's execution role.
      request: The declared request body type, or None for a route that takes no body.
      query: The declared query-string type, or None for a route that takes no query. Its fields
        are STRINGS ONLY — see ``check_routes``. Required like every other field: a defaulted one
        would let a route be added without deciding, which is the mistake ``plane`` exists not to
        repeat.
      response: The declared 200 body type. Always an object type, so an additive field always
        has somewhere to go.
    """

    id: str
    method: Literal["GET", "POST", "PUT", "DELETE"]
    path: str
    idempotent: bool
    plane: Literal["user", "api"]
    request: Any | None
    query: Any | None
    response: Any


ROUTES: Final[tuple[Route, ...]] = (
    Route(
        id="userDirectory.get",
        method="GET",
        path="/v1/user-directory",
        idempotent=True,
        plane="user",
        request=None,
        query=None,
        response=UserDirectoryResponse,
    ),
)


class UnsupportedTypeError(Exception):
    """Raised when an annotation falls outside the closed vocabulary.

    Deliberately fatal rather than recoverable. The repair a builder reaches for is a fallback
    type, and a fallback agrees with every possible value — so the failure this raises loudly is
    the one that would otherwise be silent forever.
    """


@dataclass(frozen=True)
class TypeNode:
    """One annotation, normalised into the closed vocabulary.

    The single representation both consumers read: the generator renders it to TypeScript, the
    validator interprets it against a value. One walk, two readers — so neither can come to
    support a shape the other refuses.

    Attributes:
      kind: Which of the vocabulary's forms this is.
      of: The contained node, for a list or an optional.
      literals: The permitted string values, for a literal union.
      name: The declared type's name, for an object.
      fields: Name, type and requiredness for each key of an object.
    """

    kind: Literal["str", "int", "float", "bool", "none", "list", "optional", "literal", "object"]
    of: tuple["TypeNode", ...] = ()
    literals: tuple[str, ...] = ()
    name: str = ""
    fields: tuple[tuple[str, "TypeNode", bool], ...] = field(default=())


_SCALARS: Final[dict[Any, TypeNode]] = {
    str: TypeNode(kind="str"),
    int: TypeNode(kind="int"),
    float: TypeNode(kind="float"),
    bool: TypeNode(kind="bool"),
}


def walk(annotation: Any) -> TypeNode:
    """Normalises one annotation, or refuses it.

    The vocabulary is str, int, float, bool, None, list[X], X | None, Literal over strings, a
    reference to another declared TypedDict, and optional keys. X is drawn from the same
    vocabulary, recursively.

    Args:
      annotation: The annotation to normalise.

    Returns:
      The normalised node.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary. Never returns a
        permissive node in its place.
    """
    if annotation is type(None):
        return TypeNode(kind="none")
    if annotation in _SCALARS:
        return _SCALARS[annotation]

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        if not args or not all(isinstance(value, str) for value in args):
            raise UnsupportedTypeError(f"Literal over non-strings: {annotation!r}")
        return TypeNode(kind="literal", literals=tuple(args))

    if origin is list:
        if len(args) != 1:
            raise UnsupportedTypeError(f"list without exactly one argument: {annotation!r}")
        return TypeNode(kind="list", of=(walk(args[0]),))

    if _is_union(origin):
        present = [arg for arg in args if arg is not type(None)]
        if len(present) != 1 or len(args) != 2:
            raise UnsupportedTypeError(f"union that is not X | None: {annotation!r}")
        return TypeNode(kind="optional", of=(walk(present[0]),))

    if _is_typed_dict(annotation):
        return _object_node(annotation)

    raise UnsupportedTypeError(f"outside the contract's type vocabulary: {annotation!r}")


def _is_union(origin: Any) -> bool:
    """Whether an origin is a union, in either spelling.

    Both are checked because the two spellings are not the same object: ``X | None`` produces
    ``types.UnionType`` while ``Optional[X]`` produces ``typing.Union``, and a declaration using
    the one that is not checked would be refused for a reason that reads as a vocabulary gap.

    Args:
      origin: The annotation's origin.

    Returns:
      True if the origin is a union.

    Raises:
      None.
    """
    import types
    import typing

    return origin is types.UnionType or origin is typing.Union


def _is_typed_dict(annotation: Any) -> bool:
    """Whether an annotation is a declared TypedDict.

    Args:
      annotation: The annotation to test.

    Returns:
      True if it is a TypedDict class.

    Raises:
      None.
    """
    return isinstance(annotation, type) and hasattr(annotation, "__required_keys__")


def _object_node(annotation: Any) -> TypeNode:
    """Normalises a TypedDict, in declaration order.

    Order is taken from the annotations rather than from the required and optional key sets,
    which are frozensets and iterate unpredictably — the emitter's output has to be
    byte-identical across runs for the regeneration gate to mean anything.

    Args:
      annotation: The TypedDict class.

    Returns:
      The object node, its fields in declaration order.

    Raises:
      UnsupportedTypeError: If any field's type is outside the vocabulary.
    """
    hints = get_type_hints(annotation)
    required = set(annotation.__required_keys__)
    fields = tuple(
        (name, walk(hints[name]), name in required) for name in annotation.__annotations__
    )
    return TypeNode(kind="object", name=annotation.__name__, fields=fields)


def declared_types() -> tuple[Any, ...]:
    """Every TypedDict the generated TypeScript must carry, in a deterministic order.

    Walks the routes in declaration order and each route's request, then its query, then its
    response, so the emitted file's order is a function of this module alone.

    Args:
      None.

    Returns:
      The TypedDict classes, first-seen order, without duplicates.

    Raises:
      None.
    """
    seen: list[Any] = []
    for route in ROUTES:
        for annotation in (route.request, route.query, route.response):
            for found in _referenced(annotation):
                if found not in seen:
                    seen.append(found)
    for annotation in (ApiErrorDetail, ApiErrorBody):
        for found in _referenced(annotation):
            if found not in seen:
                seen.append(found)
    return tuple(seen)


def _referenced(annotation: Any) -> list[Any]:
    """Every TypedDict reachable from one annotation, dependencies first.

    Args:
      annotation: The annotation to search, or None.

    Returns:
      The TypedDict classes it reaches, each before the type referencing it.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary.
    """
    if annotation is None:
        return []
    if not _is_typed_dict(annotation):
        walk(annotation)
        return []
    found: list[Any] = []
    for nested in get_type_hints(annotation).values():
        for reachable in _nested_typed_dicts(nested):
            if reachable not in found:
                found.append(reachable)
    if annotation not in found:
        found.append(annotation)
    return found


def _nested_typed_dicts(annotation: Any) -> list[Any]:
    """Every TypedDict inside one annotation, dependencies first.

    Args:
      annotation: The annotation to search.

    Returns:
      The TypedDict classes it contains.

    Raises:
      UnsupportedTypeError: If the annotation is outside the vocabulary.
    """
    if _is_typed_dict(annotation):
        return _referenced(annotation)
    args = get_args(annotation)
    if get_origin(annotation) is Literal or not args:
        walk(annotation)
        return []
    found: list[Any] = []
    for arg in args:
        if arg is not type(None):
            found.extend(_nested_typed_dicts(arg))
    return found


def check_routes() -> None:
    """Refuses a route declaration the wire contract cannot carry.

    A 200 body is always a JSON object, never a bare array, string or number, so an additive
    field always has somewhere to go — and "additive only within a version" is the whole reason
    a loaded tab survives an API deploy. A route answering ``list[str]`` has nowhere to put the
    next field and would force a new version to add one.

    Args:
      None.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If a route's response, or a declared request, is not an object type.
    """
    for route in ROUTES:
        if not _is_typed_dict(route.response):
            raise UnsupportedTypeError(
                f"{route.id} answers {route.response!r}; every 200 body is an object"
            )
        if route.request is not None and not _is_typed_dict(route.request):
            raise UnsupportedTypeError(
                f"{route.id} accepts {route.request!r}; every request body is an object"
            )
        if route.query is not None:
            _check_query(route)


_QUERY_KINDS: Final[frozenset[str]] = frozenset({"str", "literal"})


def _check_query(route: "Route") -> None:
    """Refuses a query declaration a query string cannot carry.

    **A query string is all strings.** API Gateway hands ``queryStringParameters`` over as
    ``dict[str, str]``, so a declaration naming an int, a bool or a nested object type-checks in
    the browser, generates clean TypeScript, and then refuses every real request with a 400 the
    handler never sees. Measured, not predicted: a declaration carrying ``space: SpaceRef`` and
    ``maxKeys: int`` emitted correct TypeScript and 400'd on the exact payload the gateway sends.

    So the vocabulary NARROWS here rather than widening. A route wanting a structured value in a
    query flattens it — ``spaceKind`` and ``spaceName`` rather than a ``SpaceRef`` — and the
    divergence from the body's own shape is deliberate. Refused at declaration time, which is a
    build-time failure, rather than per request, which is an outage.

    Args:
      route: The route whose query declaration to check.

    Returns:
      None.

    Raises:
      UnsupportedTypeError: If the query is not an object, or carries a non-string field.
    """
    if not _is_typed_dict(route.query):
        raise UnsupportedTypeError(
            f"{route.id} accepts {route.query!r}; every query is an object"
        )
    for name, node, _required in walk(route.query).fields:
        inner = node.of[0] if node.kind == "optional" else node
        if inner.kind not in _QUERY_KINDS:
            raise UnsupportedTypeError(
                f"{route.id}'s query field {name!r} is {inner.kind}; a query string carries "
                f"only strings, so declare it str or a Literal of strs and flatten what is not"
            )


def route_by_id(route_id: str) -> Route | None:
    """Finds a route by its id.

    Reads ``ROUTES`` on every call rather than an index built at import, so a test that adds a
    route sees it without reaching into a private cache — which is the only way the claim "adding
    a row makes the route reachable with no other edit" can be checked at all.

    Args:
      route_id: The route's id.

    Returns:
      The route, or None if no route carries that id.

    Raises:
      None.
    """
    for route in ROUTES:
        if route.id == route_id:
            return route
    return None


def route_for(method: str, path: str) -> Route | None:
    """Resolves a request line to the route serving it.

    Args:
      method: The request's HTTP method.
      path: The request's path.

    Returns:
      The route, or None when no route serves that pair.

    Raises:
      None.
    """
    for route in ROUTES:
        if route.method == method and route.path == path:
            return route
    return None


def validate_request(route: Route, body: object) -> str | None:
    """Checks a request body against the route's declared type.

    Reads the same walk of the same annotation the generator emits from, so the shape accepted
    here and the shape the browser was typed against cannot disagree.

    Args:
      route: The route the body was sent to.
      body: The parsed request body, or None when none was sent.

    Returns:
      None when the body is acceptable, otherwise the machine code refusing it.

    Raises:
      UnsupportedTypeError: If the route's declared request type is outside the vocabulary,
        which is a defect in the declaration rather than in the request.
    """
    if route.request is None:
        return None if body in (None, {}) else "InvalidRequest"
    if not _matches(walk(route.request), body):
        return "InvalidRequest"
    return None


def validate_query(route: Route, query: Mapping[str, str] | None) -> str | None:
    """Checks a request's query string against the route's declared type.

    The same walk of the same annotation the generator emits from, exactly as ``validate_request``
    uses for the body — so a query the browser was typed against and a query this refuses cannot
    disagree.

    Args:
      route: The route the query was sent to.
      query: The gateway's parsed query string, or None when none was sent.

    Returns:
      None when the query is acceptable, otherwise the machine code refusing it.

    Raises:
      UnsupportedTypeError: If the route's declared query type is outside the vocabulary, which
        is a defect in the declaration rather than in the request.
    """
    if route.query is None:
        return None if not query else "InvalidRequest"
    if not _matches(walk(route.query), dict(query or {})):
        return "InvalidRequest"
    return None


def _matches(node: TypeNode, value: object) -> bool:
    """Whether one value satisfies one normalised node.

    An object refuses an unknown key as firmly as a missing one: a body carrying a field the
    contract does not declare is a caller and a server that disagree about the shape, and
    accepting it silently is how the disagreement survives to the next version.

    Args:
      node: The normalised node.
      value: The value to check.

    Returns:
      True if the value satisfies the node.

    Raises:
      None.
    """
    if node.kind == "none":
        return value is None
    if node.kind == "str":
        return isinstance(value, str)
    if node.kind == "bool":
        return isinstance(value, bool)
    if node.kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if node.kind == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if node.kind == "literal":
        return isinstance(value, str) and value in node.literals
    if node.kind == "optional":
        return value is None or _matches(node.of[0], value)
    if node.kind == "list":
        return isinstance(value, list) and all(_matches(node.of[0], item) for item in value)
    if node.kind == "object":
        if not isinstance(value, dict):
            return False
        declared = {name for name, _, _ in node.fields}
        if set(value) - declared:
            return False
        for name, child, required in node.fields:
            if name not in value:
                if required:
                    return False
                continue
            if not _matches(child, value[name]):
                return False
        return True
    return False
