"""The probe route: it returns the caller's own name, and it cannot be told to return another's.

The second assertion is the one that matters. A handler that read the request body would pass
every test that sends a matching token — which is every test anybody writes by accident.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from conftest import bearer


def test_it_returns_the_verified_username():
    response = router.route("GET", "/_auth/whoami", bearer("alice"))
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"username": "alice"}


def test_a_request_STATING_a_different_username_still_resolves_the_tokens():
    """Alice's token; bob asserted everywhere a caller can assert anything. The answer is alice.

    This is what passing a resolved principal to the handler exists to make true, rather than
    something each handler has to remember not to do.
    """
    headers = {**bearer("alice"), "x-username": "bob"}
    response = router.route("GET", "/_auth/whoami", headers)
    assert json.loads(response["body"])["username"] == "alice"

    # A stated username in the request line reaches a route that does not exist — and an
    # identified caller gets a 404 rather than the handler.
    assert router.route("GET", "/_auth/whoami?username=bob", bearer("alice"))["statusCode"] == 404


def test_the_handler_is_given_no_way_to_read_a_stated_username():
    """Structural, and stronger than a behavioural test could be.

    The handler's only argument is the request context, which carries a verified principal and
    two strings for the log. There is no event, no body and no query string to read — so the
    failure this guards against is not merely absent, it is unrepresentable.
    """
    import ast
    import inspect
    import textwrap

    from routes.whoami import whoami

    signature = inspect.signature(whoami)
    assert list(signature.parameters) == ["context"]

    # Parsed, not grepped. A substring scan cannot tell a name the code READS from a docstring
    # saying that name is out of reach — and this handler's docstring says exactly that, which
    # is what a scan trips on.
    tree = ast.parse(textwrap.dedent(inspect.getsource(whoami)))
    read = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    } | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    for forbidden in ("event", "body", "queryStringParameters", "headers", "get"):
        assert forbidden not in read, f"the handler reaches for {forbidden}"
    assert read <= {"context", "principal", "username", "RequestContext", "str", "dict", "Any"}, (
        f"the handler reads {sorted(read)} — anything beyond the context and its own "
        "annotations is a second source of identity"
    )


def test_it_discloses_nothing_about_anyone_else():
    """No lookup, no existence check, no AWS call — so it cannot be used to probe for users."""
    import ast
    import inspect
    import textwrap

    from cpcommon import clients
    from routes.whoami import whoami

    calls = []
    for name in ("s3", "sqs", "sfn", "glue", "athena", "cognito", "lf"):
        setattr(clients, name, lambda *a, _n=name, **k: calls.append(_n))

    router.route("GET", "/_auth/whoami", bearer("alice"))
    assert calls == [], f"the probe reached AWS: {calls}"

    tree = ast.parse(textwrap.dedent(inspect.getsource(whoami)))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported, f"the probe imports {sorted(imported)}"
