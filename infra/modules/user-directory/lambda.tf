# ── The username-directory builder + its daily schedule ────
# Terraform owns the function INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml owns the
# Python code and the cpcommon layer. See README.md.

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
  # The listing is delimited, so page count scales with USERS, not objects. This covers a
  # pathological directory rather than an ordinary one.
  timeout     = 300
  memory_size = 512

  environment {
    variables = {
      # USER_SPACE_BUCKET is the only one this function reads; the rest are the cpcommon
      # layer's union. Do not remove one because the builder does not use it — README.md.
      # test_build_directory.py asserts this block against config.py's own declaration.
      USER_SPACE_BUCKET   = var.user_space_bucket_name
      SHARED_SPACE_BUCKET = var.shared_space_bucket_name
      ADMIN_BUCKET        = var.admin_bucket_name
      ATHENA_WORKGROUP    = var.athena_workgroup
      # Deliberately NOT mirrored by a config._require: observability reads it with
      # os.environ.get, so losing it logs to stdout rather than crashing at cold start.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
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
# Rebuilt from scratch every run: a missed run costs staleness, never correctness. Why daily is
# sufficient, and why `rate` rather than `cron`: README.md.
resource "aws_cloudwatch_event_rule" "schedule" {
  name                = "${local.function_name}-schedule"
  description         = "Rebuild the username directory from the user-space bucket's workspace prefixes, once a day."
  schedule_expression = "rate(24 hours)"
}

resource "aws_cloudwatch_event_target" "schedule" {
  rule = aws_cloudwatch_event_rule.schedule.name
  arn  = aws_lambda_function.build.arn
}

# Resource-based grant, so the schedule needs no invoke role (unlike EventBridge Scheduler).
# Scoped to this rule's ARN. Same shape as the sweep and the log sweep.
resource "aws_lambda_permission" "schedule" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.build.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
