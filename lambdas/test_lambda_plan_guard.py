"""The plan guard is driven over real plan SHAPES, including the one that makes it subtle.

The guard compares two plans that are not the same kind of document. A **no-op** plan carries
refreshed values for every attribute, including ones the configuration never set. A **replacement**
plan carries only what the configuration sets, and marks the rest unknown — where "unknown" means
*absent from `after`*, not present-and-different. Every test here that matters is about that
asymmetry, because it is the one a fixture comparison gets wrong by default and gets wrong
silently.

The guard is pure and offline for exactly this reason: the plans it reads can only be produced in
CI, so its behaviour has to be pinned against documents written by hand.

Attributes:
  ADDED_SINCE_THE_CUTOVER: Every function declared since the fixture was frozen. Named rather
    than counted, so an unexpected addition — a directory that became a function by accident —
    fails by name rather than shrinking silently into a tolerated difference.
  GUARD: The script under test, imported by path because `.github/scripts` is not a package.
  TABLE: The fleet derivation's shape, naming the two functions the fixtures use.
"""

import importlib.util
import json
import pathlib

import fleet
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARD_PATH = ROOT / ".github" / "scripts" / "lambda_plan_guard.py"

_spec = importlib.util.spec_from_file_location("lambda_plan_guard", GUARD_PATH)
GUARD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(GUARD)

TABLE = [{"name": "archive-copy-objects"}, {"name": "api"}]


def _resource(name, after, unknown=None, address=None):
    """One `resource_changes` entry for a Lambda function.

    Args:
      name: The deployed function name.
      after: The planned attribute values.
      unknown: The `after_unknown` map, defaulting to nothing unknown.
      address: The resource address, defaulting to one derived from the name.

    Returns:
      A resource-change document.

    Raises:
      None.
    """
    return {
        "address": address or f'module.x.aws_lambda_function.functions["{name}"]',
        "type": "aws_lambda_function",
        "change": {
            "after": {"function_name": name, **after},
            "after_unknown": unknown or {},
        },
    }


def _zip_after(**overrides):
    """The attribute set a NO-OP plan carries for a zip function — everything refreshed.

    Args:
      **overrides: Fields to replace.

    Returns:
      The `after` map.

    Raises:
      None.
    """
    return {
        "package_type": "Zip",
        "handler": "archive_copy_objects.handler",
        "environment": [{"variables": {"ADMIN_BUCKET": "b"}}],
        "timeout": 60,
        "memory_size": 128,
        "architectures": ["x86_64"],
        "role": "arn:aws:iam::1:role/exec",
        "reserved_concurrent_executions": -1,
        "vpc_config": [],
        **overrides,
    }


@pytest.fixture
def pre_cutover():
    """A no-op plan over two zip functions.

    Args:
      None.

    Returns:
      The plan document.

    Raises:
      None.
    """
    return {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after()),
            _resource("dat-prod-api", _zip_after(timeout=29, memory_size=256,
                                                 handler="handler.handler")),
        ]
    }


@pytest.fixture
def fixture(pre_cutover):
    """The frozen capture taken from that plan.

    Args:
      pre_cutover: The no-op plan.

    Returns:
      The fixture document.

    Raises:
      None.
    """
    return GUARD.capture(pre_cutover)


def _permission(bound, unknown=False, address="module.x.aws_lambda_permission.p"):
    """One `resource_changes` entry for a Lambda permission.

    Args:
      bound: The planned `function_name`.
      unknown: Whether it is unknown, as it is while the function it names is replaced.
      address: The resource address.

    Returns:
      A resource-change document.

    Raises:
      None.
    """
    return {
        "address": address,
        "type": "aws_lambda_permission",
        "change": {
            "actions": ["create"],
            "after": {"function_name": bound},
            "after_unknown": {"function_name": True} if unknown else {},
        },
    }


GOOD_PERMISSION = _permission("arn:aws:lambda:us-east-1:1:function:dat-prod-api")


def _check_with_table(plan, fixture, table, package_type="Zip", image_repository=None):
    """`_check` for the cases that supply their own fleet derivation.

    Args:
      plan: The plan to check.
      fixture: The frozen capture.
      table: The fleet derivation to compare the plan against.
      package_type: The packaging every function must have.
      image_repository: The registry every image_uri must name.

    Returns:
      The list of problems.

    Raises:
      None.
    """
    changes = plan.get("resource_changes", [])
    if not any(change.get("type") == "aws_lambda_permission" for change in changes):
        plan = {**plan, "resource_changes": [*changes, GOOD_PERMISSION]}
    return GUARD.check(plan, fixture, package_type, image_repository, table, "dat", "prod")


