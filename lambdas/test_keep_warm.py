"""The daily wake of the functions a user reaches first, asserted over the Terraform that builds it.

An image function idle for weeks goes Inactive and Lambda rejects the invoke that wakes it. The
three functions a user meets first — both Cognito triggers on sign-up and the API on the first
request — are each invoked once a day by a ``*-keep-warm`` rule in the module that owns them.
Two failures here apply green and only show weeks later, which is why they are guarded: a function
that joins the sign-up or request path without joining the wake, and a target whose invoke
permission is missing, which EventBridge counts in ``FailedInvocations`` and nothing reads. The
population is derived from the Cognito pool's triggers and the API's integration, never listed.

The payloads are proved to be no-ops beside each handler's own tests, not here. Reasoning:
``docs/decisions/infrastructure/the-functions-a-user-reaches-first-are-woken-daily.md``.

Attributes:
  MODULES: The Terraform module tree.
  WAKE_PAYLOAD: The input every keep-warm target must send — the file the handlers' tests run.
  MAX_PERIOD_HOURS: The longest period a keep-warm rule may run at. One invoke a day is the
    cadence measured to keep a function Active; nothing slower has been measured.
  RATE_UNIT_HOURS: Hours per unit of an EventBridge ``rate()`` expression.
"""

import pathlib
import re

import pytest
from tf_blocks import argument, blocks, span, strip_comments

MODULES = pathlib.Path(__file__).resolve().parent.parent / "infra" / "modules"
WAKE_PAYLOAD = 'trimspace(file("${path.module}/keep-warm.json"))'
MAX_PERIOD_HOURS = 24
RATE_UNIT_HOURS = {
    "minute": 1 / 60,
    "minutes": 1 / 60,
    "hour": 1,
    "hours": 1,
    "day": 24,
    "days": 24,
}


def _module_source(module: str) -> str:
    """Joins one module's Terraform files, comments blanked.

    Args:
      module: The module's directory name under ``infra/modules``.

    Returns:
      The concatenated source.

    Raises:
      None.
    """
    return "\n".join(
        strip_comments(path.read_text(encoding="utf-8"))
        for path in sorted((MODULES / module).glob("*.tf"))
    )


def _functions_a_user_reaches_first() -> set[tuple[str, str]]:
    """Every function a sign-up or a signed-in request invokes before anything else.

    Read from the Terraform rather than listed: each module named in the Cognito pool's
    ``lambda_config``, and the module behind the API's integration.

    Args:
      None.

    Returns:
      ``(module directory, function module call)`` pairs.

    Raises:
      None.
    """
    auth = _module_source("auth")
    pool = next(iter(blocks(auth, "aws_cognito_user_pool").values()))
    triggers = span(pool, pool.index("lambda_config"))
    population = {
        ("auth", name) for name in re.findall(r"module\.(\w+)\.function_arn", triggers)
    }

    integrations = blocks(_module_source("api"), "aws_apigatewayv2_integration")
    for body in integrations.values():
        population |= {
            ("api", name)
            for name in re.findall(
                r"module\.(\w+)\.invoke_arn", argument(body, "integration_uri")
            )
        }
    return population


def _keep_warm_rules(source: str) -> dict[str, str]:
    """The module's keep-warm rules, keyed by local name.

    Args:
      source: One module's Terraform source.

    Returns:
      Each rule whose name ends ``-keep-warm``, mapped to its body.

    Raises:
      None.
    """
    return {
        name: body
        for name, body in blocks(source, "aws_cloudwatch_event_rule").items()
        if argument(body, "name").endswith('-keep-warm"')
    }


def test_the_population_is_the_three_functions_measured() -> None:
    """The derivation still finds what a user reaches first, so the test below is not vacuous.

    Args:
      None.

    Returns:
      None.

    Raises:
      AssertionError: If the Cognito triggers or the API integration were not found.
    """
    assert _functions_a_user_reaches_first() == {
        ("auth", "pre_signup"),
        ("auth", "post_confirmation"),
        ("api", "api"),
    }


@pytest.mark.parametrize("module, function", sorted(_functions_a_user_reaches_first()))
def test_every_function_a_user_reaches_first_is_woken_and_may_be_invoked(
    module: str, function: str
) -> None:
    """A wake needs a target AND a permission naming the same rule, or it fails silently.

    Args:
      module: The module directory that declares the function.
      function: The function's module call name.

    Returns:
      None.

    Raises:
      AssertionError: If no keep-warm rule targets the function with the shared payload, or no
        permission lets that rule invoke it.
    """
    source = _module_source(module)
    rules = _keep_warm_rules(source)
    arn = f"module.{function}.function_arn"

    targets = [
        argument(body, "rule")
        .removeprefix("aws_cloudwatch_event_rule.")
        .removesuffix(".name")
        for body in blocks(source, "aws_cloudwatch_event_target").values()
        if argument(body, "arn") == arn and argument(body, "input") == WAKE_PAYLOAD
    ]
    woken_by = [rule for rule in targets if rule in rules]
    assert woken_by, f"no keep-warm rule in {module} targets {arn} with {WAKE_PAYLOAD}"

    permitted = {
        argument(body, "source_arn")
        .removeprefix("aws_cloudwatch_event_rule.")
        .removesuffix(".arn")
        for body in blocks(source, "aws_lambda_permission").values()
        if argument(body, "function_name") == arn
        and not re.search(r"^\s*qualifier\s*=", body, re.MULTILINE)
        and argument(body, "principal") == '"events.amazonaws.com"'
        and argument(body, "action") == '"lambda:InvokeFunction"'
    }
    missing = [rule for rule in woken_by if rule not in permitted]
    assert not missing, (
        f"{arn} is a target of {missing} with no permission for that rule to invoke it; "
        "EventBridge would fail every wake and count it only in FailedInvocations"
    )


@pytest.mark.parametrize("module", ["auth", "api"])
def test_every_keep_warm_rule_fires_at_least_daily(module: str) -> None:
    """One invoke a day is the cadence measured to keep an image function Active.

    Args:
      module: A module that carries a keep-warm rule.

    Returns:
      None.

    Raises:
      AssertionError: If a rule is missing, sets its own state, is a cron, or runs less often
        than daily.
    """
    rules = _keep_warm_rules(_module_source(module))
    assert rules, f"{module} carries no keep-warm rule"

    for name, body in rules.items():
        assert not re.search(r"^\s*(state|is_enabled)\s*=", body, re.MULTILINE), (
            f"{module}.{name} sets its own state; a keep-warm rule is always enabled"
        )
        expression = argument(body, "schedule_expression")
        match = re.fullmatch(r'"rate\((\d+) (\w+)\)"', expression)
        assert match and match.group(2) in RATE_UNIT_HOURS, (
            f"{module}.{name} runs on {expression}; a keep-warm rule is a rate() so its period "
            "can be read"
        )
        hours = int(match.group(1)) * RATE_UNIT_HOURS[match.group(2)]
        assert hours <= MAX_PERIOD_HOURS, (
            f"{module}.{name} wakes every {hours:g} hours; nothing slower than daily is measured "
            "to keep a function Active"
        )
