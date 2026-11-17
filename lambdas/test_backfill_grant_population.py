"""The deploy role's invoke grant is scoped by a wildcard, so its population is swept.

The shared-space plane's deploy grant gives ``lambda:InvokeFunction`` on
``*-shared-space-backfill-*``. That pattern is not a list, so nothing stops a later function
whose suffix happens to start with ``backfill-`` from inheriting a grant nobody meant to give
it, and nothing would go red. The population is therefore derived from the plane's own function
map and asserted here, rather than being left as a pattern whose reach is assumed.

The second assertion is the one that matters: the grant must reach nothing the state machine
routes to. An invoke grant on a verb is an invoke grant on the delete cascade.
"""

import fnmatch
import pathlib
import re

import plane_grants
from tf_blocks import argument, map_entries, module_calls, span

REPO = pathlib.Path(__file__).resolve().parent.parent
PLANE = REPO / "infra" / "plane-shared-spaces.tf"
PLANE_CALL = "shared_spaces"
DEFINITION = REPO / "infra" / "planes" / "shared-spaces" / "state-machine.asl.json.tftpl"
MODULE_LOCALS = REPO / "infra" / "modules" / "control-plane" / "locals.tf"
#: The placeholder account these tests build their probe ARNs with. The templates pin a
#: VARIABLE, so this need not be the real account — but it must be the same value this file
#: renders `${account_id}` as, or every probe ARN lands in a different account from the
#: pattern it is checked against and the coverage assertions all pass vacuously.
ACCOUNT_ID = "123456789012"

#: The plane's key in the deploy role's map of control-plane grants.
GRANT_PLANE = "shared-space"

#: The wildcard's middle, as it appears in the granted ARN pattern.
GRANT_INFIX = "-shared-space-backfill-"


def _routed_suffixes():
    """The plane's functions the state machine routes to, derived from its definition.

    Every verb reaches the definition as ``<verb>_function_arn``, so the routed verbs are exactly
    the placeholders its template uses.

    Args:
      None.

    Returns:
      The routed function suffixes.

    Raises:
      AssertionError: When the definition names a placeholder that is not this plane's function.
    """
    by_placeholder = {suffix.replace("-", "_"): suffix for suffix in _function_suffixes()}
    placeholders = set(re.findall(r"\$\{([a-z0-9_]+)_function_arn\}", DEFINITION.read_text()))
    unknown = placeholders - set(by_placeholder)
    assert not unknown, f"the definition routes to {sorted(unknown)}, which are not this plane's functions"
    return {by_placeholder[name] for name in placeholders}


def _function_suffixes():
    """Every key of the plane's ``shared_space_functions`` map, the one its root call passes.

    Args:
      None.

    Returns:
      The function suffixes, which are also the ``lambdas/`` directory suffixes.

    Raises:
      AssertionError: If the call no longer passes that local, so the keys read here would not be
        the functions it deploys.
      ValueError: If the local is not declared.
    """
    text = PLANE.read_text()
    passed = argument(module_calls(text)[PLANE_CALL], "functions")
    assert passed == "local.shared_space_functions", f"the {PLANE_CALL} call passes {passed}"
    declared = re.search(r"(?m)^\s*shared_space_functions\s*=\s*\{", text)
    assert declared, f"{PLANE.name} declares no shared_space_functions"
    return set(map_entries(span(text, declared.end() - 1)))


def test_the_function_sweep_found_the_plane():
    """Guards the guard: an empty parse makes every assertion below vacuously true."""
    suffixes = _function_suffixes()
    assert len(suffixes) >= 9, suffixes
    assert "delete" in suffixes and "validate" in suffixes


def test_exactly_one_function_is_reachable_by_the_backfill_invoke_grant():
    matching = sorted(s for s in _function_suffixes() if s.startswith("backfill-"))

    assert matching == ["backfill-ever-active"], (
        f"the deploy role's {GRANT_INFIX}* invoke grant now reaches {matching}. "
        "Either narrow the grant or say why the new function may be invoked from CI."
    )


def test_the_invoke_grant_reaches_nothing_the_state_machine_routes_to():
    routed = _routed_suffixes()
    granted = {s for s in _function_suffixes() if s.startswith("backfill-")}

    assert routed, f"no routed verbs parsed from {DEFINITION.name}"
    assert routed & granted == set(), f"the invoke grant reaches routed verbs: {sorted(routed & granted)}"


#: The grant's invoke statements by Sid. Exactly these: a third one the core gained would leave
#: every assertion here green while it widened the reach.
INVOKE_SIDS = {"SharedSpaceBackfillInvoke", "SharedSpaceReportInvoke"}


