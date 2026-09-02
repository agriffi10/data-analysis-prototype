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
  GUARD: The script under test, imported by path because `.github/scripts` is not a package.
  TABLE: A deploy table naming the two functions the fixtures use.
"""

import importlib.util
import json
import pathlib

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


def _check(plan, fixture, package_type="Zip", image_repository=None):
    """Runs the guard's check with this module's fixed project and environment.

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
    problems = GUARD.check(pre_cutover, fixture, "Zip", None,
                           [*TABLE, {"name": "ghost-function"}], "dat", "prod")
    assert any("ghost-function" in p and "no such function" in p for p in problems), problems

    dropped = json.loads(json.dumps(pre_cutover))
    dropped["resource_changes"].append(
        _resource("dat-prod-unlisted", _zip_after())
    )
    fixture2 = GUARD.capture(dropped)
    problems = GUARD.check(dropped, fixture2, "Zip", None, TABLE, "dat", "prod")
    assert any("unlisted" in p and "deploy table does not name it" in p for p in problems), problems


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
DEPLOY_TABLE = ROOT / ".github" / "lambda-functions.json"


def test_the_committed_fixture_covers_exactly_the_deployed_fleet():
    """The fixture and the deploy table are two independent lists of one fleet.

    Not self-referential: the fixture was captured from a `tofu plan` and the table is
    hand-maintained beside the function directories, so a divergence means one of them is wrong
    about what exists. `test_deploy_matrix.py` separately holds the table equal to the directories
    on disk, which closes the third side.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: When the two disagree about the fleet.
    """
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    captured = {name.removeprefix("dat-prod-") for name in fixture["functions"]}
    declared = {row["name"] for row in json.loads(DEPLOY_TABLE.read_text(encoding="utf-8"))}

    assert captured, "the fixture names no functions"
    assert captured == declared, (
        f"only in the fixture: {sorted(captured - declared)}; "
        f"only in the deploy table: {sorted(declared - captured)}"
    )


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
