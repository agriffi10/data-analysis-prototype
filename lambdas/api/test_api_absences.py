"""What this API is NOT, and what it must never learn.

**These are reintroduction guards, not evidence the design is right.** Nothing in scope can emit
a cookie, a PKCE parameter or a login route, so they pass on the day they are written — which is
the point. A reader who saw an earlier draft of this design, or who ports a pattern from another
codebase where the API performs the login, will reach for exactly these pieces. The sweep is what
reddens when they do.

**The sweep's subject is every non-test module in this package, selected by path.** That rule is
itself a decision rather than a convenience: the suites legitimately mint Cognito-shaped tokens,
name a pool id, and assert on the very literals these tests forbid. Run unfiltered, the sweeps
fail on their own assertions the day they are written, and the repair a builder reaches for is to
delete them. An allowlist would work today and rot quietly; a path rule cannot.

Attributes:
  BFF_MACHINERY: The pieces of a server-side login flow. Every one is a thing this API
    deliberately does not do, and a thing whose arrival would be invisible without this.
  PROVIDER_NAMES: Text that would mean the verifier knows which provider it is verifying.
"""

import ast
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
INFRA = HERE.parent.parent / "infra"

BFF_MACHINERY = (
    "set-cookie",
    "set_cookie",
    "cookie",
    "csrf",
    "code_verifier",
    "code_challenge",
    "client_secret",
    "grant_type",
    "authorization_code",
    "refresh_token",
    "/auth/",
)

PROVIDER_NAMES = ("cognito", "amazonaws.com", "user_pool", "userpool")


