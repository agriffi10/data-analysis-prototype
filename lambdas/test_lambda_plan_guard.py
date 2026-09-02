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
    problems = GUARD.check(created, captured, "Image", "repo",
                           [{"name": "archive-copy-objects"}], "dat", "prod")
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
    problems = GUARD.check({"resource_changes": [replacement]}, fixture, "Zip", None,
                           [{"name": "vpc-thing"}], "dat", "prod")
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
    problems = GUARD.check({"resource_changes": [after]}, fixture, "Zip", None,
                           [{"name": "vpc-thing"}], "dat", "prod")
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