def _check(plan, fixture, package_type="Zip", image_repository=None):
    """Runs the guard's check with this module's fixed project and environment.

    A real root plan always carries permissions, and the guard refuses one that does not — so a
    plan built here to say something about FUNCTIONS is given a correctly-bound permission unless
    it supplies its own. Without that, every test in this file would be asserting about the
    permission rule by accident.

    Args:
      plan: The plan to check.
      fixture: The frozen capture.
      package_type: The packaging every function must have.
      image_repository: The registry every image_uri must name.

    Returns:
      The list of problems.

    Raises:
      None.
    """
    changes = plan.get("resource_changes", [])
    if not any(change.get("type") == "aws_lambda_permission" for change in changes):
        plan = {**plan, "resource_changes": [*changes, GOOD_PERMISSION]}
    return GUARD.check(plan, fixture, package_type, image_repository, TABLE, "dat", "prod")


def test_a_clean_pre_cutover_plan_has_no_problems(pre_cutover, fixture):
    """The baseline. Without it every "found no problems" below means nothing.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When the guard objects to the world as it is.
    """
    assert _check(pre_cutover, fixture) == []


def test_the_fixture_is_keyed_by_name_so_the_cutover_s_address_change_does_not_break_it(fixture):
    """The addresses move; the names do not.

    An address-keyed fixture would match nothing after the cutover and the comparison would pass
    having compared nothing — the exact failure mode this guard exists to avoid.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When the fixture is keyed by anything but the deployed name.
    """
    assert set(fixture["functions"]) == {"dat-prod-archive-copy-objects", "dat-prod-api"}

    moved = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after(),
                      address='module.x.module.fns["copy-objects"].aws_lambda_function.this'),
            _resource("dat-prod-api", _zip_after(timeout=29, memory_size=256,
                                                 handler="handler.handler"),
                      address="module.api.module.fn.aws_lambda_function.this"),
        ]
    }
    assert _check(moved, fixture) == []


def test_an_unknown_parity_field_is_a_failure_not_a_skip(pre_cutover, fixture):
    """The asymmetry, asserted directly. This is the finding the guard is built around.

    A replacement plan omits any attribute the configuration does not set. Reading that as "no
    change" makes the comparison vacuous for precisely the fields most likely to have moved —
    memory and architecture — so it is a hard failure instead, and the module declares them.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When an unknown field passes silently.
    """
    replacement = {
        "resource_changes": [
            _resource(
                "dat-prod-archive-copy-objects",
                {k: v for k, v in _zip_after().items() if k != "memory_size"},
                unknown={"memory_size": True},
            ),
            _resource("dat-prod-api", _zip_after(timeout=29, memory_size=256,
                                                 handler="handler.handler")),
        ]
    }
    problems = _check(replacement, fixture)
    assert any("memory_size is UNKNOWN" in p for p in problems), problems


def test_a_changed_parity_field_is_named_with_both_values(pre_cutover, fixture):
    """The message has to say what moved, not that something did.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When a changed field goes unreported or unnamed.
    """
    changed = json.loads(json.dumps(pre_cutover))
    changed["resource_changes"][0]["change"]["after"]["timeout"] = 900
    problems = _check(changed, fixture)
    assert any("timeout moved from 60 to 900" in p for p in problems), problems


def test_a_function_left_on_zip_by_a_partial_cutover_fails(fixture):
    """Derived from the plan, so a function left behind fails rather than being missed.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When a stale function passes an Image check.
    """
    half = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after(
                package_type="Image", handler=None,
                image_uri="123.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda:abc",
                image_config=[{"command": ["archive_copy_objects.handler"]}])),
            _resource("dat-prod-api", _zip_after(timeout=29, memory_size=256,
                                                 handler="handler.handler")),
        ]
    }
    problems = _check(half, fixture, "Image",
                      "123.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda")
    assert any("dat-prod-api: package_type is 'Zip'" in p for p in problems), problems