def _shipped():
    """Every non-test module in this package, as (path, source, tree).

    Args:
      None.

    Returns:
      An iterator of triples.

    Raises:
      None.
    """
    for path in sorted(HERE.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        yield path.relative_to(HERE), source, ast.parse(source)


def _code_strings(tree):
    """Every string literal in a module except its docstrings.

    Args:
      tree: The parsed module.

    Returns:
      An iterator of string values.

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
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            yield node.value


def test_the_sweeps_have_a_subject() -> None:
    """Guard-the-guard: a filter excluding everything would read as a clean pass.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the subject is empty or has lost the module it exists to pin.
    """
    modules = {str(path) for path, _, _ in _shipped()}
    assert "router.py" in modules
    assert "apicommon/principal.py" in modules
    assert len(modules) >= 6, f"the sweep's subject collapsed to {sorted(modules)}"


def test_no_module_reaches_for_a_server_side_login_flow() -> None:
    """Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any BFF machinery appears in code.
    """
    for path, _, tree in _shipped():
        names = {
            node.attr.lower() for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {node.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Name)}
        literals = {value.lower() for value in _code_strings(tree)}

        for forbidden in BFF_MACHINERY:
            assert forbidden not in names, f"{path} names {forbidden}"
            assert not any(forbidden in literal for literal in literals), (
                f"{path} carries the literal {forbidden}"
            )


def test_the_verifier_does_not_know_which_provider_it_is_verifying() -> None:
    """Five environment values describe the provider, and no module names one.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a provider name appears in code.
    """
    for path, _, tree in _shipped():
        literals = {value.lower() for value in _code_strings(tree)}
        for name in PROVIDER_NAMES:
            assert not any(name in literal for literal in literals), (
                f"{path} names {name!r} — the provider is configuration, not code"
            )


def test_the_only_name_taken_from_the_control_plane_error_module_is_the_auth_seam() -> None:
    """Mapping an auth failure to a control-plane terminal is a Step Functions concern.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any other name is imported from cpcommon.errors.
    """
    for path, _, tree in _shipped():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "cpcommon.errors":
                imported = {alias.name for alias in node.names}
                assert imported <= {"AuthError"}, f"{path} imports {sorted(imported)}"


def test_the_control_plane_decorator_stack_is_absent() -> None:
    """The response is the channel for a synchronous API.

    A notification decorator here would be copied from a verb by a reader who did not notice
    that a verb has no caller waiting on it and this does.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the failure-notification decorator appears.
    """
    for path, source, _ in _shipped():
        assert "notifies_on_failure" not in source, f"{path} uses notifies_on_failure"


def test_the_expiry_relaxation_is_unreachable_from_here() -> None:
    """A synchronous request is never late by construction.

    The relaxed verification exists for the dead-letter drain, where a message is old by
    construction. A route reaching for it has misread why it exists.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module reaches the relaxed entry points or the private core.
    """
    forbidden = {
        "verify_id_token_ignoring_expiry",
        "verified_username_ignoring_expiry",
        "_verify_claims",
        "_verify",
    }
    for path, _, tree in _shipped():
        names = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for alias in (
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        ):
            names.add(alias)
        assert not (names & forbidden), f"{path} reaches {sorted(names & forbidden)}"


def test_the_verifier_has_no_dependency_on_the_router() -> None:
    """What lets the gate move to an authorizer later without touching the verification.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the verifier or the identity module imports the router.
    """
    for module in (
        HERE.parent / "control-plane-common" / "cpcommon" / "auth.py",
        HERE / "apicommon" / "principal.py",
    ):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "router", f"{module.name} imports the router"
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "router", f"{module.name} imports the router"


def test_the_function_is_instrumented_as_one_service() -> None:
    """Records land under one service prefix, so the API's runs stay one queryable set.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the service name is not the one the log layout expects.
    """
    source = (HERE / "handler.py").read_text(encoding="utf-8")
    assert 'SERVICE = "api"' in source
    assert "observability.init(service=SERVICE" in source
    assert "@observability.traced" in source


def test_the_provider_keys_the_code_reads_are_exactly_the_keys_terraform_declares() -> None:
    """Set equality, both sides derived. A key in one and not the other is a hard failure.

    A value present in code and absent from the environment map is a request that fails at the
    boundary; the reverse is a variable nobody reads, which is how a map accumulates keys that
    look load-bearing and are not.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two key sets differ.
    """
    config_source = (HERE / "apicommon" / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(config_source)
    read = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for value in node.values:
                if isinstance(value, ast.Constant) and str(value.value).startswith("OIDC_"):
                    read.add(value.value)

    declared = set(
        re.findall(
            r"^\s*(OIDC_[A-Z_]+)\s*=",
            (INFRA / "modules" / "api" / "lambda.tf").read_text(),
            re.MULTILINE,
        )
    )
    assert declared, "no provider keys were found in the environment map — the read is broken"

    assert read == declared, (
        f"code reads {sorted(read)} and Terraform declares {sorted(declared)}"
    )
    assert len(read) == 5


def test_the_browsers_example_environment_gains_nothing() -> None:
    """That file is the SPA's dev fallback; these five are server-side and Terraform computes them.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If a provider key appears in the SPA's example environment.
    """
    example = (HERE.parent.parent / "apps" / "portal" / ".env.example").read_text()
    assert "OIDC_" not in example


def test_no_module_builds_a_jwks_url_from_the_issuer() -> None:
    """The provider's path convention is a fact about ONE provider.

    Cognito publishes its keys under its issuer; other providers do not. The concatenation lives
    at the composition root, which already names the provider and is therefore a site any swap
    edits. Here it must be an opaque value.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module derives a key-set URL.
    """
    for path, _, tree in _shipped():
        for literal in _code_strings(tree):
            lowered = literal.lower()
            # Naming the variable is the point of the variable; building a URL is the defect.
            assert "well-known" not in lowered, f"{path} builds a key-set URL: {literal!r}"
            assert not ("://" in lowered and "jwks" in lowered), (
                f"{path} carries a hard-coded key-set URL: {literal!r}"
            )


def test_the_route_table_and_the_public_list_are_what_they_claim() -> None:
    """Both asserted by value: the public list is the whole of what runs without a credential.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If either has grown.
    """
    import sys

    sys.path.insert(0, str(HERE))
    import router

    assert frozenset({("GET", "/healthz")}) == router.PUBLIC_ROUTES
    assert set(router.ROUTES) == {("GET", "/_auth/whoami")}
    assert json.loads(router.route("GET", "/healthz", {})["body"])["status"] == "ok"
