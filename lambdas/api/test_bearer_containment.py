"""The bearer reaches the verifier and nothing else — not even the message body.

This service used to hold a raw credential past authentication, because the control planes
verified a token out of the message body and the enqueue routes had to forward one. A wrapper
that could not be rendered kept that contained, and a sweep counted its single unwrapper.

**The planes read the API's identity block now, so the containment problem is gone rather than
solved.** These assertions were rewritten upward rather than deleted: what was "exactly one module
unwraps a bearer" is now "none does", and what was "the token does not appear in a failure" now
holds because nothing ever put it anywhere. A guard whose subject disappears is worth keeping only
if the stronger claim is the one you actually want, and here it is — the way this regresses is
somebody re-introducing a forwarded credential, which is exactly what a zero-count catches.
"""

import ast
import json
import pathlib

import handler as api_handler
from apicommon import contract
from apicommon import enqueue as enqueue_module
from conftest import bearer


class _ExplodingSqs:
    """A client that fails inside the send helper, on the path that used to carry a bearer.

    Attributes:
      None.
    """

    def send_message(self, **kwargs):
        """Fails the way an unpredicted fault does.

        Args:
          **kwargs: The send request, ignored.

        Returns:
          Never returns.

        Raises:
          RuntimeError: Always.
        """
        raise RuntimeError("the queue exploded")


def test_a_failure_inside_the_sender_puts_no_part_of_the_bearer_on_the_wire(
    monkeypatch, capsys
):
    """The path that used to carry a token, driven to a fault with a distinctive literal.

    It held before because the token was wrapped; it holds now because the token is never put on
    that path at all. Kept because the assertion is about the OBSERVABLE — nothing in the response
    or the emitted records carries the caller's credential — which is the property a reader
    actually wants, and which survives whatever the mechanism happens to be.
    """
    for queue in contract.QUEUES:
        monkeypatch.setenv(queue.env_var, f"https://sqs.test/1/{queue.id}.fifo")
    monkeypatch.setenv("USER_SPACE_BUCKET", "dat-prod-user-space")
    monkeypatch.setenv("SHARED_SPACE_BUCKET", "dat-prod-shared-space")
    monkeypatch.setattr(
        enqueue_module.identity, "api_client", lambda service: _ExplodingSqs()
    )
    route = next(r for r in contract.ENQUEUE_ROUTES if r.id == "notifications.enqueue")
    headers = bearer()
    token = headers["authorization"].split(" ")[1]

    response = api_handler.handler(
        {
            "requestContext": {
                "http": {"method": route.method, "path": route.path},
                "requestId": "gateway-1",
            },
            "headers": headers,
            "body": json.dumps({"action": "markAllRead", "id": None}),
        },
        None,
    )
    emitted = capsys.readouterr()

    assert response["statusCode"] >= 500
    assert token not in json.dumps(response)
    assert token not in emitted.out + emitted.err


def test_no_module_unwraps_a_bearer_into_a_message_body():
    """The count was one and is now ZERO, which is the stronger form of the same guard.

    ``reveal`` was the single deliberate door through the wrapper, and the sender was the only
    caller. Both are gone with the field they served.

    **What this catches is narrow, and the narrowness is worth stating**: it is coupled to that
    name, so a forwarded credential reintroduced under any other one is invisible here. The teeth
    for that regression are in ``test_enqueue_routes``, which asserts the sent body carries neither
    field name a plane ever kept a token in — ten routes, checked on the message itself. This
    remains because the specific shape it names is the one somebody restoring the old design would
    reach for first.
    """
    api = pathlib.Path(__file__).parent
    callers = []

    for path in sorted(api.rglob("*.py")):
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name == "reveal":
                    callers.append(str(path.relative_to(api)))

    assert callers == [], (
        f"{callers} unwrap a credential — the planes read the identity block, so a token in a "
        "message body has no reader and is exposure with no purpose"
    )


def test_no_handler_names_a_credential_in_code():
    """The router's premise, narrowed rather than dropped: handlers stay out of this entirely.

    Walked as an AST rather than grepped as text, so a module may EXPLAIN why it does not touch a
    credential without tripping the check on its own prose. A text sweep that a docstring can fail
    gets loosened the first time it does, and a loosened sweep is one nobody trusts.
    """
    routes_dir = pathlib.Path(__file__).parent / "routes"
    forbidden = {"authorization", "bearer", "idToken", "reveal"}
    offenders = []

    for path in sorted(routes_dir.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            named = (
                {
                    getattr(node, "id", None),
                    getattr(node, "attr", None),
                    getattr(node, "arg", None),
                }
                if isinstance(node, (ast.Name, ast.Attribute, ast.arg))
                else {node.value}
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else set()
            )
            for word in forbidden & {n for n in named if isinstance(n, str)}:
                offenders.append((path.name, word))

    assert offenders == []
