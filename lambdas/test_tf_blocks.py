"""The Terraform readers the infrastructure suites assert through.

`blocks`, `span` and `strip_noise` were exercised only through their callers, which is fine while a
caller fails loudly on a bad parse and useless when it does not: an under-reading scanner returns a
smaller slice, every assertion over it still passes, and the guard has quietly stopped covering the
half it could not see. The readers added for the fleet's second packaging are the ones with that
failure mode, so they are tested here directly.

**Both fixtures are real artefacts, and that is the point.** The resource is lifted verbatim from
the module that declares the log sweep — the packaging every function in the fleet still has. The
module call is the packaging the cutover will write: it was put through
`tofu init -backend=false && tofu validate && tofu fmt -check` on the version CI pins and pasted
here verbatim, including the two hazards that are the point — a comment closing a brace it never
opened, and a string containing one. A fixture and an implementation written from each other
agree with nothing.

Attributes:
  MODULE_CALL: The validated module call, verbatim.
  RESOURCE: The zip-packaged shape, lifted verbatim from `infra/modules/observability/lambda.tf`
    at the commit this branch left. It is the log sweep because that is a function declaring
    BOTH old spellings, `timeout` and `memory_size`, so neither arm is exercised against text
    written for the test.
"""

import pytest
from tf_blocks import (
    argument,
    lambda_declaration,
    lambda_environment,
    lambda_input,
    module_calls,
    strip_comments,
)

MODULE_CALL = '''module "functions" {
  source   = "./modules/docker-lambda"
  for_each = local.demo_functions

  function_name        = local.demo_function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = "0.dkr.ecr.us-east-1.amazonaws.com/demo"
  image_tag            = var.lambda_image_tag
  command              = [each.value.handler]
  timeout_seconds      = each.value.timeout
  memory_mb            = each.value.memory

  environment = merge(
    {
      ADMIN_BUCKET = "a"
      # ⚠ A missing one surfaces as a failed REQUEST rather than a failed deploy } and this
      # comment closes a brace it never opened, on purpose.
      ENV_NAME       = var.environment
      LOGS_QUEUE_URL = "https://example/q}suffix"
    },
    lookup(local.demo_verb_env, each.key, {}),
  )
}

module "sibling" {
  source        = "./modules/docker-lambda"
  function_name = "unrelated"
}
'''

RESOURCE = '''resource "aws_lambda_function" "sweep" {
  function_name = local.sweep_name
  role          = aws_iam_role.sweep.arn
  runtime       = "python3.12"
  handler       = "log_sweep.handler"

  # ORDERED: timeout < queue visibility (360s) < schedule interval (600s). Breaking either
  # inequality writes messages to S3 twice. README.md.
  timeout = 300
  # 512, not 256 — the sweep reads the day's whole object back before appending.
  memory_size = 512

  environment {
    variables = {
      LOGS_QUEUE_URL = aws_sqs_queue.logs.url
      ENV_NAME       = var.environment

      # ADMIN_BUCKET is genuinely used; the rest are the cpcommon layer's required union.
      # Do not remove one because the sweep does not read it — README.md.
      ADMIN_BUCKET        = var.admin_bucket_name
      USER_SPACE_BUCKET   = var.user_space_bucket_name
      SHARED_SPACE_BUCKET = var.shared_space_bucket_name
      ATHENA_WORKGROUP    = var.athena_workgroup
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  lifecycle {
    # CI owns the code AND the cpcommon layer attachment — never revert either on apply.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.sweep,
    aws_cloudwatch_log_group.sweep,
  ]
}
'''


def test_a_module_call_ends_at_its_own_closing_brace_and_not_before() -> None:
    """Both ends of the block, and the second half is the one with teeth.

    "It did not swallow the next call" is satisfied by any truncation, so a non-greedy regex —
    the shape the brace counter replaced — passes it while cutting the body short at the first
    inner `}`. Measured: three such mutants survived an earlier version of this test, including
    the plainest. So the tail is asserted POSITIVELY: the body must still carry its last
    argument, which sits after two nested blocks and a comment that closes a brace it never
    opened.
    """
    calls = module_calls(MODULE_CALL)

    assert set(calls) == {"functions", "sibling"}
    assert "unrelated" not in calls["functions"], (
        "the first call swallowed the one after it, so every assertion over it reads two "
        "declarations as one"
    )
    assert calls["functions"].rstrip().endswith(")"), (
        "the body was cut short of its own closing brace — an under-read leaves every assertion "
        "over it passing on less than the block actually says"
    )
    assert "lookup(local.demo_verb_env, each.key, {})" in calls["functions"], (
        "the body stops before its last argument"
    )


