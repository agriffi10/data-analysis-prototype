# The scheduled log sweep. Terraform owns the function; CI owns which image it runs. See README.md.

module "sweep" {
  source = "../docker-lambda"

  function_name        = local.sweep_name
  role_arn             = aws_iam_role.sweep.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["log_sweep.handler"]

  # ORDERED: timeout < queue visibility (360s) < schedule interval (600s). Breaking either
  # inequality writes messages to S3 twice. README.md.
  timeout_seconds = 300
  # 512, not 256 — the sweep reads the day's whole object back before appending.
  memory_mb = 512

  # Passed through rather than left to the module's default, so this module's own retention
  # variable still decides its log group's retention.
  log_retention_days = var.log_retention_days

  environment = merge({
    LOGS_QUEUE_URL = aws_sqs_queue.logs.url
    ENV_NAME       = var.environment

    # ADMIN_BUCKET is genuinely used; the rest are the shared code's required union.
    # Do not remove one because the sweep does not read it — README.md.
    ADMIN_BUCKET        = var.admin_bucket_name
    USER_SPACE_BUCKET   = var.user_space_bucket_name
    SHARED_SPACE_BUCKET = var.shared_space_bucket_name
    ATHENA_WORKGROUP    = var.athena_workgroup
  })

  # The sweep policy is NOT in this list, and cannot be: it renders this module's own log-group
  # ARN, so depending on it here is a cycle. ../docker-lambda/README.md.
}

# ── The schedule ─────────────────────────────────────────────────────────────
# 10 minutes (user decision, 2026-07-23), matching the DLQ drain. Must stay ABOVE the function
# timeout. README.md.
resource "aws_cloudwatch_event_rule" "sweep" {
  name                = local.schedule_name
  description         = "Fires the structured-logging sweep every 10 minutes."
  schedule_expression = "rate(10 minutes)"
}

resource "aws_cloudwatch_event_target" "sweep" {
  rule = aws_cloudwatch_event_rule.sweep.name
  arn  = module.sweep.function_arn
}

# No invoke role needed — EventBridge invokes through this resource policy, scoped to the rule.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = module.sweep.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
