"""The control-plane module's one plan-time refusal, run through OpenTofu rather than read.

A plane that declares a ceiling gets its `TIMED_OUT` rule because it declared the ceiling, and the
rule targets the verb the ceiling names. A ceiling naming a verb the plane does not have would
ship a door to nobody, so the module refuses it with a `precondition` — and a precondition can be
asserted present while its condition has been weakened to accept anything, so it is EVALUATED
here: the module is planned against a mocked AWS provider, once with a notifier it has and once
with one it lacks, and the refusal's own message is asserted.

The plan needs the AWS provider's schema, so `tofu init` downloads it once into the scratch copy.

Attributes:
  MODULES: The module tree, copied whole so the module's call into `docker-lambda` resolves.
"""

import os
import pathlib
import shutil
import subprocess
import tempfile

MODULES = pathlib.Path(__file__).resolve().parent.parent / "infra" / "modules"

_RUN = """
mock_provider "aws" {{
  mock_resource "aws_iam_role" {{
    defaults = {{ arn = "arn:aws:iam::111111111111:role/mock" }}
  }}
  mock_resource "aws_lambda_function" {{
    defaults = {{ arn = "arn:aws:lambda:us-east-1:111111111111:function:mock" }}
  }}
  mock_resource "aws_sqs_queue" {{
    defaults = {{ arn = "arn:aws:sqs:us-east-1:111111111111:mock.fifo" }}
  }}
  mock_resource "aws_cloudwatch_log_group" {{
    defaults = {{ arn = "arn:aws:logs:us-east-1:111111111111:log-group:mock" }}
  }}
  mock_resource "aws_cloudwatch_event_rule" {{
    defaults = {{ arn = "arn:aws:events:us-east-1:111111111111:rule/mock" }}
  }}
  mock_resource "aws_sfn_state_machine" {{
    defaults = {{ arn = "arn:aws:states:us-east-1:111111111111:stateMachine:mock" }}
  }}
}}

variables {{
  name                            = "plane"
  project_name                    = "dat"
  environment                     = "test"
  aws_region                      = "us-east-1"
  account_id                      = "111111111111"
  functions                       = {{ "notify-failure" = {{ handler = "n.handler", timeout = 15, memory = 256 }} }}
  environment_variables           = {{ ENV_NAME = "test" }}
  lambda_image_repository_url     = "111111111111.dkr.ecr.us-east-1.amazonaws.com/fleet"
  lambda_image_tag                = "abc"
  content_based_deduplication     = false
  dlq_content_based_deduplication = false
  dlq_max_receive_count           = 3
  definition_template             = "./definition.tftpl"
  execution_policy                = "{{}}"
  admin_bucket_arn                = "arn:aws:s3:::admin"
  ceiling = {{
    seconds          = 60
    notifier_verb    = "{verb}"
    rule_description = "Tell the actor."
  }}
}}

run "plan" {{
  command = plan
}}
"""


def _plan_with_notifier(verb: str) -> subprocess.CompletedProcess[str]:
    """Plans the module, under a mocked provider, with a ceiling naming ``verb`` as its notifier.

    Args:
      verb: The notifier the ceiling names.

    Returns:
      The finished `tofu test` run.

    Raises:
      AssertionError: When OpenTofu is unavailable or its init fails, rather than a skip that
        would read as coverage.
    """
    tofu = shutil.which("tofu")
    assert tofu, "OpenTofu is not on PATH — this refusal cannot be skipped into passing"
    with tempfile.TemporaryDirectory() as scratch:
        tree = pathlib.Path(scratch) / "modules"
        for name in ("control-plane", "docker-lambda"):
            shutil.copytree(MODULES / name, tree / name, ignore=shutil.ignore_patterns(".terraform*"))
        module = tree / "control-plane"
        (module / "definition.tftpl").write_text(
            '{"TimeoutSeconds": ${state_machine_timeout_seconds}, '
            '"Notify": "${notify_failure_function_arn}"}\n',
            encoding="utf-8",
        )
        (module / "tests").mkdir()
        (module / "tests" / "ceiling.tftest.hcl").write_text(_RUN.format(verb=verb), encoding="utf-8")
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "TF_IN_AUTOMATION": "1",
        }
        setup = subprocess.run(  # noqa: S603
            [tofu, "init", "-backend=false", "-input=false"],
            cwd=module, env=environment, capture_output=True, text=True, check=False,
        )
        assert setup.returncode == 0, f"tofu init failed:\n{setup.stdout}\n{setup.stderr}"
        return subprocess.run(  # noqa: S603
            [tofu, "test", "-no-color"],
            cwd=module, env=environment, capture_output=True, text=True, check=False,
        )


def test_a_ceiling_whose_notifier_is_a_verb_plans() -> None:
    """The positive control: without it the refusal below could be any failure at all."""
    result = _plan_with_notifier("notify-failure")
    assert result.returncode == 0, f"a valid ceiling did not plan:\n{result.stdout}\n{result.stderr}"


def test_a_ceiling_whose_notifier_is_not_a_verb_is_refused_by_name() -> None:
    """The refusal fires, and it is the module's own precondition that fires."""
    result = _plan_with_notifier("missing")
    output = result.stdout + result.stderr
    assert result.returncode != 0, f"a ceiling naming no verb planned:\n{output}"
    assert 'notifier verb "missing" is not one of this plane\'s functions' in output, output
