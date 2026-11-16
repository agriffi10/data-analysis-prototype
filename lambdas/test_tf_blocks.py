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

The block-comment and heredoc fixtures are written for the test, since the tree has no block
comment and one heredoc, but each was put through `tofu fmt -check` before it was pasted, so a
parser that agrees with them agrees with HCL.

Attributes:
  BLOCK_COMMENTED: A client retired with `/* */` and a live one whose revocation line is commented
    out the same way, with a brace the comment never opened.
  CLIENT: The client every silence case ends with; it must come back whole and switched on.
  HEREDOC_SOURCES: The variable from `infra/modules/auth/variables.tf` whose description is a
    heredoc, with a client header and an unbalanced brace added to the description, then a client
    whose own heredoc carries an assignment line and a closing brace.
  MODULE_CALL: The validated module call, verbatim.
  RESOURCE: The zip-packaged shape, lifted verbatim from what was then
    `infra/modules/observability/lambda.tf`, at the commit that branch left. It is the log sweep because that is a function declaring
    BOTH old spellings, `timeout` and `memory_size`, so neither arm is exercised against text
    written for the test.
"""

import pytest
from tf_blocks import (
    argument,
    argument_names,
    blocks,
    join_list_items,
    lambda_declaration,
    lambda_environment,
    lambda_input,
    map_entries,
    module_calls,
    span,
    strip_comments,
    strip_noise,
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
    assert argument_names(body)[-1] == "environment" and "ADMIN_BUCKET" not in argument_names(body), (
        "a name assigned inside the environment's map was listed as one of the call's own arguments"
    )


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


BLOCK_COMMENTED = '''/*
resource "aws_cognito_user_pool_client" "retired" {
  enable_token_revocation = false
}
*/

resource "aws_cognito_user_pool_client" "live" {
  name = "live"
  /* enable_token_revocation = true
     closes a brace it never opened } */
  allowed_oauth_flows = ["code"]
}
'''

HEREDOC_SOURCES = '''variable "logs_queue_url" {
  description = <<-EOT
    Structured-logging queue URL, set as LOGS_QUEUE_URL on both triggers.

    resource "aws_cognito_user_pool_client" "quoted" {
      enable_token_revocation = true
  EOT
  type        = string
}

resource "aws_cognito_user_pool_client" "real" {
  name                = "real"
  explanation         = <<EOT
enable_token_revocation = true
}
EOT
  allowed_oauth_flows = ["code"]
}
'''

CLIENT = '''
resource "aws_cognito_user_pool_client" "after" {
  enable_token_revocation = true
}
'''


def test_a_block_comment_hides_a_retired_client_and_a_commented_out_argument() -> None:
    """Both directions the revocation sweep was measured failing in before this parser knew `/* */`.

    The retired client was read as deployed and failed the sweep on a `false` nobody applies; the
    live client's commented-out `true` satisfied it while the client deploys with revocation off.
    The unbalanced brace inside the comment is the third failure: counted, it ends the live block
    before its last argument.
    """
    clients = blocks(BLOCK_COMMENTED, "aws_cognito_user_pool_client")

    assert set(clients) == {"live"}, "a client inside a block comment was read as declared"
    with pytest.raises(ValueError, match=r"no top-level .enable_token_revocation = ."):
        argument(clients["live"], "enable_token_revocation")
    assert argument(clients["live"], "allowed_oauth_flows") == '["code"]', (
        "a brace inside the block comment ended the block before its last argument"
    )
    assert argument_names(clients["live"]) == ["name", "allowed_oauth_flows"]


def test_a_heredoc_is_a_string_so_nothing_in_its_body_declares_or_assigns() -> None:
    """The heredoc form the tree already uses, carrying the three lines that misread it.

    A header quoted in a description became a client, an assignment line in a client's heredoc
    satisfied `argument`, and a `}` in one closed the block early. The value itself must come back
    whole, both markers included, not cut at the opener's line break.
    """
    clients = blocks(HEREDOC_SOURCES, "aws_cognito_user_pool_client")

    assert set(clients) == {"real"}, "a header quoted in a heredoc was read as a resource"
    with pytest.raises(ValueError, match=r"no top-level .enable_token_revocation = ."):
        argument(clients["real"], "enable_token_revocation")
    assert argument(clients["real"], "allowed_oauth_flows") == '["code"]'
    assert argument(clients["real"], "explanation") == "<<EOT\nenable_token_revocation = true\n}\nEOT"
    assert argument_names(clients["real"]) == ["name", "explanation", "allowed_oauth_flows"]


@pytest.mark.parametrize(
    "lookalike",
    [
        'locals {\n  arn = "arn:aws:glue:us-east-1:1:database/*"\n}\n',
        "# scoped to logs/* and never the bucket\n",
        "# an example: description = <<EOT\n",
        'locals {\n  note = <<-EOT\n    a line ending in EOT\n    EOTX\n    a " quote, a /* and a # that do nothing\n  EOT\n}\n',
        'locals {\r\n  note = <<-END-OF-NOTE\r\n    a " quote\r\n  END-OF-NOTE\r\n}\r\n',
        'locals {\n  objects = ["${format("%s/*", aws_s3_bucket.b.arn)}"]\n}\n',
        'locals {\n  text = "%{if var.on == "}"}a /* b%{endif}"\n}\n',
        'locals {\n  text = "%{if var.on == "a /* b"}x%{endif}"\n}\n',
        'locals {\n  pick = "x-${merge({ a = 1 }, { b = "/*" })["b"]}"\n}\n',
        'locals {\n  quoted = "a \\" /* b"\n}\n',
        'locals {\n  literal = "$${ /* "\n}\n',
    ],
    ids=[
        "comment-opener-in-a-string",
        "comment-opener-in-a-comment",
        "heredoc-opener-in-a-comment",
        "noise-in-a-heredoc",
        "crlf-heredoc-with-a-hyphenated-marker",
        "comment-opener-after-quotes-nested-in-an-interpolation",
        "brace-in-a-string-nested-in-a-directive",
        "comment-opener-after-quotes-nested-in-a-directive",
        "comment-opener-after-a-map-nested-in-an-interpolation",
        "comment-opener-after-an-escaped-quote",
        "escaped-template-opener",
    ],
)
def test_a_lookalike_opener_opens_nothing_and_the_next_client_is_read_whole(lookalike: str) -> None:
    """The silence cases, and the half a new lexer form gets wrong: an opener that is not one.

    Each lookalike, taken as real, runs to the end of the file and swallows the client after it.
    The first two are shapes the tree carries today, an ARN wildcard and a comment naming one; so
    are quotes nested in an interpolation, which end a string early for a scanner that does not
    follow ``${…}`` and expose whatever follows them, here a ``/*`` that blanked the file. In
    the heredoc, the lines that merely contain its marker come BEFORE the quote and the `/*`, so a
    marker matched mid-line closes the heredoc early and exposes them as code.
    """
    source = lookalike + CLIENT

    clients = blocks(source, "aws_cognito_user_pool_client")

    assert clients == {"after": "\n  enable_token_revocation = true\n"}, (
        "the client after the lookalike was swallowed, or its body was not cut at its own brace"
    )


def test_the_blankers_keep_length_and_disagree_only_about_strings() -> None:
    """Offsets taken from either blanker must slice the original, and each blanks its own forms.

    `strip_comments` keeps a heredoc body, since a sweep for a literal must still find it there,
    and every line break, since its callers split it into lines. `strip_noise` keeps only a
    heredoc's markers, and blanks a block comment's line breaks with the rest of it, since a value
    written across a comment is one value. Each is checked against the SOURCE's line breaks, not
    against the other blanker, which shares the code that would be wrong.
    """
    source = BLOCK_COMMENTED + HEREDOC_SOURCES
    comment_end = BLOCK_COMMENTED.index("*/") + 2

    comments_gone = strip_comments(source)
    noise_gone = strip_noise(source)

    assert len(comments_gone) == len(noise_gone) == len(source)
    assert comments_gone.count("\n") == source.count("\n"), "strip_comments lost a line break"
    assert "\n" not in noise_gone[:comment_end], "strip_noise kept a block comment's line break"
    assert "retired" not in comments_gone and "closes a brace" not in comments_gone
    assert "/*" not in comments_gone and "*/" not in comments_gone
    assert "Structured-logging queue URL" in comments_gone, "strip_comments blanked a heredoc body"
    assert "Structured-logging" not in noise_gone and "quoted" not in noise_gone
    assert "<<-EOT" in noise_gone and "<<EOT" in noise_gone and noise_gone.count("EOT") == 4