def test_an_argument_comes_back_whole_past_a_brace_in_a_comment_and_in_a_string() -> None:
    """The reason this reader exists, and the mutation it is written against.

    Counting delimiters over the raw text closes `merge(` early: the comment's `}` and the URL's
    `}` each drop the depth, and the value ends at the newline after `LOGS_QUEUE_URL`. Every
    environment NAME is still captured, so nothing looks wrong — what is lost is the per-verb
    override, silently.
    """
    body = module_calls(MODULE_CALL)["functions"]

    value = argument(body, "environment")

    assert value.startswith("merge(")
    assert "lookup(local.demo_verb_env, each.key, {})" in value, (
        "the value was truncated before the override; a brace in a comment or a string ended it"
    )
    assert value.endswith(")")


def test_a_single_line_argument_stops_at_its_own_end_of_line() -> None:
    """The other direction: a scalar value must not run on into the next argument."""
    body = module_calls(MODULE_CALL)["functions"]

    assert argument(body, "command") == "[each.value.handler]"
    assert argument(body, "memory_mb") == "each.value.memory"


def test_a_missing_argument_raises_rather_than_reading_as_empty() -> None:
    """An empty string is what every caller would compare against and pass."""
    body = module_calls(MODULE_CALL)["functions"]

    with pytest.raises(ValueError, match=r"no top-level .handler = ."):
        argument(body, "handler")


def test_a_declaration_is_found_under_either_packaging() -> None:
    """One accessor, so a suite pinning a Python constant to a deployed number reads one way."""
    assert "image_tag" in lambda_declaration(MODULE_CALL, "functions")
    assert "runtime" in lambda_declaration(RESOURCE, "sweep")

    with pytest.raises(ValueError, match="no module call or aws_lambda_function"):
        lambda_declaration(RESOURCE, "absent")


def test_an_input_reads_whichever_spelling_the_declaration_carries() -> None:
    """`timeout`/`memory_size`/`role` on the resource; the module's own spellings on a call."""
    call = lambda_declaration(MODULE_CALL, "functions")
    resource = lambda_declaration(RESOURCE, "sweep")

    assert lambda_input(call, "timeout") == "each.value.timeout"
    assert lambda_input(resource, "timeout") == "300"
    assert lambda_input(resource, "memory") == "512"
    assert lambda_input(resource, "role") == "aws_iam_role.sweep.arn"

    with pytest.raises(ValueError, match="unknown setting"):
        lambda_input(resource, "disk")


def test_a_declaration_that_sets_neither_thing_raises_rather_than_reading_as_absent() -> None:
    """The two refusals a caller could otherwise mistake for "the value is empty".

    A suite that pins a Python constant to a deployed number must fail LOUDLY when the number is
    gone; a silent empty string would compare unequal in some callers and be skipped in others.
    """
    bare = 'module "bare" {\n  source = "../docker-lambda"\n}\n'
    body = module_calls(bare)["bare"]

    with pytest.raises(ValueError, match="the declaration sets no environment"):
        lambda_environment(body)
    with pytest.raises(ValueError, match="the declaration sets no memory"):
        lambda_input(body, "memory")


def test_the_environment_is_found_in_both_shapes_and_carries_the_same_names() -> None:
    """A map on the call, a nested block on the resource; the names are what callers want."""
    call = lambda_environment(lambda_declaration(MODULE_CALL, "functions"))
    resource = lambda_environment(lambda_declaration(RESOURCE, "sweep"))

    assert "ADMIN_BUCKET" in call and "LOGS_QUEUE_URL" in call
    assert "ADMIN_BUCKET" in resource and "LOGS_QUEUE_URL" in resource
    assert "memory_size" not in resource, (
        "the resource's environment slice ran past its own block and swallowed a sibling argument"
    )


def test_blanking_comments_alone_leaves_the_string_a_sweep_is_looking_for() -> None:
    """The counterpart `strip_noise` cannot serve, and the reason it exists.

    A constructed ARN, a resource type, a log-group path — every one lives inside quotes, and
    `strip_noise` blanks exactly that. A sweep for one over its output finds nothing and reports
    the tree clean, which is the shape of guard this repo keeps paying for.
    """
    source = '  arns = ["arn:aws:lambda:us-east-1:1:function:x"] # arn:aws:lambda: in a comment\n'

    blanked = strip_comments(source)

    assert len(blanked) == len(source), "offsets taken here must still point into the original"
    assert "arn:aws:lambda:us-east-1:1:function:x" in blanked
    assert blanked.count("arn:aws:lambda:") == 1, "the comment's copy survived the blanking"
