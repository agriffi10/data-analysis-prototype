"""The handler reads payload format 2.0 and dispatches, and it holds no surface of its own.

The method and path are read from ``requestContext.http`` rather than the top-level ``rawPath``,
and getting that wrong is the failure this file exists to catch: ``rawPath`` carries the stage
prefix on the ``execute-api`` host, so a handler reading it answers ``/healthz`` through the custom
domain and 404s the same request through the other host — and only one of those is ever tested.
"""

import ast
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import handler as m

FORBIDDEN_HANDLER_NAMES = (
    "boto3",
    "assume_role",
    "sts",
    "dynamodb",
    "cookie",
    "session",
)


def _referenced_names(module: str) -> set[str]:
    """Collects every name a module actually imports or touches, ignoring prose.

    A raw substring scan cannot tell a forbidden name from a docstring SAYING the name is
    forbidden — this package's own "holds no session" sentence trips one. Parsing means the
    assertion is about code, which is what it claims to be about.

    Args:
      module: The file name inside this directory to parse.

    Returns:
      Imported module roots, imported symbols, attribute names and bare identifiers, lowercased.

    Raises:
      None.
    """
    source = pathlib.Path(os.path.dirname(os.path.abspath(__file__)), module).read_text(
        encoding="utf-8"
    )
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0].lower())
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module.split(".")[0].lower())
            for alias in node.names:
                names.add(alias.name.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, ast.Name):
            names.add(node.id.lower())
    return names


def _event(method: str, path: str) -> dict:
    """Builds an API Gateway payload-format-2.0 request.

    Args:
      method: The HTTP method.
      path: The request path.

    Returns:
      The event dict, carrying a ``rawPath`` that DISAGREES with the routed path so a handler
      reading the wrong field is caught rather than accidentally right.

    Raises:
      None.
    """
    return {
        "rawPath": f"/$default{path}",
        "requestContext": {"http": {"method": method, "path": path}},
    }


def test_health_is_served_through_the_request_context() -> None:
    """The routed path comes from ``requestContext.http``, not from ``rawPath``.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the handler reads the stage-prefixed path instead.
    """
    response = m.handler(_event("GET", "/healthz"), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ok"


def test_the_daily_wake_is_answered_by_the_health_route() -> None:
    """The API module's keep-warm rule sends this file every day; it must be a plain success.

    A payload missing the request context would be refused 401 on every wake and read as one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the wake is not answered as a healthy request.
    """
    payload = (
        pathlib.Path(__file__).resolve().parents[2] / "infra/modules/api/keep-warm.json"
    )
    response = m.handler(json.loads(payload.read_text(encoding="utf-8")), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ok"


def test_an_unroutable_request_is_refused_not_a_traceback() -> None:
    """A malformed event cannot arrive through the API, so an answer beats a raise.

    The status this asserts CHANGED when the router began identifying callers first, and the
    new one is the honest answer: an event carrying no request context also carries no
    credential, so it is refused as unauthenticated rather than reported as a missing route.
    Telling an unidentified caller which paths exist is what deny-by-default is for.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a missing request context raises instead of being refused.
    """
    for event in ({}, {"requestContext": {}}, {"requestContext": {"http": {}}}):
        assert m.handler(event, None)["statusCode"] == 401


def test_the_handler_holds_no_aws_surface_and_no_session() -> None:
    """Every one of these belongs to a later spec, and each would apply green if added early.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the module references any of them.
    """
    referenced = _referenced_names("handler.py")

    offending = sorted(referenced & set(FORBIDDEN_HANDLER_NAMES))
    assert not offending, (
        f"handler.py references {offending} — the placeholder resolves no identity and calls no "
        "service; that arrives with the spec that needs it"
    )