def test_a_command_that_is_not_the_old_handler_fails(fixture):
    """The command is derived from the FIXTURE, never from the new code.

    Deriving both sides from the cutover would make them agree with each other and with nothing
    else — the mistake SPEC-212's review caught once already, where an expected count and an
    observed count fell together and matched.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When a wrong command passes.
    """
    repo = "123.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda"
    wrong = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after(
                package_type="Image", handler=None, image_uri=f"{repo}:abc",
                image_config=[{"command": ["archive_copy_objects.handlr"]}])),
            _resource("dat-prod-api", _zip_after(
                package_type="Image", handler=None, timeout=29, memory_size=256,
                image_uri=f"{repo}:abc", image_config=[{"command": ["handler.handler"]}])),
        ]
    }
    problems = _check(wrong, fixture, "Image", repo)
    assert any("handlr" in p and "expected" in p for p in problems), problems


def test_an_image_from_the_wrong_repository_fails(fixture):
    """One fleet, one image. A function pointing elsewhere is not part of it.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When a foreign repository passes.
    """
    repo = "123.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda"
    foreign = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after(
                package_type="Image", handler=None,
                image_uri="123.dkr.ecr.us-east-1.amazonaws.com/somewhere-else:abc",
                image_config=[{"command": ["archive_copy_objects.handler"]}])),
            _resource("dat-prod-api", _zip_after(
                package_type="Image", handler=None, timeout=29, memory_size=256,
                image_uri=f"{repo}:abc", image_config=[{"command": ["handler.handler"]}])),
        ]
    }
    problems = _check(foreign, fixture, "Image", repo)
    assert any("does not name the fleet's repository" in p for p in problems), problems


def test_the_plan_and_the_deploy_table_must_name_the_same_fleet(pre_cutover, fixture):
    """This is the link that lets `Deploy Lambdas` count against the table.

    The pipeline points every function the table names and fails on a shortfall; what makes that
    a check against TERRAFORM rather than against a copied list is this equality.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When a divergence goes unreported.
    """
    problems = _check_with_table(pre_cutover, fixture, [*TABLE, {"name": "ghost-function"}])
    assert any("ghost-function" in p and "no such function" in p for p in problems), problems

    dropped = json.loads(json.dumps(pre_cutover))
    dropped["resource_changes"].append(
        _resource("dat-prod-unlisted", _zip_after())
    )
    fixture2 = GUARD.capture(dropped)
    problems = _check(dropped, fixture2)
    assert any(
        "unlisted" in p and "sources do not declare it" in p for p in problems
    ), problems


def test_an_empty_plan_exits_rather_than_reporting_clean(fixture):
    """"Did not run" is never "clean", applied to the guard's own input.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When an empty plan is reported as a healthy fleet.
    """
    with pytest.raises(SystemExit):
        _check({"resource_changes": []}, fixture)
    with pytest.raises(SystemExit):
        GUARD.capture({"resource_changes": []})


def test_capture_refuses_a_plan_whose_values_are_unknown():
    """A fixture captured from a pending plan would freeze unknowns as the expected values.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When capture accepts an unusable plan.
    """
    pending = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects",
                      {k: v for k, v in _zip_after().items() if k != "role"},
                      unknown={"role": True})
        ]
    }
    with pytest.raises(SystemExit):
        GUARD.capture(pending)


# ── The committed fixture ─────────────────────────────────────────────────────
# Everything above drives the guard over documents written by hand. These read the real capture,
# because a fixture that has drifted from the fleet is a comparison that passes having compared the
# wrong things — and it cannot be regenerated to fix that, by design.

FIXTURE = ROOT / "lambdas" / "fixtures" / "pre_cutover_plan.json"


ADDED_SINCE_THE_CUTOVER: frozenset[str] = frozenset(
    {
        "results-conversion-describe-results",
        "results-conversion-notify-failure",
        "results-conversion-validate-authorize",
    }
)


