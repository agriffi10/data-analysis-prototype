"""The deploy role's invoke grant is scoped by a wildcard, so its population is swept.

``github-actions-deploy-shared-spaces.json.tftpl`` grants ``lambda:InvokeFunction`` on
``*-shared-space-backfill-*``. That pattern is not a list, so nothing stops a later function
whose suffix happens to start with ``backfill-`` from inheriting a grant nobody meant to give
it, and nothing would go red. The population is therefore derived from the plane's own function
map and asserted here, rather than being left as a pattern whose reach is assumed.

The second assertion is the one that matters: the grant must reach nothing the state machine
routes to. An invoke grant on a verb is an invoke grant on the delete cascade.
"""

import fnmatch
import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
LOCALS = REPO / "infra" / "modules" / "shared-spaces" / "locals.tf"
STEPFUNCTION = REPO / "infra" / "modules" / "shared-spaces" / "stepfunction.tf"
#: The placeholder account these tests build their probe ARNs with. The templates pin a
#: VARIABLE, so this need not be the real account — but it must be the same value this file
#: renders `${account_id}` as, or every probe ARN lands in a different account from the
#: pattern it is checked against and the coverage assertions all pass vacuously.
ACCOUNT_ID = "123456789012"

DEPLOY_POLICY = (
    REPO / "infra" / "modules" / "base" / "policies" / "github-actions-deploy-shared-spaces.json.tftpl"
)

#: The wildcard's middle, as it appears in the granted ARN pattern.
GRANT_INFIX = "-shared-space-backfill-"


def _function_suffixes():
    """Every key of the plane's ``shared_space_functions`` map.

    Args:
      None.

    Returns:
      The function suffixes, which are also the ``lambdas/`` directory suffixes.

    Raises:
      None.
    """
    body = LOCALS.read_text().split("shared_space_functions = {", 1)[1].split("\n  }", 1)[0]
    return {m.group(1) for m in re.finditer(r'^\s*"([a-z0-9-]+)"\s*=', body, re.MULTILINE)}


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
    # The machine is wired with one explicit ARN per verb, so the verbs are exactly the
    # functions named in its templatefile block — derived, not listed here.
    routed = set(
        re.findall(r'module\.functions\["([a-z0-9-]+)"\]', STEPFUNCTION.read_text())
    )
    granted = {s for s in _function_suffixes() if s.startswith("backfill-")}

    assert routed, "no routed verbs parsed from stepfunction.tf"
    assert routed & granted == set(), f"the invoke grant reaches routed verbs: {sorted(routed & granted)}"


def _invoke_statement():
    """The statement granting the invoke, as its own JSON object.

    Parsed rather than sliced out of the raw text: the template's own ``${aws_region}`` carries a
    closing brace, so splitting the document on one truncates the statement before its resource
    and the assertion below passes on a policy that says nothing. The interpolations are replaced
    with plausible values first, which is what makes the document parseable at all.

    Args:
      None.

    Returns:
      The statement whose Sid grants the backfill invoke.

    Raises:
      StopIteration: When no such statement exists.
    """
    rendered = DEPLOY_POLICY.read_text()
    for marker, value in (
        ("${aws_region}", "us-east-1"),
        ("${project_name}", "dat"),
        ("${account_id}", ACCOUNT_ID),
    ):
        rendered = rendered.replace(marker, value)
    rendered = re.sub(r"\$\{\w+\}", "arn:aws:s3:::placeholder", rendered)
    document = json.loads(rendered)
    return next(s for s in document["Statement"] if s.get("Sid") == "SharedSpaceBackfillInvoke")


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
    renders it the way ``locals.tf`` does and matches it against the pattern the policy actually
    grants, so either side moving alone fails here rather than as an AccessDenied in CI.
    """
    pattern = re.search(r'"(arn:aws:lambda:[^"]*backfill[^"]*)"', DEPLOY_POLICY.read_text()).group(1)
    pattern = (
        pattern.replace("${aws_region}", "us-east-1")
        .replace("${project_name}", "dat")
        .replace("${account_id}", ACCOUNT_ID)
    )
    # Rendered from locals.tf's OWN template, not restated here: a hard-coded name pins the
    # policy side only, so renaming the template would silently stop this from testing anything.
    template = re.search(
        r"suffix => \"([^\"]+)\"", LOCALS.read_text().split("shared_space_function_names", 1)[1]
    ).group(1)

    for suffix in (s for s in _function_suffixes() if s.startswith("backfill-")):
        name = (
            template.replace("${var.project_name}", "dat")
            .replace("${var.environment}", "prod")
            .replace("${suffix}", suffix)
        )
        assert "${" not in name, f"unresolved interpolation in the rendered name: {name}"
        arn = f"arn:aws:lambda:us-east-1:123456789012:function:{name}"
        assert fnmatch.fnmatchcase(arn, pattern), f"{name} is not reachable by the grant {pattern}"

    unreachable = "arn:aws:lambda:us-east-1:123456789012:function:dat-prod-shared-space-backfill"
    assert not fnmatch.fnmatchcase(unreachable, pattern), (
        "a suffix of plain 'backfill' now matches, so this test no longer pins the trailing hyphen"
    )
