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
    assert response["body"]["status"] == "ok"
    assert response["body"]["version"]


def test_health_version_comes_from_the_package_stamp_not_the_environment(monkeypatch) -> None:
    """Terraform owns the environment map, so an env-borne version would be reverted by an apply.

    Reads the value through the layer's own accessor rather than re-deriving it — that accessor
    is the single owner of the environment-then-package fallback, and a second copy here would
    make this test agree with itself rather than with the deployed function.

    Args:
      monkeypatch: pytest's environment patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the reported version disagrees with the layer's resolved stamp.
    """
    from cpcommon.observability import build_version

    monkeypatch.setenv("BUILD_VERSION", "should-not-be-read-at-call-time")

    response = router.route("GET", "/healthz")

    assert response["body"]["version"] == build_version()


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
        response = router.route(method, path)

        assert response["statusCode"] == 404, f"{method} {path} must not be served"
        assert response["headers"]["content-type"] == "application/json"
        assert json.dumps(response["body"])


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
        headers = router.route(method, path)["headers"]

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