def test_the_committed_fixture_is_a_floor_under_the_deployed_fleet():
    """The fixture and the fleet derivation are two independent lists of one fleet.

    Not self-referential: the fixture was CAPTURED from a `tofu plan` run before the cutover, and
    the declaration is derived from today's Terraform sources — so a captured function the sources
    no longer declare means one of them is wrong about what exists. The fixture is a floor: every
    function it captured must still be declared, and everything declared beyond it must be named in
    `ADDED_SINCE_THE_CUTOVER`. `test_image_layout.py` separately holds the declaration equal to the
    function directories on disk, which closes the third side.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a captured function is gone, or an addition is unnamed.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    captured = {name.removeprefix("dat-prod-") for name in fixture["functions"]}
    declared = set(fleet.function_names(ROOT))

    assert captured, "the fixture names no functions"
    assert captured <= declared, f"captured before the cutover, gone now: {sorted(captured - declared)}"
    assert declared - captured == ADDED_SINCE_THE_CUTOVER, (
        f"declared beyond the fixture: {sorted(declared - captured)}; "
        f"named as added: {sorted(ADDED_SINCE_THE_CUTOVER)}"
    )


def _with_variables(plan, index, variables):
    """A copy of a plan with one function's environment replaced.

    Args:
      plan: The plan to copy.
      index: Which `resource_changes` entry.
      variables: The variable map to set.

    Returns:
      The copied plan.

    Raises:
      None.
    """
    changed = json.loads(json.dumps(plan))
    changed["resource_changes"][index]["change"]["after"]["environment"] = [{"variables": variables}]
    return changed


def test_a_function_added_after_the_cutover_is_accepted_and_named(pre_cutover, fixture, capsys):
    """An addition is reported by name on stderr and is not a problem.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.
      capsys: Captures the guard's stderr.

    Returns:
      None.

    Raises:
      AssertionError: When the addition is refused, or accepted silently.
    """
    grown = json.loads(json.dumps(pre_cutover))
    grown["resource_changes"].append(
        _resource("dat-prod-results-conversion-notify-failure", _zip_after())
    )
    table = [*TABLE, {"name": "results-conversion-notify-failure"}]
    problems = _check_with_table(grown, fixture, table)
    assert problems == [], problems
    assert "dat-prod-results-conversion-notify-failure: added since the parity fixture" in capsys.readouterr().err


def test_a_captured_function_absent_from_the_plan_is_still_a_problem(pre_cutover, fixture):
    """The floor's other edge: what the fixture captured cannot disappear.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When a vanished function goes unreported.
    """
    shrunk = json.loads(json.dumps(pre_cutover))
    del shrunk["resource_changes"][0]
    problems = _check_with_table(shrunk, fixture, [{"name": "api"}])
    assert any("dat-prod-archive-copy-objects: in the parity fixture, but absent from the plan" in p for p in problems), problems


def test_a_removed_environment_variable_is_named(pre_cutover, fixture):
    """A captured variable that the plan no longer sets is drift, named by the variable.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When the removal goes unreported.
    """
    problems = _check(_with_variables(pre_cutover, 0, {}), fixture)
    assert any("dat-prod-archive-copy-objects: environment variable ADMIN_BUCKET was removed" in p for p in problems), problems


def test_a_changed_environment_variable_is_named_with_both_values(pre_cutover, fixture):
    """A captured variable set to another value is drift, named with both values.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When the change goes unreported or unnamed.
    """
    problems = _check(_with_variables(pre_cutover, 0, {"ADMIN_BUCKET": "other"}), fixture)
    assert any("environment variable ADMIN_BUCKET moved from 'b' to 'other'" in p for p in problems), problems


def test_an_empty_environment_block_reads_as_no_variables(pre_cutover):
    """The provider's two spellings of "no variables" are one value, in both directions.

    A no-op plan refreshes an unset environment as ``[]`` and a create plan emits the block with
    an empty map; neither is a captured variable going missing, so neither is drift.

    Args:
      pre_cutover: The no-op plan.

    Returns:
      None.

    Raises:
      AssertionError: When the two spellings read as a move.
    """
    bare = json.loads(json.dumps(pre_cutover))
    bare["resource_changes"][0]["change"]["after"]["environment"] = []
    captured_bare = GUARD.capture(bare)
    assert _check(_with_variables(bare, 0, {}), captured_bare) == []
    assert _check(bare, GUARD.capture(_with_variables(bare, 0, {}))) == []


def test_an_added_function_with_an_unknown_parity_field_is_still_refused(pre_cutover, fixture):
    """The unknown-field rule is about the module, not the fixture, so an addition is held to it.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When an added function with an undeclared memory tier passes.
    """
    grown = json.loads(json.dumps(pre_cutover))
    grown["resource_changes"].append(
        _resource("dat-prod-results-conversion-notify-failure", _zip_after(), unknown={"memory_size": True})
    )
    table = [*TABLE, {"name": "results-conversion-notify-failure"}]
    problems = _check_with_table(grown, fixture, table)
    assert any("dat-prod-results-conversion-notify-failure: memory_size is UNKNOWN" in p for p in problems), problems


def test_an_added_function_left_on_zip_is_refused_in_image_mode(pre_cutover, fixture):
    """Packaging is derived from the plan, so an addition is held to it like everyone else.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When an added zip function passes an Image-mode check.
    """
    grown = json.loads(json.dumps(pre_cutover))
    grown["resource_changes"].append(
        _resource("dat-prod-results-conversion-notify-failure", _zip_after())
    )
    table = [*TABLE, {"name": "results-conversion-notify-failure"}]
    problems = _check_with_table(grown, fixture, table, package_type="Image", image_repository="repo")
    assert any("dat-prod-results-conversion-notify-failure: package_type is 'Zip'" in p for p in problems), problems


def test_a_variable_that_is_unknown_until_apply_is_named_rather_than_read_as_a_removal(
    pre_cutover, fixture, capsys
):
    """The shape every plan that adds a plane carries.

    A queue URL threaded into an existing function's environment is absent from `after` and
    marked in `after_unknown` until the queue exists. By value alone that is indistinguishable
    from a removal, and reading it as one refuses the whole plan for doing exactly what it says.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.
      capsys: Captures the guard's stderr.

    Returns:
      None.

    Raises:
      AssertionError: When an unknowable variable is refused, or is skipped silently.
    """
    pending = json.loads(json.dumps(pre_cutover))
    after = pending["resource_changes"][0]["change"]["after"]
    after["environment"] = [{"variables": {}}]
    pending["resource_changes"][0]["change"]["after_unknown"] = {
        "environment": [{"variables": {"ADMIN_BUCKET": True}}]
    }

    problems = _check(pending, fixture)

    assert problems == [], problems
    assert "environment variable ADMIN_BUCKET is not known until apply" in capsys.readouterr().err


@pytest.mark.parametrize(
    "marker",
    [True, [True], [{"variables": True}], [{"variables": {"ADMIN_BUCKET": True}}]],
    ids=["whole-attribute", "whole-block", "whole-map", "one-value"],
)
def test_every_shape_terraform_marks_an_unknown_environment_with_is_read(pre_cutover, fixture, marker):
    """`after_unknown` preserves structure at whichever level the provider resolved.

    The one-value shape was the only one the first version of this handled, because the fixture
    it was written against had only that shape — and the real plan carried the whole-block one,
    which crashed the guard in CI on the first PR that produced one. Each of these means the
    captured variable cannot be compared on this plan, and none of them is drift.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.
      marker: One shape Terraform writes.

    Returns:
      None.

    Raises:
      AssertionError: When a shape is read as drift or crashes the guard.
    """
    pending = json.loads(json.dumps(pre_cutover))
    pending["resource_changes"][0]["change"]["after"]["environment"] = [{"variables": {}}]
    pending["resource_changes"][0]["change"]["after_unknown"] = {"environment": marker}

    assert _check(pending, fixture) == []


@pytest.mark.parametrize("marker", [{"variables": {}}, [[1]], ["nope"]], ids=["dict", "nested-list", "string"])
def test_a_marker_shape_this_guard_cannot_read_is_refused_rather_than_guessed(
    pre_cutover, fixture, marker
):
    """A shape nobody has seen must not resolve to "nothing is unknown".

    That default would read every absent variable as a removal, or every present one as fine,
    depending on nothing — so an unreadable marker is a named refusal instead.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.
      marker: A shape the reader does not recognise.

    Returns:
      None.

    Raises:
      AssertionError: When an unreadable marker passes or crashes.
    """
    pending = json.loads(json.dumps(pre_cutover))
    pending["resource_changes"][0]["change"]["after_unknown"] = {"environment": marker}

    problems = _check(pending, fixture)

    assert any("a shape this guard cannot read" in p for p in problems), problems


def test_an_unknown_environment_does_not_excuse_the_variables_beside_it(pre_cutover, fixture):
    """The other half: one unknowable variable must not stop the rest being compared.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When a real removal hides behind an unknown sibling.
    """
    captured = json.loads(json.dumps(pre_cutover))
    captured["resource_changes"][0]["change"]["after"]["environment"] = [
        {"variables": {"ADMIN_BUCKET": "b", "KEPT": "yes"}}
    ]
    fixture_with_two = GUARD.capture(captured)

    pending = json.loads(json.dumps(captured))
    pending["resource_changes"][0]["change"]["after"]["environment"] = [{"variables": {}}]
    pending["resource_changes"][0]["change"]["after_unknown"] = {
        "environment": [{"variables": {"ADMIN_BUCKET": True}}]
    }

    problems = _check(pending, fixture_with_two)

    assert any("environment variable KEPT was removed" in p for p in problems), problems
    assert not any("ADMIN_BUCKET" in p for p in problems), problems


def test_an_image_packaged_addition_is_clean_in_image_mode(pre_cutover, fixture):
    """The production shape: Image mode, an addition that is Image-packaged with a command.

    The command-vs-handler comparison has no captured handler for an addition and must pass it
    through; a later tidy that refused an unknown handler would refuse every addition in
    production with the rest of this suite green.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When the production shape refuses growth.
    """
    grown = json.loads(json.dumps(pre_cutover))
    for change in grown["resource_changes"]:
        after = change["change"]["after"]
        after.update(
            package_type="Image",
            image_uri=f"repo:{after['function_name']}",
            image_config=[{"command": [after["handler"]]}],
        )
    grown["resource_changes"].append(
        _resource(
            "dat-prod-results-conversion-notify-failure",
            _zip_after(package_type="Image", image_uri="repo:sha", image_config=[{"command": ["rc_notify_failure.handler"]}]),
        )
    )
    table = [*TABLE, {"name": "results-conversion-notify-failure"}]
    assert _check_with_table(grown, fixture, table, package_type="Image", image_repository="repo") == []


def test_an_added_environment_variable_is_clean(pre_cutover, fixture):
    """A variable the fixture never captured is growth, not drift.

    Args:
      pre_cutover: The no-op plan.
      fixture: Its capture.

    Returns:
      None.

    Raises:
      AssertionError: When growth is refused.
    """
    problems = _check(
        _with_variables(pre_cutover, 0, {"ADMIN_BUCKET": "b", "RESULTS_CONVERSION_QUEUE_URL": "q"}),
        fixture,
    )
    assert problems == [], problems


def test_every_captured_function_carries_a_handler_and_a_memory_tier():
    """The two fields the cutover reads back out of the fixture rather than deriving.

    The handler becomes the container's command, and the memory tier is one of the attributes a
    replacement plan leaves unknown unless the module declares it. A null in either would make the
    corresponding comparison silently trivial.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a captured row is missing either.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    missing_handler = sorted(n for n, r in fixture["functions"].items() if not r.get("handler"))
    missing_memory = sorted(n for n, r in fixture["functions"].items() if not r.get("memory_size"))

    assert missing_handler == [], f"captured with no handler: {missing_handler}"
    assert missing_memory == [], f"captured with no memory tier: {missing_memory}"


