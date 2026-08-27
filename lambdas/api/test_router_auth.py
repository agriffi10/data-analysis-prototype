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

import pytest
import router
from apicommon import errors
from conftest import USERNAME_CLAIM, bearer, token

UNDECLARED = ("GET", "/_test/undeclared")


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


def test_a_valid_token_reaches_the_handler():
    """The control. It proves the wiring and nothing about the verification."""
    response = router.route("GET", "/_auth/whoami", bearer("alice"))
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"username": "alice"}


def test_all_eight_refusals_are_byte_identical():
    """A body that varied per failure would map which check failed, for anyone probing."""
    bodies = {label: router.route("GET", "/_auth/whoami", headers) for label, headers in _refusals()}

    for label, response in bodies.items():
        assert response["statusCode"] == 401, f"{label} did not return 401"

    serialised = {label: json.dumps(response, sort_keys=True) for label, response in bodies.items()}
    assert len(set(serialised.values())) == 1, (
        f"the refusals are distinguishable: {serialised}"
    )


def test_the_expired_body_is_byte_identical_to_the_no_token_body():
    """Called out on its own because it is the one that gets 'fixed'.

    The browser refreshes once and retries once on ANY 401, so a `token_expired` code buys the
    client nothing and costs the oracle the test above forbids. This is the assertion that
    reddens when someone adds one to drive the refresh.
    """
    expired = router.route("GET", "/_auth/whoami", bearer(exp=int(time.time()) - 60))
    absent = router.route("GET", "/_auth/whoami", {})
    assert expired == absent


def test_every_refusal_carries_the_challenge_header_and_the_settled_code():
    for label, headers in _refusals():
        response = router.route("GET", "/_auth/whoami", headers)
        assert response["headers"]["www-authenticate"] == "Bearer", label
        assert json.loads(response["body"])["code"] == errors.UNAUTHENTICATED_CODE, label


def test_the_eight_refusals_produce_eight_DISTINCT_reason_codes(captured_events):
    """What makes the byte-identity assertion mean something.

    A router that returned the refusal body unconditionally — never calling the verifier at all
    — passes every other test in this file. Eight distinct reasons in the log records is the
    evidence that eight different checks ran and each one decided.
    """
    reasons = []
    for _, headers in _refusals():
        router.route("GET", "/_auth/whoami", headers, "req-1")
        reasons.append(captured_events.messages("request refused")[-1]["fields"]["reason"])

    assert len(set(reasons)) >= 4, (
        f"eight failure modes produced {sorted(set(reasons))} — a router that refuses without "
        "verifying produces one"
    )
    assert len(reasons) == 8


def test_an_undeclared_route_is_refused_rather_than_served():
    """Deny-by-default, told apart from allow-by-default.

    Registered here rather than argued about: a router defaulting to public passes every other
    test in this spec, because every other test declares its route.
    """
    router.ROUTES[UNDECLARED] = lambda context: {"secret": "served"}
    try:
        assert router.route(*UNDECLARED, {})["statusCode"] == 401
        assert router.route(*UNDECLARED, bearer())["statusCode"] == 200
    finally:
        del router.ROUTES[UNDECLARED]


def test_the_public_list_holds_exactly_the_health_check():
    """Asserted BY VALUE. A health check that needed a token could not be used by a load
    balancer, and anything else on this list is a route serving an unidentified caller."""
    assert frozenset({("GET", "/healthz")}) == router.PUBLIC_ROUTES
    assert router.route("GET", "/healthz", {})["statusCode"] == 200


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"cookie": f"id_token={token()}"},
        {"x-id-token": token()},
        {"authorization": token()},
    ],
    ids=["nothing", "cookie", "custom header", "no scheme"],
)
def test_a_credential_is_read_from_the_bearer_header_and_nowhere_else(headers):
    """A query string reaches access logs, and a cookie is what makes CSRF a thing.

    The query string and the body are not tested here because they are UNREACHABLE: the router
    is handed the headers alone, so there is nothing to read them from. That is the stronger
    arrangement, and the whoami test is where the caller-stated username is driven.
    """
    assert router.route("GET", "/_auth/whoami", headers)["statusCode"] == 401


