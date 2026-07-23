"""SPEC-128 FR-001/FR-003 — every data-quality verb is traced, and nothing sensitive is logged.

Partial instrumentation is worse than none: a run that shows eight of nine verbs looks like a
run that STOPPED at eight. So this enumerates the verb directories rather than listing them, and
a tenth verb cannot be added without either instrumenting it or failing here. Mirrors the
descriptor-coverage test SPEC-126 FR-001 used for the same reason.
"""

import ast
import pathlib

import pytest

LAMBDAS = pathlib.Path(__file__).resolve().parent.parent

#: Directories that are layers, not verbs — they ship shared code and expose no handler.
NOT_VERBS = {"data-quality-common", "data-quality-polars"}


def _verb_modules():
    for d in sorted(LAMBDAS.glob("data-quality-*")):
        if not d.is_dir() or d.name in NOT_VERBS:
            continue
        for path in d.glob("dq_*.py"):
            if path.name.startswith("test_"):
                continue
            yield path


def _decorators(path):
    """Return the decorator source lines applied to `handler`, outermost first."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "handler":
            return [ast.unparse(d) for d in node.decorator_list]
    return None


VERB_MODULES = list(_verb_modules())


def test_the_enumeration_actually_found_the_verbs():
    """Guards the guard: a glob that matches nothing would make every test below vacuous."""
    assert len(VERB_MODULES) == 9, f"expected 9 verb modules, found {[p.name for p in VERB_MODULES]}"


@pytest.mark.parametrize("path", VERB_MODULES, ids=lambda p: p.parent.name)
def test_every_verb_handler_is_traced(path):
    decorators = _decorators(path)
    assert decorators is not None, f"{path.name} exposes no `handler`"
    assert any(
        d.startswith("observability.traced(") for d in decorators
    ), f"{path.name}'s handler is not traced — a run would show 8 of 9 verbs and look truncated"


@pytest.mark.parametrize("path", VERB_MODULES, ids=lambda p: p.parent.name)
def test_every_verb_initialises_the_control_plane_service(path):
    source = path.read_text()
    assert 'observability.init(service="data-quality")' in source, (
        f"{path.name} must init with the CONTROL PLANE name, not the function — "
        "the nine verbs are only one queryable set if they share it"
    )


@pytest.mark.parametrize("path", VERB_MODULES, ids=lambda p: p.parent.name)
def test_traced_is_outermost_above_notifies_on_failure(path):
    """FR-001: notifies_on_failure catches on its way out.

    If it were outermost, the span would close `status="ok"` on an invocation that actually
    failed and notified — the traces would say the pipeline was healthy while users received
    failure notifications.
    """
    decorators = _decorators(path)
    notify_idx = next(
        (i for i, d in enumerate(decorators) if d.startswith("notify.notifies_on_failure(")), None
    )
    if notify_idx is None:
        pytest.skip("notify-failure has no notifies_on_failure — it IS the failure handler")
    traced_idx = next(i for i, d in enumerate(decorators) if d.startswith("observability.traced("))
    assert traced_idx < notify_idx, (
        f"{path.name}: @traced must sit ABOVE @notifies_on_failure, or failed invocations "
        "close their span as ok"
    )


# -- FR-003: what must never become a field --------------------------------------------


@pytest.mark.parametrize("path", VERB_MODULES, ids=lambda p: p.parent.name)
def test_no_verb_enables_argument_or_return_capture(path):
    """The single setting that would turn every traced verb into a data-exfiltration path.

    log-foundry captures nothing by default; these logs land in S3 and are retained forever
    (SPEC-127 FR-009), and everything a verb touches is either a bearer credential or someone's
    data.
    """
    source = path.read_text()
    for banned in ("capture_args", "capture_return", "capture=", "include_args"):
        assert banned not in source, f"{path.name} enables {banned} — see FR-003"


@pytest.mark.parametrize("path", VERB_MODULES, ids=lambda p: p.parent.name)
def test_no_verb_puts_a_token_into_a_log_field(path):
    """No ID token, or any part of one, is ever a log field (same posture as SPEC-126 FR-004).

    Scans `lf.info`/`set_baggage`-style call sites for token-shaped argument names.
    """
    source = path.read_text()
    tree = ast.parse(source)
    banned_names = {"id_token", "idToken", "token", "access_token", "credentials", "authorization"}
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        if not (func.startswith("lf.") or func.endswith("set_baggage") or ".info" in func):
            continue
        for kw in node.keywords:
            if kw.arg and kw.arg.lower().replace("-", "_") in banned_names:
                offenders.append(f"{func}({kw.arg}=...)")
    assert not offenders, f"{path.name} logs a credential-shaped field: {offenders}"