def _invoke_statement(sid="SharedSpaceBackfillInvoke"):
    """One statement granting the invoke, as its own JSON object.

    Read from the plane's composed grant, which ``plane_grants`` renders the way Terraform does,
    and the grant's invoke statements are required to be exactly ``INVOKE_SIDS``.

    Args:
      sid: The statement to return.

    Returns:
      The statement with that Sid.

    Raises:
      AssertionError: When the grant's invoke statements are not exactly ``INVOKE_SIDS``.
    """
    values = {"aws_region": "us-east-1", "project_name": "dat", "account_id": ACCOUNT_ID}
    values = {name: values.get(name, "placeholder") for name in plane_grants.template_variables()}
    document = plane_grants.document(plane_grants.grants()[GRANT_PLANE], values)
    invokes = {s.get("Sid"): s for s in document["Statement"] if "lambda:InvokeFunction" in s["Action"]}
    assert set(invokes) == INVOKE_SIDS and len(invokes) == len(
        [s for s in document["Statement"] if "lambda:InvokeFunction" in s["Action"]]
    ), f"the {GRANT_PLANE} grant's invoke statements are {sorted(invokes)}, not {sorted(INVOKE_SIDS)}"
    return invokes[sid]


def test_the_grant_is_scoped_to_that_prefix_and_not_to_the_whole_plane():
    statement = _invoke_statement()

    assert statement["Action"] == "lambda:InvokeFunction"
    assert GRANT_INFIX in statement["Resource"], statement["Resource"]
    assert not statement["Resource"].endswith("shared-space-*"), (
        "the invoke is scoped to the whole plane, which reaches every verb"
    )


def test_the_granted_pattern_actually_matches_the_deployed_function_name():
    """The trailing hyphen is load-bearing and the coupling is otherwise pinned nowhere.

    IAM's ``*`` matches zero or more characters, so the granted pattern needs the literal
    ``-shared-space-backfill-`` **including its trailing hyphen** — a function suffix of plain
    ``backfill`` renders a name the grant does not match, which is the same shape as the
    archive-bucket trap in ``infra/modules/base/README.md``. Rather than restate the name, this
    renders it the way the control-plane module's ``locals.tf`` does, with the plane's ``name``
    from its root call, and matches it against the pattern the policy actually grants, so either
    side moving alone fails here rather than as an AccessDenied in CI.
    """
    pattern = _invoke_statement()["Resource"]
    # Rendered from the module's OWN template, not restated here: a hard-coded name pins the
    # policy side only, so renaming the template would silently stop this from testing anything.
    template = re.search(
        r"verb => \"([^\"]+)\"", MODULE_LOCALS.read_text().split("function_names", 1)[1]
    ).group(1)
    plane_name = re.fullmatch(r'"([a-z0-9-]+)"', argument(module_calls(PLANE.read_text())[PLANE_CALL], "name"))
    assert plane_name, f"the {PLANE_CALL} call's name is not a literal"

    for suffix in (s for s in _function_suffixes() if s.startswith("backfill-")):
        name = (
            template.replace("${var.project_name}", "dat")
            .replace("${var.environment}", "prod")
            .replace("${var.name}", plane_name.group(1))
            .replace("${verb}", suffix)
        )
        assert "${" not in name, f"unresolved interpolation in the rendered name: {name}"
        arn = f"arn:aws:lambda:us-east-1:123456789012:function:{name}"
        assert fnmatch.fnmatchcase(arn, pattern), f"{name} is not reachable by the grant {pattern}"

    unreachable = "arn:aws:lambda:us-east-1:123456789012:function:dat-prod-shared-space-backfill"
    assert not fnmatch.fnmatchcase(unreachable, pattern), (
        "a suffix of plain 'backfill' now matches, so this test no longer pins the trailing hyphen"
    )


def test_the_report_grant_names_exactly_the_report_and_no_routed_verb():
    """The report's invoke is one exact name, not a prefix, so its population is one function.

    A pattern with a trailing wildcard would reach whatever is named after it later; the exact
    name reaches the report and nothing else, and the report is not a function the machine routes
    to, so the grant is not an invoke on any verb.
    """
    pattern = _invoke_statement("SharedSpaceReportInvoke")["Resource"]
    assert pattern.endswith(":function:dat-*-shared-space-name-collisions"), pattern
    reached = {
        suffix
        for suffix in _function_suffixes()
        if fnmatch.fnmatchcase(f"arn:aws:lambda:us-east-1:{ACCOUNT_ID}:function:dat-prod-shared-space-{suffix}", pattern)
    }
    assert reached == {"name-collisions"}, reached
    assert reached & _routed_suffixes() == set()
