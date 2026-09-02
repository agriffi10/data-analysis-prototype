# ── The username-directory builder + its daily schedule ────
# Terraform owns the function INFRASTRUCTURE; deploy-lambdas.yml owns which image it runs.
# See README.md.

module "build" {
  source = "../docker-lambda"

  function_name        = local.function_name
  role_arn             = aws_iam_role.build.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["build_directory.handler"]

  # The listing is delimited, so page count scales with USERS, not objects. This covers a
  # pathological directory rather than an ordinary one.
  timeout_seconds = 300
  memory_mb       = 512

  environment = merge({
    # USER_SPACE_BUCKET is the only one this function reads; the rest are the cpcommon
    # layer's union. Do not remove one because the builder does not use it — README.md.
    # test_build_directory.py asserts this block against config.py's own declaration.
    USER_SPACE_BUCKET   = var.user_space_bucket_name
    SHARED_SPACE_BUCKET = var.shared_space_bucket_name
    ATHENA_WORKGROUP    = var.athena_workgroup
    ADMIN_BUCKET        = var.admin_bucket_name
    # Deliberately NOT mirrored by a config._require: observability reads it with
    # os.environ.get, so losing it logs to stdout rather than crashing at cold start.
    LOGS_QUEUE_URL = var.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  })

  depends_on = [aws_iam_role_policy.build]
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
  arn  = module.build.function_arn
}

# Resource-based grant, so the schedule needs no invoke role (unlike EventBridge Scheduler).
# Scoped to this rule's ARN. Same shape as the sweep and the log sweep.
resource "aws_lambda_permission" "schedule" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = module.build.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.schedule.arn
}