def test_the_fixture_says_in_its_own_text_that_it_is_frozen():
    """A regenerated fixture agrees with whatever the code currently says, which is the one thing
    it must never do — so the file carries that instruction rather than only the commit that added
    it.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the note is missing.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "FROZEN" in fixture.get("note", ""), (
        "the fixture must say it is frozen; a reader who regenerates it destroys the only "
        "independent record of what the fleet looked like before the cutover"
    )


# ── The shapes a real plan actually produces ──────────────────────────────────
# Everything above this line builds `after_unknown` by hand, and the first version of the guard
# passed all of it while being wrong about every real plan. The reason is worth stating: those
# fixtures used SCALAR unknown markers (`{"memory_size": True}`), so they agreed with the
# implementation and with nothing else.
#
# Terraform's `after_unknown` PRESERVES STRUCTURE. Measured with `tofu show -json` against a real
# create plan of infra/modules/docker-lambda, provider 5.100.0:
#
#     environment    after=[{"variables": {"FOO": "bar"}}]   after_unknown=[{"variables": {}}]
#     architectures  after=["x86_64"]                        after_unknown=[false]
#     timeout        after=60                                after_unknown=null
#
# A known list is `[false]`; a known block is `[{}]`. Both are truthy in Python. These are those
# captured shapes, verbatim.

REAL_CREATE_UNKNOWN = {
    "environment": [{"variables": {}}],
    "architectures": [False],
    "vpc_config": [],
    "timeout": None,
    "memory_size": None,
    "role": None,
    "reserved_concurrent_executions": None,
}


def test_a_known_list_or_block_is_not_read_as_unknown():
    """The leaf test, against the markers a real create plan emits.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a fully-known structured value reads as unknown.
    """
    for field, marker in REAL_CREATE_UNKNOWN.items():
        assert not GUARD._has_unknown_leaf(marker), (
            f"{field}: marker {marker!r} is fully known in a real plan but reads as unknown"
        )


def test_a_genuinely_unknown_leaf_is_still_caught():
    """The negative control. Without it the fix above could be "always return False".

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a real unknown is missed.
    """
    assert GUARD._has_unknown_leaf(True)
    assert GUARD._has_unknown_leaf([True])
    assert GUARD._has_unknown_leaf([{"variables": True}])
    assert GUARD._has_unknown_leaf([{"subnet_ids": [False, True]}])
    assert not GUARD._has_unknown_leaf(None)


def test_a_create_plan_captures_and_checks_clean():
    """End to end over the real shapes — capture, then check the same plan against its capture.

    This is the case the guard was written for and got wrong: capture exited 1, and check emitted
    a false failure for every list and block attribute.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a create plan is not handled cleanly.
    """
    created = {
        "resource_changes": [{
            "address": "module.fn.aws_lambda_function.this",
            "type": "aws_lambda_function",
            "change": {
                "actions": ["create"],
                "after": {
                    "function_name": "dat-prod-archive-copy-objects",
                    "package_type": "Image",
                    "image_uri": "repo:abc",
                    "image_config": [{"command": ["archive_copy_objects.handler"]}],
                    "environment": [{"variables": {"FOO": "bar"}}],
                    "architectures": ["x86_64"],
                    "vpc_config": [],
                    "timeout": 60,
                    "memory_size": 128,
                    "role": "arn:aws:iam::123456789012:role/exec",
                    "reserved_concurrent_executions": -1,
                },
                "after_unknown": REAL_CREATE_UNKNOWN,
            },
        }]
    }
    captured = GUARD.capture(created)
    problems = _check_with_table(created, captured, [{"name": "archive-copy-objects"}],
                                 package_type="Image", image_repository="repo")
    assert problems == [], problems


def test_vpc_parity_survives_the_computed_vpc_id():
    """`vpc_id` is read back by the provider: present in a no-op plan, absent in a create one.

    Comparing it raw fails for every VPC-attached function whatever the configuration says, and
    the guard's usual remedy — declare it explicitly — is impossible for an attribute nothing can
    set. Only the sub-attributes a configuration controls are compared.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the computed read-back breaks parity.
    """
    no_op = _resource("dat-prod-vpc-thing", _zip_after(
        vpc_config=[{"subnet_ids": ["s-2", "s-1"], "security_group_ids": ["sg-1"],
                     "vpc_id": "vpc-123"}]))
    replacement = _resource("dat-prod-vpc-thing", _zip_after(
        vpc_config=[{"subnet_ids": ["s-1", "s-2"], "security_group_ids": ["sg-1"],
                     "ipv6_allowed_for_dual_stack": False}]))

    fixture = GUARD.capture({"resource_changes": [no_op]})
    problems = _check_with_table({"resource_changes": [replacement]}, fixture,
                                 [{"name": "vpc-thing"}])
    assert problems == [], problems


def test_a_real_vpc_change_is_still_caught():
    """The negative control for the normalisation — it must not flatten a genuine move.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a changed subnet passes.
    """
    before = _resource("dat-prod-vpc-thing", _zip_after(
        vpc_config=[{"subnet_ids": ["s-1"], "security_group_ids": ["sg-1"], "vpc_id": "vpc-1"}]))
    after = _resource("dat-prod-vpc-thing", _zip_after(
        vpc_config=[{"subnet_ids": ["s-9"], "security_group_ids": ["sg-1"]}]))

    fixture = GUARD.capture({"resource_changes": [before]})
    problems = _check_with_table({"resource_changes": [after]}, fixture,
                                 [{"name": "vpc-thing"}])
    assert any("vpc_config moved" in p for p in problems), problems


def test_the_parity_list_covers_every_field_the_spec_promises():
    """`PARITY_FIELDS` is the guard's whole subject, and dropping one from it fails nothing else.

    Measured: removing `vpc_config` left every other test in this file green while the guard
    stopped reporting a real VPC move. FR-002 names the set, so it is pinned here.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the guard stops comparing something the spec promises is unchanged.
    """
    assert set(GUARD.PARITY_FIELDS) == {
        "environment", "timeout", "memory_size", "architectures", "role",
        "reserved_concurrent_executions", "vpc_config",
    }, (
        f"PARITY_FIELDS is {sorted(GUARD.PARITY_FIELDS)}; FR-002 promises the cutover changes "
        "none of environment, timeout, memory, architecture, role, reserved concurrency or VPC "
        "configuration, and a field missing from this tuple is one nothing compares"
    )


def test_the_repository_check_requires_the_tag_separator(fixture):
    """`repo` and `repo-something-else` share a prefix; only the colon distinguishes them.

    Measured: dropping the `:` from the prefix test left all ten of this file's other assertions
    green while the guard accepted a neighbouring repository whose name merely starts the same.

    Args:
      fixture: The capture.

    Returns:
      None.

    Raises:
      AssertionError: When a lookalike repository is accepted.
    """
    repo = "123.dkr.ecr.us-east-1.amazonaws.com/dat-prod-lambda"
    lookalike = {
        "resource_changes": [
            _resource("dat-prod-archive-copy-objects", _zip_after(
                package_type="Image", handler=None,
                image_uri=f"{repo}-experimental:abc",
                image_config=[{"command": ["archive_copy_objects.handler"]}])),
            _resource("dat-prod-api", _zip_after(
                package_type="Image", handler=None, timeout=29, memory_size=256,
                image_uri=f"{repo}:abc", image_config=[{"command": ["handler.handler"]}])),
        ]
    }
    problems = _check(lookalike, fixture, "Image", repo)
    assert any("does not name the fleet's repository" in p for p in problems), problems


def test_a_destroyed_function_is_skipped_rather_than_aborting_the_guard():
    """A delete carries `after: null`, which is not a function whose name is unknown.

    Measured against OpenTofu: a destroy is `{"actions": ["delete"], "after": null}`. Reading that
    as a nameless function aborted the whole guard with a diagnosis naming the wrong problem. A
    REPLACE — one entry with both actions — describes a function that WILL exist and is kept.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When a destroy aborts the guard, or a replacement is dropped.
    """
    plan = {
        "resource_changes": [
            {"address": "module.old.aws_lambda_function.gone", "type": "aws_lambda_function",
             "change": {"actions": ["delete"], "after": None, "after_unknown": {}}},
            {"address": "module.new.aws_lambda_function.this", "type": "aws_lambda_function",
             "change": {"actions": ["delete", "create"],
                        "after": {"function_name": "dat-prod-api", **_zip_after(
                            timeout=29, memory_size=256, handler="handler.handler")},
                        "after_unknown": REAL_CREATE_UNKNOWN}},
        ]
    }
    assert sorted(GUARD._functions(plan)) == ["dat-prod-api"]


def test_a_permission_bound_to_a_NAME_is_the_outage_this_guard_refuses(pre_cutover, fixture):
    """The defect that ships green: no diff, and the replacement takes the resource policy.

    A name is known at plan time and identical either side of the replacement, so Terraform never
    recreates the permission — while DeleteFunction has already removed the policy it granted.
    """
    plan = {
        "resource_changes": [
            *pre_cutover["resource_changes"],
            _permission("dat-prod-api"),
        ]
    }

    problems = _check(plan, fixture)

    assert any("which is a NAME" in problem for problem in problems), problems


def test_a_permission_unknown_because_its_function_is_being_replaced_is_fine(pre_cutover, fixture):
    """The correct binding, seen the way a replacement plan renders it.

    `function_arn` is computed, so it is unknown while the function is replaced — which is
    precisely what plans the permission for replacement alongside it.
    """
    plan = {
        "resource_changes": [
            *pre_cutover["resource_changes"],
            _permission(None, unknown=True),
        ]
    }

    assert _check(plan, fixture) == []


def test_a_plan_carrying_no_permission_at_all_exits_rather_than_passing(pre_cutover, fixture):
    """A check that passes when its own subject is absent reads as enforcement while enforcing
    nothing — the same refusal `_functions` already makes for an empty fleet."""
    with pytest.raises(SystemExit) as exit_info:
        GUARD.check(pre_cutover, fixture, "Zip", None, TABLE, "dat", "prod")

    assert "no aws_lambda_permission" in str(exit_info.value)


def test_a_destroyed_permission_is_skipped_rather_than_read_as_a_bare_name():
    """Its `after` is null, which is neither an ARN nor unknown — and reading it would fail the
    guard with a diagnosis naming the wrong problem."""
    destroyed = {
        "address": "module.x.aws_lambda_permission.gone",
        "type": "aws_lambda_permission",
        "change": {"actions": ["delete"], "after": None, "after_unknown": {}},
    }

    assert GUARD._permissions({"resource_changes": [destroyed]}) == {}
