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

Attributes:
  HERE: This function's package root.

Note on the ``conftest`` import below: it is at MODULE scope deliberately, matching the other
suites here. Inside a function it resolves at run time, by which point another package's
``conftest`` owns that name in ``sys.modules`` — green alone, ImportError in the full run.
  EXEMPT_MODULES: The modules allowed to construct a client, by exact relative path.
  FORBIDDEN_CLIENT_CALLS: The boto3 entry points that mint a client on default credentials.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import router
from apicommon import identity, planes
from conftest import bearer

HERE = pathlib.Path(__file__).resolve().parent

EXEMPT_MODULES = ("apicommon/identity.py",)
FORBIDDEN_CLIENT_CALLS = ("client", "resource", "Session")


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


def findings(tree) -> list[tuple[str, str]]:
    """Every way a module could reach AWS or an identity around the two doors.

    Returned as tagged findings rather than asserted here, so the same checker can be driven
    against a synthetic module that is supposed to be caught.

    Args:
      tree: The parsed module.

    Returns:
      A list of (kind, detail) pairs.

    Raises:
      None.
    """
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "boto3"
            and node.func.attr in FORBIDDEN_CLIENT_CALLS
        ):
            found.append(("client_construction", f"boto3.{node.func.attr}"))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "UserIdentity"
        ):
            found.append(("identity_construction", "UserIdentity"))
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("cpcommon.clients"):
                    found.append(("clients_import", alias.name))
                if alias.name == "boto3":
                    found.append(("boto3_import", alias.name))
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "cpcommon" and any(a.name == "clients" for a in node.names):
                found.append(("clients_import", "cpcommon.clients"))
            if module.startswith("cpcommon.clients"):
                found.append(("clients_import", module))
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
    assert len(modules) >= 6, f"the sweep's subject collapsed to {sorted(modules)}"
    for exempt in EXEMPT_MODULES:
        assert exempt in modules, f"{exempt} is exempted and does not exist"

    assert is_exempt("apicommon/identity.py")
    for near_miss in (
        "apicommon/identity_helpers.py",
        "apicommon/identity2.py",
        "routes/identity_self.py",
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
    assert builders <= set(EXEMPT_MODULES), f"{sorted(builders)} mint an identity"


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
    planes.begin_dispatch(("GET", "/_auth/whoami"))

    with pytest.raises(identity.PlaneViolationError):
        identity.api_client("sts")
    assert no_aws == [], "a client was constructed before the plane was checked"


def test_a_route_that_declared_the_api_plane_gets_its_client(no_aws, monkeypatch) -> None:
    """The other direction. One alone passes for a guard that always raises.

    Args:
      no_aws: The construction recorder.
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the declared route is refused.
    """
    monkeypatch.setitem(
        planes.ROUTE_PLANES, ("POST", "/_test/api-plane"), frozenset({planes.Plane.API})
    )
    planes.begin_request()
    planes.begin_dispatch(("POST", "/_test/api-plane"))

    identity.api_client("sts")
    assert no_aws == ["sts"]


def test_a_route_key_left_behind_by_the_last_request_authorizes_nothing(no_aws, monkeypatch) -> None:
    """THE case a two-direction test misses, driven as a sequence in one process.

    A warm container does not give each invocation a fresh context. Request A declares the API
    plane and raises partway through; request B is a user-only route. If the route key survives,
    B reaches the execution role and SUCCEEDS.

    Args:
      no_aws: The construction recorder.
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If the second request inherits the first's declaration.
    """
    monkeypatch.setitem(
        planes.ROUTE_PLANES, ("POST", "/_test/api-plane"), frozenset({planes.Plane.API})
    )

    planes.begin_request()
    planes.begin_dispatch(("POST", "/_test/api-plane"))
    identity.api_client("sts")

    planes.begin_request()
    planes.begin_dispatch(("GET", "/_auth/whoami"))
    with pytest.raises(identity.PlaneViolationError):
        identity.api_client("sts")


def test_the_api_plane_is_unreachable_with_no_dispatch_in_progress(no_aws) -> None:
    """The sentinel is not a key in the table, so it authorizes nothing.

    Args:
      no_aws: The construction recorder.

    Returns:
      None.

    Raises:
      AssertionError: If a client is handed out with no route running.
    """
    planes.begin_request()
    assert planes.current_route() == planes.NO_ROUTE
    with pytest.raises(identity.PlaneViolationError):
        identity.api_client("sts")
    assert no_aws == []


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


def test_the_entry_reset_is_what_saves_the_next_request_when_cleanup_is_SKIPPED(
    no_aws, monkeypatch
) -> None:
    """The entry reset, observed behaviourally — by taking the exit reset away.

    While cleanup always runs, the two resets are indistinguishable and only the source ordering
    tells them apart. So this simulates the case the entry reset exists for: a path that does not
    reach its cleanup. With ``end_dispatch`` neutered, request A's declaration is still in the
    context when request B arrives, and the ONLY thing that stops B reaching the execution role
    is the reset at the top of ``route``.

    Args:
      no_aws: The construction recorder.
      monkeypatch: pytest's patcher.

    Returns:
      None.

    Raises:
      AssertionError: If B inherits A's declaration.
    """
    def _api_plane_route(context):
        identity.api_client("sts")
        return {"ok": True}

    def _user_plane_route(context):
        identity.api_client("sts")
        return {"ok": True}

    monkeypatch.setitem(router.ROUTES, ("GET", "/_test/api-plane"), _api_plane_route)
    monkeypatch.setitem(router.ROUTES, ("GET", "/_test/user-plane"), _user_plane_route)
    monkeypatch.setitem(
        planes.ROUTE_PLANES, ("GET", "/_test/api-plane"), frozenset({planes.Plane.API})
    )
    monkeypatch.setitem(planes.ROUTE_PLANES, ("GET", "/_test/user-plane"), frozenset())
    monkeypatch.setattr(planes, "end_dispatch", lambda: None)

    router.route("GET", "/_test/api-plane", bearer())
    assert no_aws == ["sts"], "the declared route did not get its client"

    with pytest.raises(identity.PlaneViolationError):
        router.route("GET", "/_test/user-plane", bearer())


def test_a_public_route_leaves_the_plane_at_the_sentinel() -> None:
    """The health check runs before dispatch and must not inherit a declaration.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the public path leaves a route key behind.
    """
    planes.begin_dispatch(("POST", "/_test/api-plane"))
    router.route("GET", "/healthz", {})
    assert planes.current_route() == planes.NO_ROUTE


# ── The table and the dispatch table are the same set ─────────────────────────


def test_every_dispatched_route_declares_a_plane_and_every_declaration_dispatches() -> None:
    """Set equality, both sides derived. A hand-maintained list rots; this is what stops it.

    ``PUBLIC_ROUTES`` is excluded BY NAME rather than by a rule: the health check makes no AWS
    call, runs before dispatch, and is deliberately left at the sentinel — which authorizes
    nothing, so it needs no entry and must not have one. Recorded here because "the guard covers
    every route" and "the guard covers the routes it looks at" are otherwise indistinguishable.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the two sets differ, or a public route acquired a declaration.
    """
    assert set(planes.ROUTE_PLANES) == set(router.ROUTES), (
        f"declared {sorted(planes.ROUTE_PLANES)} but the router dispatches "
        f"{sorted(router.ROUTES)}"
    )
    assert not (set(planes.ROUTE_PLANES) & router.PUBLIC_ROUTES)
    assert planes.NO_ROUTE not in planes.ROUTE_PLANES


def test_the_user_plane_is_the_default_and_is_never_listed() -> None:
    """A route naming nothing gets the less privileged plane, which is the safe direction.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If any entry lists the user plane, or the user plane is ever refused.
    """
    for route_key, declared in planes.ROUTE_PLANES.items():
        assert planes.Plane.USER not in declared, (
            f"{route_key} lists the user plane — it is implicit, and listing it invites an "
            "entry that lists nothing to be read as declaring nothing rather than as user-only"
        )

    planes.begin_request()
    planes.require(planes.Plane.USER)
