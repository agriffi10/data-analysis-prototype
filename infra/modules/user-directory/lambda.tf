# ── The username-directory builder + its daily schedule ────
# One function, one schedule, one published object. It lists the user-space bucket's
# top-level common prefixes and publishes them as a sorted JSON document the browser reads to
# suggest usernames.
#
# Code-ownership split (architecture.md): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml owns the Python code and attaches
# the cpcommon layer. `ignore_changes` keeps `tofu apply` from reverting CI's deployed code.

data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/user-directory-build-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('user-directory-build Lambda code not yet deployed by CI')\n"
    filename = "build_directory.py"
  }
}

# Explicit log group so retention is managed (Lambda would otherwise create one with infinite
# retention on first invoke). 14 days, matching every other function here.
resource "aws_cloudwatch_log_group" "build" {
  name              = local.log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "build" {
  function_name = local.function_name
  role          = aws_iam_role.build.arn
  runtime       = "python3.12"
  handler       = "build_directory.handler"
  # Headroom for a bucket with many thousands of workspace prefixes. The listing is delimited
  # to top-level common prefixes, so the page count scales with USERS, not with objects — the
  # ceiling here covers a pathological directory rather than an ordinary one.
  timeout     = 300
  memory_size = 512

  environment {
    variables = {
      # USER_SPACE_BUCKET is the one variable this function actually uses. The rest are here
      # because the cpcommon layer's config requires them of every function that attaches it.
      # SPEC-156 FR-004 moved that from import to FIRST READ, so a missing one no longer
      # crashes at COLD START (the table-builder break PR #196, and the nine-day signup outage
      # PR #317) — it fails on whichever branch reads it, which is narrower and no less broken.
      # lambdas/user-directory-build/test_build_directory.py asserts this block against
      # config.py's own declaration rather than against a hand-kept copy.
      USER_SPACE_BUCKET     = var.user_space_bucket_name
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
      SHARED_SPACE_BUCKET   = var.shared_space_bucket_name
      ADMIN_BUCKET          = var.admin_bucket_name
      ATHENA_WORKGROUP      = var.athena_workgroup
      # Deliberately NOT mirrored by a config._require on the Lambda side:
      # cpcommon.observability reads it with os.environ.get, so a builder that somehow loses
      # this variable logs to stdout and still publishes rather than crashing at cold start.
      LOGS_QUEUE_URL = var.logs_queue_url
      # `env` shipped empty on every record. Same source of truth as the
      # feature-flag document's `environments` keys (`var.environment`, default "prod").
      ENV_NAME = var.environment
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
    aws_iam_role_policy.build,
    aws_cloudwatch_log_group.build,
  ]
}

# ── The daily rebuild trigger ────────────────────────────────────────────────
# `rate(24 hours)` rather than a cron expression: nothing depends on the rebuild landing at a
# particular hour, and a rate schedule cannot be wrong about a timezone.
#
# The document is rebuilt from scratch every run — there is no incremental state, so nothing
# reconciles and a missed run costs staleness, never correctness. A user provisioned just
# after a run is absent from the suggestions for up to a day; they can still be added by
# typing the name, because every consumer accepts a name that is not in the list
# (SPEC-147 FR-005). That bound is the whole reason a daily schedule is sufficient.
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.function_name}-schedule"
  description         = "Rebuild the username directory from the user-space bucket's workspace prefixes, once a day."
  schedule_expression = "rate(24 hours)"
}

resource "aws_cloudwatch_event_target" "schedule" {
  rule = aws_cloudwatch_event_rule.schedule.name
  arn  = aws_lambda_function.build.arn
}

# Resource-based grant so the rule (events.amazonaws.com) may invoke the function — this is
# why the schedule needs no separate invoke role, unlike EventBridge Scheduler. Scoped to this
# rule's ARN. Same shape as the sweep and the log sweep.
resource "aws_lambda_permission" "schedule" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.build.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