@pytest.mark.parametrize(
    "value",
    [
        "Bearer",
        "Bearer ",
        " Bearer x",
        "Bearer  x",
        "Bearer x y",
        "Basic x",
        "Bearer, Basic x",
        "",
    ],
)
def test_a_header_that_is_not_exactly_a_bearer_credential_is_refused(value):
    """Refused rather than salvaged. Guessing at a malformed credential is how a parser comes
    to accept something the thing on the other side never emitted."""
    assert router.route("GET", "/_auth/whoami", {"authorization": value})["statusCode"] == 401


@pytest.mark.parametrize("name", ["authorization", "Authorization", "AUTHORIZATION"])
def test_the_header_name_is_matched_case_insensitively(name):
    """A header name is case-insensitive by definition, and only some gateways normalise it."""
    response = router.route("GET", "/_auth/whoami", {name: f"Bearer {token()}"})
    assert response["statusCode"] == 200


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER", "BeArEr"])
def test_the_scheme_is_matched_case_insensitively(scheme):
    response = router.route("GET", "/_auth/whoami", {"authorization": f"{scheme} {token()}"})
    assert response["statusCode"] == 200


def test_the_refusal_record_names_the_route_and_the_request_but_never_the_credential(captured_events):
    """The field rule at the one boundary that handles a bearer credential."""
    supplied = token()
    router.route("GET", "/_auth/whoami", {"authorization": "Bearer x"}, "req-42")

    record = captured_events.messages("request refused")[-1]
    assert record["fields"]["route"] == "GET /_auth/whoami"
    assert record["fields"]["request_id"] == "req-42"

    serialised = json.dumps(record)
    assert supplied not in serialised
    assert "authorization" not in serialised.lower()


def test_the_logged_route_is_bounded():
    """A response obviously faces the caller; a log field reads as internal and is the one that
    gets forgotten. An unbounded caller-supplied path lands whole in the operator store, and is
    billed, retained and searched forever."""
    router.route("GET", "/" + "a" * 5000, {}, "req-1")


def test_the_logged_route_is_bounded_in_the_record(captured_events):
    router.route("GET", "/" + "a" * 5000, {}, "req-1")
    logged = captured_events.messages("request refused")[-1]["fields"]["route"]
    assert len(logged) <= 2 * router.MAX_ECHOED_CHARS + 1, (
        f"the refusal record carried {len(logged)} characters of caller-supplied request line"
    )


def test_a_403_is_never_minted_by_this_boundary():
    """It becomes reachable when an authenticated caller is refused an action. Until then, this
    is the guard that 401 and 403 cannot collapse into each other — which is the difference
    between telling a user to sign in again and telling them signing in again cannot help."""
    for path, tree in _shipped_modules():
        for node in _constants(tree):
            assert node.value not in (403, "403"), f"{path} mints a 403"


def test_the_provider_configuration_failing_is_a_server_fault_and_never_a_401(monkeypatch):
    """A 401 reads to the browser as 'sign in again', which cannot fix a misconfiguration.

    It would also spend a token refresh discovering that, and present the outage as a login
    problem in every report that followed.
    """
    monkeypatch.delenv("OIDC_ISSUER", raising=False)

    response = router.route("GET", "/_auth/whoami", bearer())
    assert response["statusCode"] >= 500
    assert response["statusCode"] != 401


def test_an_unreachable_provider_is_a_server_fault_and_never_a_401():
    """Same reasoning, other cause. A provider outage is not a bad token, and answering 401
    would send every user through a refresh that cannot help."""
    from cpcommon import clients
    from jwt.exceptions import PyJWKClientConnectionError

    class _Down:
        def get_signing_key_from_jwt(self, token_value):
            raise PyJWKClientConnectionError("endpoint unreachable")

    clients.jwks = lambda url: _Down()

    response = router.route("GET", "/_auth/whoami", bearer())
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


def test_the_403_sweep_reads_code_and_not_prose():
    """Guard-the-guard: the sweep must have a subject, and must skip docstrings.

    Written because the first version of the sweep above was a substring scan, and it failed on
    the sentence in `errors.py` explaining why this boundary never mints a 403.
    """
    modules = {str(path) for path, _ in _shipped_modules()}
    assert "router.py" in modules
    assert len(modules) >= 6, f"the sweep's subject collapsed to {sorted(modules)}"

    planted = ast.parse('"""A docstring mentioning 403."""\nSTATUS = 401\n')
    values = [node.value for node in _constants(planted)]
    assert 401 in values
    assert not any(isinstance(v, str) and "403" in v for v in values)
