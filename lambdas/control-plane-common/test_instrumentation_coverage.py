"""The fleet-wide instrumentation coverage harness (SPEC-128 FR-001/FR-003, SPEC-134 FR-007).

**Partial instrumentation is worse than none:** a run that shows eight of nine verbs looks like a
run that STOPPED at eight. So every plane's verbs are ENUMERATED from disk rather than listed, and
a tenth verb cannot be added without either instrumenting it or failing here.

This started as one module in `data-quality-common`. It moved here when the second plane needed
it, because four planes each keeping their own copy of an enumeration test is how three of them
end up subtly different — the same argument that put the emitters behind one door in SPEC-130.
Adding a plane is exactly one :class:`Plane` entry.
"""

import ast
import pathlib
from dataclasses import dataclass, field

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Plane:
    """One control plane's coverage expectations.

    ``notifies_on_failure`` is the field worth reading twice. Data-quality, table-builder and
    table-share wrap every handler in ``@notify.notifies_on_failure``, and ``@traced`` MUST sit
    above it or a failed-and-notified invocation closes its span ``status: "ok"``. **Shared-space
    carries no such decorator** — its verbs notify explicitly from inside the handler — so there
    `@traced` is simply the only decorator, and the ordering rule does not apply.

    That difference is declared rather than discovered: someone reading three planes will see the
    ordering rule stated three times and reasonably assume it was forgotten on the fourth
    (SPEC-134 FR-002).
    """

    service: str
    glob: str
    module_prefix: str
    verb_count: int
    notifies_on_failure: bool
    not_verbs: frozenset = field(default_factory=frozenset)

    def modules(self):
        for directory in sorted(LAMBDAS.glob(self.glob)):
            if not directory.is_dir() or directory.name in self.not_verbs:
                continue
            for path in directory.glob(f"{self.module_prefix}*.py"):
                if path.name.startswith("test_"):
                    continue
                yield path


PLANES = [
    Plane(
        service="data-quality",
        glob="data-quality-*",
        module_prefix="dq_",
        verb_count=9,
        notifies_on_failure=True,
        not_verbs=frozenset({"data-quality-common", "data-quality-polars"}),
    ),
    Plane(
        service="shared-space",
        glob="shared-space-*",
        module_prefix="",
        verb_count=8,
        # Its verbs notify explicitly from inside the handler — see Plane's docstring.
        notifies_on_failure=False,
        not_verbs=frozenset({"shared-space-common"}),
    ),
]

#: Every (plane, module) pair, so a failure names the file rather than just the plane.
MODULES = [(plane, path) for plane in PLANES for path in plane.modules()]
_IDS = [f"{plane.service}:{path.stem}" for plane, path in MODULES]


