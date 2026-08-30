# The scheduled log sweep. Terraform owns the function and a placeholder zip; CI deploys the
# real code and attaches the cpcommon layer. See README.md.

data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/.placeholder-log-sweep.zip"

  source {
    filename = "log_sweep.py"
    content  = "def handler(event, context):\n    return {'placeholder': True}\n"
  }
}

resource "aws_cloudwatch_log_group" "sweep" {
  name              = "/aws/lambda/${local.sweep_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "sweep" {
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
  arn  = aws_lambda_function.sweep.arn
}

# No invoke role needed — EventBridge invokes through this resource policy, scoped to the rule.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sweep.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
