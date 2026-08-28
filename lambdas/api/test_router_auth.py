"""The gate: who gets in, what a refusal says, and what it deliberately does not say.

**Every load-bearing assertion here is negative.** A request carrying a genuine token succeeds
against a correct implementation and against one that does not verify at all, so the happy path
proves only wiring. What can fail is the refusals.

**The byte-identity assertion is paired with a reason-code assertion, and neither is sufficient
alone.** One body for every failure is what stops the API being an oracle for which check
failed — but a router that returns that body unconditionally, without ever calling the
verifier, satisfies it perfectly, and would also satisfy the undeclared-route test, the
header-parsing table and the credential-source table. The eight distinct reason codes in the
log records are what says eight different checks actually ran.

Attributes:
  UNDECLARED: A route registered for one test with no public declaration, which is how
    deny-by-default is told apart from allow-by-default.
"""

import ast
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from conftest import USERNAME_CLAIM, bearer, token

UNDECLARED = ("GET", "/v1/_test-undeclared")


def _refusals():
    """Every way a request can fail to identify its caller, as (label, headers).

    Eight rows, and the expired one is deliberately among them: it is the row a builder is
    most tempted to answer differently, because a discriminator would let the browser skip a
    refresh it does not need.
    """
    return [
        ("no header", {}),
        ("malformed token", {"authorization": "Bearer not-a-jwt"}),
        ("bad signature", {"authorization": f"Bearer {token()[:-6]}AAAAAA"}),
        ("wrong issuer", bearer(iss="https://elsewhere.example/pool")),
        ("wrong audience", bearer(aud="another-client")),
        ("wrong token use", bearer(token_use="access")),
        ("missing username", bearer(**{USERNAME_CLAIM: None})),
        ("expired", bearer(exp=int(time.time()) - 60)),
    ]


def test_a_valid_token_reaches_the_handler(stub_directory):
    """The control. It proves the wiring and nothing about the verification.

    The one row here that dispatches, so it is the one that needs the user plane stubbed. Every
    refusal below is refused before a handler runs and reaches no AWS call at all — which is
    also what makes the call count in the next test meaningful.
    """
    response = router.route("GET", "/v1/user-directory", bearer("alice"))
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["usernames"] == ["alice", "bob_smith"]


def test_all_eight_refusals_are_byte_identical():
    """A body that varied per failure would map which check failed, for anyone probing."""
    bodies = {label: router.route("GET", "/v1/user-directory", headers) for label, headers in _refusals()}

    for label, response in bodies.items():
        assert response["statusCode"] == 401, f"{label} did not return 401"

    serialised = {label: json.dumps(response, sort_keys=True) for label, response in bodies.items()}
    assert len(set(serialised.values())) == 1, (
        f"the refusals are distinguishable: {serialised}"
    )


def test_the_provider_configuration_failing_is_a_server_fault_and_never_a_401(monkeypatch):
    """A 401 reads to the browser as 'sign in again', which cannot fix a misconfiguration.

    It would also spend a token refresh discovering that, and present the outage as a login
    problem in every report that followed.
    """
    monkeypatch.delenv("OIDC_ISSUER", raising=False)

    response = router.route("GET", "/v1/user-directory", bearer())
    assert response["statusCode"] >= 500
    assert response["statusCode"] != 401


def _shipped_modules():
    """Every non-test module in this package, parsed.

    Args:
      None.

    Returns:
      Pairs of relative path and parsed tree.

    Raises:
      None.
    """
    root = pathlib.Path(__file__).resolve().parent
    for path in sorted(root.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        yield path.relative_to(root), ast.parse(path.read_text(encoding="utf-8"))


def _constants(tree):
    """Yields every constant in a module EXCEPT its docstrings.

    A raw substring scan cannot tell a status a module returns from a docstring saying that
    status must never be returned — and this package's own refusal module says exactly that, in
    the sentence explaining why a 401 is not a 401-shaped 403. Parsing means the assertion is
    about code, which is what it claims to be about.

    Args:
      tree: The parsed module.

    Returns:
      An iterator of constant nodes.

    Raises:
      None.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and id(node) not in docstrings:
            yield node