def test_a_quoted_key_in_a_heredoc_or_a_block_comment_is_not_a_map_entry() -> None:
    """The map reader keys on quoted strings, so it is the reader a quoted lookalike reaches first."""
    body = span(
        '{\n  "real" = 1\n  /* "ghost" = 2 } */\n  "note" = <<-EOT\n    "fake" = 3\n  EOT\n  "last" = 4\n}\n',
        0,
    )

    entries = map_entries(body)

    assert set(entries) == {"real", "note", "last"}
    assert entries["last"] == "4"


def test_a_value_written_across_a_block_comment_is_one_value() -> None:
    """HCL reads `1 /* … */ + 2` as `1 + 2` when the comment spans a line break; so must `argument`."""
    body = "  a = 1 /* spans\n  a line */ + 2\n  b = 3\n"

    assert argument(body, "a") == "1 /* spans\n  a line */ + 2"
    assert argument(body, "b") == "3"


@pytest.mark.parametrize(
    "unterminated",
    ["/* never closes }\n", "x = <<EOT\nnever closes }\n"],
    ids=["block-comment", "heredoc"],
)
def test_an_unterminated_form_runs_to_the_end_of_the_text(unterminated: str) -> None:
    """Input `tofu` refuses, read as never closing rather than closing on a brace inside the noise."""
    source = "{\n  " + unterminated

    assert span(source, 0) == source
    assert "}" not in strip_noise(source) and "never" not in strip_noise(source)


def test_a_commented_out_copy_of_a_joined_list_is_not_the_one_read() -> None:
    """`join_list_items` finds the FIRST `<name> = join(`, so a ghost copy above the live one wins.

    Measured before it read over `strip_comments`: a `/* */` copy above the live connect-src list
    returned the ghost's terms and none of the live ones, and the Cognito check passed on it.
    """
    source = (
        "locals {\n  /*\n  csp_connect_src = join(\" \", [\n    \"https://ghost.example\",\n  ])\n  */\n"
        "  csp_connect_src = join(\" \", [\n    \"https://live.example\", # the live term\n"
        "    local.term,\n  ])\n}\n"
    )

    assert join_list_items(source, "csp_connect_src") == (" ", ("https://live.example", "local.term"))


def test_a_commented_out_environment_block_is_not_the_one_read() -> None:
    """The nested-block arm of `lambda_environment` finds the first `environment {` line."""
    resource = (
        'resource "aws_lambda_function" "f" {\n  /*\n  environment {\n    variables = { GHOST = 1 }\n'
        "  }\n  */\n  environment {\n    variables = { LIVE = 1 }\n  }\n}\n"
    )

    environment = lambda_environment(lambda_declaration(resource, "f"))

    assert "LIVE" in environment and "GHOST" not in environment