def _decorators(path):
    """The decorator source lines applied to `handler`, outermost first."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "handler":
            return [ast.unparse(d) for d in node.decorator_list]
    return None


def _emitter_calls(path):
    """Every `observability.info/warning/error(...)` call, as AST nodes.

    AST rather than a substring search, so a mention inside a docstring or a comment cannot
    satisfy the guard — the point is that the verb *emits*, not that it talks about emitting.
    """
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Call) and ast.unparse(node.func) in (
            "observability.info",
            "observability.warning",
            "observability.error",
        ):
            yield node


#: Field names that would carry data read out of a user's file. Name-based and therefore
#: IMPERFECT — the real rule turns on provenance (did this value come from inside a file), which
#: no name test can see. A tripwire for the obvious mistake, not the enforcement.
#:
#: `rows` is here even though a row COUNT is a legitimate thing to log: a count is spelled
#: `row_count`. The tripwire is valuable because it is dumb and strict, and a field an author has
#: to argue is fine is a field whose name should say so instead. (It caught exactly that in
#: assemble-report on its first run — SPEC-132.)
CONTENTS_DENYLIST = {
    "value", "values", "sample", "samples", "row", "rows", "cell", "content", "contents",
    "preview", "head", "text", "token", "id_token",
}

#: Credential-shaped keyword names, banned on any emitter or baggage call.
CREDENTIAL_NAMES = {"id_token", "idtoken", "token", "access_token", "credentials", "authorization"}


@pytest.mark.parametrize("plane", PLANES, ids=lambda p: p.service)
def test_the_enumeration_actually_found_the_verbs(plane):
    """Guards the guard: a glob that matches nothing makes every test below vacuous.

    The count is a LITERAL per plane, so finding too few fails instead of passing quietly.
    """
    found = [p.stem for p in plane.modules()]
    assert len(found) == plane.verb_count, (
        f"{plane.service}: expected {plane.verb_count} verb modules, found {found}"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_every_verb_handler_is_traced(plane, path):
    decorators = _decorators(path)
    assert decorators is not None, f"{path.name} exposes no `handler`"
    assert any(d.startswith("observability.traced(") for d in decorators), (
        f"{path.name}'s handler is not traced — a run would show one verb short and look truncated"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_every_verb_initialises_its_control_plane_service(plane, path):
    expected = f'observability.init(service="{plane.service}")'
    assert expected in path.read_text(), (
        f"{path.name} must init with the CONTROL PLANE name, not the function — "
        f"a plane's verbs are only one queryable set if they share it"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_the_decorator_expectation_for_this_plane_holds(plane, path):
    """Two different rules, and which one applies is declared on the Plane (FR-002).

    Where `notifies_on_failure` is used it catches on its way OUT, so `@traced` must sit above
    it — otherwise the span closes `status="ok"` on an invocation that actually failed and
    notified, and the traces say the pipeline is healthy while users receive failure messages.

    Where it is not used, `@traced` must be the ONLY decorator: this test then fails if someone
    later adds `notifies_on_failure` without also establishing the ordering.
    """
    decorators = _decorators(path)
    traced_idx = next(i for i, d in enumerate(decorators) if d.startswith("observability.traced("))
    notify_idx = next(
        (i for i, d in enumerate(decorators) if d.startswith("notify.notifies_on_failure(")), None
    )

    if not plane.notifies_on_failure:
        assert len(decorators) == 1, (
            f"{path.name}: this plane notifies from INSIDE the handler, so @traced is the only "
            f"decorator. Adding {decorators} means the ordering rule now applies — declare it on "
            f"the Plane."
        )
        return

    if notify_idx is None:
        pytest.skip("this verb IS the failure handler and has no notifies_on_failure")
    assert traced_idx < notify_idx, (
        f"{path.name}: @traced must sit ABOVE @notifies_on_failure, or failed invocations "
        "close their span as ok"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_every_verb_narrates_and_not_only_traces(plane, path):
    """A verb that traces but never narrates is worse than one that does neither: in a query
    filtered to narrative events it looks exactly like a verb that never ran.
    """
    assert list(_emitter_calls(path)), (
        f"{path.name} opens a span and says nothing inside it — see SPEC-132 FR-001"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_no_emitter_passes_a_contents_shaped_field(plane, path):
    """`logs/` is retained forever, and these functions hold users' data in memory."""
    offenders = [
        f"{ast.unparse(node.func)}({kw.arg}=...)"
        for node in _emitter_calls(path)
        for kw in node.keywords
        if kw.arg and kw.arg.lower() in CONTENTS_DENYLIST
    ]
    assert not offenders, (
        f"{path.name} logs a contents-shaped field: {offenders} — column NAMES are schema and are "
        "permitted; column VALUES are file contents and are not (SPEC-132 FR-004)"
    )


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_no_verb_enables_argument_or_return_capture(plane, path):
    """The single setting that would turn every traced verb into a data-exfiltration path."""
    source = path.read_text()
    for banned in ("capture_args", "capture_return", "capture=", "include_args"):
        assert banned not in source, f"{path.name} enables {banned}"


@pytest.mark.parametrize(("plane", "path"), MODULES, ids=_IDS)
def test_no_verb_puts_a_credential_into_a_log_field(plane, path):
    """No ID token, or any part of one, is ever a log field — regardless of provenance."""
    offenders = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        if not (func.startswith("lf.") or func.endswith("set_baggage") or ".info" in func
                or func.startswith("observability.")):
            continue
        for kw in node.keywords:
            if kw.arg and kw.arg.lower().replace("-", "_") in CREDENTIAL_NAMES:
                offenders.append(f"{func}({kw.arg}=...)")
    assert not offenders, f"{path.name} logs a credential-shaped field: {offenders}"


@pytest.mark.parametrize("plane", PLANES, ids=lambda p: p.service)
def test_the_service_name_survives_the_sweeps_routing_rule(plane):
    """A `service` failing SERVICE_RE does not error — it quietly files every one of that
    plane's events under logs/_unrouted/ (SPEC-129). Checked against the sweep's OWN pattern.
    """
    import re

    sweep = (LAMBDAS / "log-sweep" / "log_sweep.py").read_text()
    pattern = re.search(r'SERVICE_RE = re\.compile\(r"(.+?)"\)', sweep).group(1)
    assert re.match(pattern, plane.service), (
        f"{plane.service!r} would be routed to logs/_unrouted/"
    )
