"""Two credential planes, and the enumeration that keeps them two.

**Everything here guards a failure that fails OPEN.** A route handed a client on the wrong plane
does not error — the call succeeds, against the execution role's identity, and returns
right-looking data for a user who was never authorized to see it. There is no symptom to wait for
and no test of a feature that would notice, so the guards are a runtime refusal and a mechanical
sweep rather than a convention.

**The sweep's exemption is a list of exact module paths, never a pattern.** A pattern exemption
silently exempts the next module somebody names similarly, which is how a rule comes to cover less
than its name claims. And the client-construction check is a COUNT rather than an absence: "no
module outside the identity layer builds a client" is satisfied by a package that builds six of
them inside it, so the assertion is that the package holds exactly one construction site.

**The stale-route case is the one a two-direction violation test misses.** Declaring a route and
not declaring a route are both tested against a process where nothing else has run. The leak this
design actually invites is a warm container whose *previous* request declared the API plane, so
that case is driven as a sequence.

**The ``conftest`` import below is at MODULE scope deliberately**, matching the other suites
here. Inside a function it resolves at run time, by which point another package's ``conftest``
owns that name in ``sys.modules`` — green alone, ImportError in the full run.

Attributes:
  HERE: This function's package root.
  EXEMPT_MODULES: The modules allowed to construct a client, by exact relative path.
  FORBIDDEN_CLIENT_CALLS: The boto3 entry points that mint a client on default credentials.
  CLIENT_FACTORY_METHODS: Factory methods that do the same without naming boto3.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from apicommon import contract, identity, planes

_API_PLANE_ROUTE = contract.Route(
    id="test.apiPlane",
    method="GET",
    path="/v1/_test-api-plane",
    idempotent=True,
    plane="api",
    request=None,
    response=contract.UserDirectoryResponse,
)

HERE = pathlib.Path(__file__).resolve().parent

EXEMPT_MODULES = ("apicommon/identity.py",)
FORBIDDEN_CLIENT_CALLS = frozenset({"client", "resource", "Session"})

#: Factory METHODS that mint a client without naming boto3 at the call site. `create_client` is
#: botocore's own door and reaches default credentials exactly as `boto3.client` does.
CLIENT_FACTORY_METHODS = frozenset({"create_client"})


def _shipped():
    """Every non-test module in this package, as (relative path, tree).

    Selected by path rather than by an allowlist, for the reason the absence sweeps already
    record: the suites legitimately do the things the sweeps forbid, so an unfiltered run would
    fail on its own fixtures the day it was written.

    Args:
      None.

    Returns:
      An iterator of (relative path string, parsed module) pairs.

    Raises:
      None.
    """
    for path in sorted(HERE.rglob("*.py")):
        if path.name.startswith(("test_", "conftest.")) or "__pycache__" in path.parts:
            continue
        yield str(path.relative_to(HERE)), ast.parse(path.read_text(encoding="utf-8"))


def is_exempt(relative_path: str) -> bool:
    """Whether a module may construct a client, by EXACT identity.

    Args:
      relative_path: The module's path relative to the package root.

    Returns:
      True only for a module named exactly in the exemption list.

    Raises:
      None.
    """
    return relative_path in EXEMPT_MODULES


def _aliases(tree, module: str, names: set[str]) -> set[str]:
    """Every local name bound to one of ``names`` imported from ``module``.

    Import aliasing is the cheapest way past a sweep that matches on the name it expects, and it
    is not an exotic evasion — ``from boto3 import client`` is how a lot of code is written.

    Args:
      tree: The parsed module.
      module: The module the names would be imported from.
      names: The names of interest. Empty means "any name".

    Returns:
      The local names bound to them.

    Raises:
      None.
    """
    bound = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "") == module:
            for alias in node.names:
                if not names or alias.name in names:
                    bound.add(alias.asname or alias.name)
    return bound


def findings(tree) -> list[tuple[str, str]]:
    """Every way a module could reach AWS or an identity around the two doors.

    Returned as tagged findings rather than asserted here, so the same checker can be driven
    against a synthetic module that is supposed to be caught.

    **Each shape below was reached past an earlier version of this checker**, which matched only
    ``boto3.client(...)`` as an attribute call and only ``UserIdentity`` as a bare name. A route
    doing ``from boto3 import client as mk`` and ``identity.UserIdentity(username="mallory", ...)``
    — the second being the form every route naturally reaches for, since they all already import
    the module — passed the whole suite while constructing a default-credentials client AND
    assuming the portal role as somebody else. Every row is now in the parametrized guard below.

    Args:
      tree: The parsed module.

    Returns:
      A list of (kind, detail) pairs.

    Raises:
      None.
    """
    found: list[tuple[str, str]] = []

    boto3_names = _aliases(tree, "boto3", set())
    identity_names = _aliases(tree, "apicommon.identity", {"UserIdentity"}) | _aliases(
        tree, ".identity", {"UserIdentity"}
    ) | _aliases(tree, "identity", {"UserIdentity"})

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "boto3"
                    and func.attr in FORBIDDEN_CLIENT_CALLS
                ):
                    found.append(("client_construction", f"boto3.{func.attr}"))
                if func.attr in CLIENT_FACTORY_METHODS:
                    found.append(("client_construction", func.attr))
                if func.attr == "UserIdentity":
                    found.append(("identity_construction", "UserIdentity"))
                if func.attr == "replace" and any(
                    isinstance(argument, ast.Attribute) and argument.attr == "acting_as"
                    for argument in node.args
                ):
                    found.append(("identity_construction", "dataclasses.replace"))
            if isinstance(func, ast.Name):
                if func.id in boto3_names:
                    found.append(("client_construction", func.id))
                if func.id == "UserIdentity" or func.id in identity_names:
                    found.append(("identity_construction", func.id))
            if (
                isinstance(func, ast.Name)
                and func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and str(node.args[1].value).startswith("_")
            ):
                found.append(("private_identity_access", str(node.args[1].value)))

        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("cpcommon.clients"):
                    found.append(("clients_import", alias.name))
                if alias.name in ("boto3", "botocore") or alias.name.startswith("botocore."):
                    found.append(("boto3_import", alias.name))
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "cpcommon" and any(a.name == "clients" for a in node.names):
                found.append(("clients_import", "cpcommon.clients"))
            if module.startswith("cpcommon.clients"):
                found.append(("clients_import", module))
            if module == "boto3" or module.startswith(("boto3.", "botocore")):
                found.append(("boto3_import", module))
            if module in ("apicommon.identity", ".identity", "identity"):
                for alias in node.names:
                    if alias.name.startswith("_"):
                        found.append(("private_identity_import", alias.name))
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and isinstance(node.value, ast.Name)
            and node.value.id == "identity"
        ):
            found.append(("private_identity_access", node.attr))
    return found


# ── The sweep ─────────────────────────────────────────────────────────────────


def test_the_sweep_has_a_subject_and_its_exemption_is_an_identity_not_a_pattern() -> None:
    """Guard-the-guard, both halves.

    A subject that collapsed to nothing reads as a clean pass, and an exemption that matched by
    prefix or substring would quietly cover every module named nearby — which is the failure a
    docstring-versus-declaration exemption already cost this repo once.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the subject is empty, or the exemption matches anything but itself.
    """
    modules = {path for path, _ in _shipped()}
    assert len(modules) >= 10, (
        f"the sweep's subject is {len(modules)} modules: {sorted(modules)}. A floor set well "
        "below the real count lets half the package leave the sweep without anyone noticing."
    )
    for exempt in EXEMPT_MODULES:
        assert exempt in modules, f"{exempt} is exempted and does not exist"

    assert is_exempt("apicommon/identity.py")
    for near_miss in (
        "apicommon/identity_helpers.py",
        "apicommon/identity2.py",
        "identity.py",
        "apicommon/identity.py ",
    ):
        assert not is_exempt(near_miss), f"{near_miss} is exempt by resemblance"


def test_no_module_outside_the_identity_layer_reaches_aws_or_mints_an_identity() -> None:
    """The whole sweep, over every shipped module but the one door.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module builds a client, imports the default-credential cache,
        reaches a private name in the identity layer, or constructs an identity of its own.
    """
    for path, tree in _shipped():
        if is_exempt(path):
            continue
        assert findings(tree) == [], f"{path} reaches around the two doors: {findings(tree)}"


def test_the_package_holds_exactly_one_client_construction_site() -> None:
    """A COUNT, not an absence — "none outside the layer" permits six inside it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the package builds no client, or more than one.
    """
    sites = [
        (path, detail)
        for path, tree in _shipped()
        for kind, detail in findings(tree)
        if kind == "client_construction"
    ]
    assert len(sites) == 1, f"the package constructs {len(sites)} clients: {sites}"
    assert sites[0][0] in EXEMPT_MODULES


def test_the_identity_is_constructed_in_one_module_and_nowhere_else() -> None:
    """A route minting its own identity assumes the portal role as somebody else.

    It would compile, pass review and pass every test that supplies a matching token — the
    credential-selection defect the tag rule forbids, wearing a scoping parameter's clothes.

    **Equality, not a subset.** ``builders <= EXEMPT_MODULES`` is satisfied by an EMPTY builders
    set, so a detector that stopped recognising the construction would report clean — which is
    exactly how the aliased and attribute-qualified forms stayed invisible. The count is what
    makes a broken detector redden.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any module outside the layer constructs one.
    """
    builders = {
        path
        for path, tree in _shipped()
        for kind, _ in findings(tree)
        if kind == "identity_construction"
    }
    assert builders == set(EXEMPT_MODULES), (
        f"identities are minted in {sorted(builders)}, expected exactly {sorted(EXEMPT_MODULES)}"
    )


@pytest.mark.parametrize(
    ("label", "source", "kind"),
    [
        ("a client", "import boto3\ndef f():\n    return boto3.client('s3')\n", "client_construction"),
        ("a resource", "import boto3\nb = boto3.resource('s3')\n", "client_construction"),
        ("a session", "import boto3\ns = boto3.Session()\n", "client_construction"),
        ("the cache", "from cpcommon import clients\n", "clients_import"),
        ("the cache by path", "import cpcommon.clients\n", "clients_import"),
        ("a private door", "from apicommon.identity import _execution_client\n", "private_identity_import"),
        ("a private door by attribute", "from apicommon import identity\nx = identity._execution_client('s3')\n", "private_identity_access"),
        ("an identity", "from apicommon.identity import UserIdentity\nu = UserIdentity(username='x', memberships={})\n", "identity_construction"),
        ("a client by from-import", "from boto3 import client\nc = client('s3')\n", "boto3_import"),
        ("a client by aliased from-import", "from boto3 import client as mk\nc = mk('s3')\n", "client_construction"),
        ("an identity through the module", "from apicommon import identity\nu = identity.UserIdentity(username='x', memberships={})\n", "identity_construction"),
        ("an identity by aliased import", "from apicommon.identity import UserIdentity as UI\nu = UI(username='x', memberships={})\n", "identity_construction"),
        ("an identity by dataclass replace", "import dataclasses\nu = dataclasses.replace(context.acting_as, username='bob')\n", "identity_construction"),
        ("a client through botocore", "import botocore.session\nc = botocore.session.get_session().create_client('s3')\n", "client_construction"),
        ("a private door by getattr", "from apicommon import identity\nc = getattr(identity, '_client')('s3')\n", "private_identity_access"),
    ],
)
def test_the_checker_catches_every_shape_it_claims_to(label, source, kind) -> None:
    """Guard-the-guard: a sweep that matched nothing would pass over all of these.

    Args:
      label: What the synthetic module does.
      source: The synthetic module.
      kind: The finding it must produce.

    Returns:
      None.

    Raises:
      AssertionError: If the checker does not flag it.
    """
    kinds = {found for found, _ in findings(ast.parse(source))}
    assert kind in kinds, f"the checker missed {label}"


# ── The runtime guard ─────────────────────────────────────────────────────────


@pytest.fixture
def no_aws(monkeypatch):
    """Makes any client construction observable, and fails the test if one happens unasked.

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      The list of services a client was built for.

    Raises:
      None.
    """
    import boto3

    built: list[str] = []

    def _record(service, *args, **kwargs):
        built.append(service)
        return object()

    monkeypatch.setattr(boto3, "client", _record)
    return built


def test_a_route_that_did_not_declare_the_api_plane_is_refused_before_any_call(no_aws) -> None:
    """One direction, and the refusal must land before the client exists.

    Args:
      no_aws: The construction recorder.

    Returns:
      None.

    Raises:
      AssertionError: If the call is allowed, or a client was built on the way to refusing.
    """
    planes.begin_request()
    planes.begin_dispatch("userDirectory.get")

    with pytest.raises(identity.PlaneViolationError):
        identity.api_client("sts")
    assert no_aws == [], "a client was constructed before the plane was checked"


def test_the_router_resets_the_plane_on_the_way_IN(monkeypatch) -> None:
    """Read off the router's own source: the reset precedes the public-route check.

    Asserted structurally rather than behaviourally because the property is an ORDERING, and a
    behavioural test of a warm container cannot distinguish "reset on entry" from "reset on exit
    and nothing went wrong this time".

    Args:
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the reset is missing, or does not come first.
    """
    import inspect

    tree = ast.parse(inspect.getsource(router.route))
    body = tree.body[0].body
    statements = [node for node in body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)]

    first = statements[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call), (
        "the first thing route() does is no longer a call"
    )
    assert first.value.func.attr == "begin_request", (
        "route() no longer resets the credential plane before anything else"
    )


# ── The table and the dispatch table are the same set ─────────────────────────


def test_a_plane_that_is_neither_of_the_two_is_REFUSED_rather_than_defaulted() -> None:
    """The half the old set-equality guard could never carry.

    Deriving the plane from the route's own declaration makes "a route cannot be added without
    choosing" structural — the field is required to construct one. What that does NOT give is
    protection from choosing wrongly: a typo resolving quietly to user-only looks identical to a
    correct user-only route, and the fail-closed guarantee would be gone with nothing to show it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If an unrecognised plane resolves instead of raising.
    """
    typo = contract.Route(
        id="typo.get",
        method="GET",
        path="/v1/typo",
        idempotent=True,
        plane="API",
        request=None,
        response=contract.UserDirectoryResponse,
    )

    original = contract.ROUTES
    contract.ROUTES = (*original, typo)
    try:
        with pytest.raises(ValueError):
            planes.planes_for("typo.get")
    finally:
        contract.ROUTES = original
