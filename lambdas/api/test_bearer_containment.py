"""The bearer reaches the message body and nothing else.

This service is the first in the package to hold a raw credential past authentication, which
re-opens the trap a token-handling service is most likely to fall into: a token reaching a log
record or a stack trace by being interpolated into a message far from where it was read. Every
assertion here is about a rendering path rather than about intent — a rule that the token "must
not be logged" is upheld by nothing, where a wrapper that cannot render is upheld by the type.
"""

import ast
import json
import pathlib

import handler as api_handler
from apicommon import contract
from apicommon import enqueue as enqueue_module
from apicommon.context import Redacted, reveal
from conftest import bearer

_SECRET = "TOKEN-THAT-MUST-NOT-APPEAR-ANYWHERE"


class _ExplodingSqs:
    """A client that fails inside the send helper, after the bearer has been unwrapped.

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


def test_a_wrapped_bearer_renders_as_redacted_down_every_path_that_can_print_it():
    """The guard whose failure is silent: one missing dunder and the token renders with padding."""
    wrapped = Redacted(_SECRET)

    rendered = [
        f"{wrapped}",
        f"{wrapped:>40}",
        f"{wrapped!r}",
        f"{wrapped!s}",
        str(wrapped),
        repr(wrapped),
        json.dumps({"bearer": wrapped}, default=str),
        str(RuntimeError(f"failed for {wrapped}")),
    ]

    assert reveal(wrapped) == _SECRET
    for text in rendered:
        assert _SECRET not in text, text
        assert "<redacted>" in text, text


def test_a_failure_inside_the_sender_puts_no_part_of_the_bearer_on_the_wire(
    monkeypatch, capsys
):
    """The path that actually carries a token, driven to a fault with a distinctive literal."""
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


def test_exactly_one_module_unwraps_a_bearer_and_it_is_the_sender():
    """A second reveal is a second place a token can escape, so the count is the guard."""
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

    assert callers == ["apicommon/enqueue.py"]


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
