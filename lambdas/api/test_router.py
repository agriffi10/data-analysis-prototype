"""The router answers one path and refuses the rest, and it emits no CORS header.

Two of these assertions are about **absences**, which is the point. A CORS header emitted here
would be ignored by API Gateway rather than duplicated, so the browser would never see the defect
— it would surface as a second source of truth nobody is reading, and only when the API's own
configuration changed. An AWS call or a business route arriving early is the same shape: it applies
green and belongs to a later spec.

Attributes:
  FORBIDDEN_HEADER_PREFIX: The header family CORS ownership forbids this module from emitting.
"""

import ast
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from conftest import bearer

FORBIDDEN_HEADER_PREFIX = "access-control-"
FORBIDDEN_ROUTER_NAMES = ("boto3", "clients", "assume_role", "sts")


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


def test_health_returns_ok_and_a_version() -> None:
    """The one route that exists reports the build it is running.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the status, the status field or the version is wrong.
    """
    response = router.route("GET", "/healthz")

    assert response["statusCode"] == 200

    body = json.loads(response["body"])
    assert body["status"] == "ok"
    assert body["version"]


def test_health_reports_the_layer_s_resolved_stamp_and_not_a_live_env_read(monkeypatch) -> None:
    """The router must not re-read the environment; it reports what the layer resolved at import.

    The name matters here. The layer's own accessor honours ``BUILD_VERSION`` **first** by
    design, so "the version comes from the package stamp" is not true of the layer and this
    test cannot claim it — what it can claim is that the router does not perform its own live
    read, which is the thing that would drift from the log records.

    Both assertions are needed. Comparing against ``build_version()`` alone passes even if the
    router re-reads the environment, because both sides would then return the patched value —
    measured: that mutation survived until the second assertion was added.

    Args:
      monkeypatch: pytest's environment patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the router re-reads the environment at call time.
    """
    from cpcommon.observability import build_version

    monkeypatch.setenv("BUILD_VERSION", "should-not-be-read-at-call-time")

    reported = json.loads(router.route("GET", "/healthz")["body"])["version"]

    assert reported == build_version()
    assert reported != "should-not-be-read-at-call-time", (
        "the router re-read BUILD_VERSION at call time — the stamp is resolved once at import, "
        "and a live read drifts from what every log record carries"
    )


def test_every_other_method_and_path_is_a_json_404() -> None:
    """A later spec may replace the shape; this spec claims only that the router refuses.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any of these is served, or served without a JSON body.
    """
    for method, path in (
        ("POST", "/healthz"),
        ("GET", "/"),
        ("GET", "/healthz/"),
        ("GET", "/files"),
        ("DELETE", "/anything"),
        ("", ""),
    ):
        response = router.route(method, path, bearer())

        assert response["statusCode"] == 404, f"{method} {path} must not be served"
        assert response["headers"]["content-type"] == "application/json"
        assert json.loads(response["body"])["error"] == "not_found"


def test_no_response_carries_a_cors_header() -> None:
    """CORS is the API's to answer, and two answerers is how they come to disagree.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any response carries an ``access-control-*`` header.
    """
    for method, path in (("GET", "/healthz"), ("GET", "/nope"), ("OPTIONS", "/healthz")):
        headers = router.route(method, path, bearer())["headers"]

        offending = [
            name for name in headers if name.lower().startswith(FORBIDDEN_HEADER_PREFIX)
        ]
        assert not offending, (
            f"{method} {path} emitted {offending} — CORS is configured on the API, which "
            "IGNORES headers from the integration, so this would silently never reach a browser"
        )


def test_the_module_makes_no_aws_call_and_declares_no_client() -> None:
    """No AWS call, no client, no identity — each is a later spec's, and each applies green.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the module references any AWS surface.
    """
    referenced = _referenced_names("router.py")

    offending = sorted(referenced & set(FORBIDDEN_ROUTER_NAMES))
    assert not offending, f"router.py references {offending} — the placeholder holds no AWS surface"


def test_every_body_is_a_STRING_because_a_status_makes_the_envelope_literal() -> None:
    """The defect this file previously passed straight over.

    API Gateway infers a response only when the function returns JSON and returns NO
    ``statusCode``. Once a status is set the envelope is read literally and ``body`` must be a
    string — an object there is a malformed proxy response and a 500 for the caller.

    ``json.dumps(response["body"])`` was the old assertion, and it is green on exactly the bug
    it was meant to exclude: a dict body serializes perfectly. Asserting the TYPE is what
    separates "this could be serialized" from "this was".

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any response body is not an already-serialized string.
    """
    for method, path in (("GET", "/healthz"), ("GET", "/nope"), ("POST", "/healthz")):
        body = router.route(method, path, bearer())["body"]

        assert isinstance(body, str), (
            f"{method} {path} returned a {type(body).__name__} body beside a statusCode — "
            "API Gateway reads that envelope literally and answers 500"
        )
        assert isinstance(json.loads(body), dict)


def test_a_refusal_bounds_what_it_echoes_back() -> None:
    """The method and path are caller-controlled and are reflected into the body.

    The body is JSON and never HTML, so this is a size bound rather than an escaping one — a
    request line is not a place to let an arbitrary payload round-trip.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either value is echoed unbounded.
    """
    body = json.loads(router.route("GET", "/" + "a" * 5000, bearer())["body"])

    assert len(body["path"]) <= router.MAX_ECHOED_CHARS, (
        "the refusal echoed the whole caller-supplied path back"
    )
