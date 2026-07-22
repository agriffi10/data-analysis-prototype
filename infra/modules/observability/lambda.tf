# The scheduled log sweep (SPEC-127 FR-004).
#
# Terraform owns the function and a placeholder zip; CI deploys the real code and attaches the
# cpcommon layer. `ignore_changes` keeps `tofu apply` from reverting CI's deployed code.

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

  # MUST stay below the 5-minute schedule interval (so a slow sweep cannot still be running when
  # the next one fires) and below the queue's 360s visibility timeout (so in-flight messages
  # cannot become visible to the next sweep and be written to S3 twice).
  timeout     = 300
  memory_size = 256

  environment {
    variables = {
      LOGS_QUEUE_URL = aws_sqs_queue.logs.url
      ENV_NAME       = var.environment

      # ADMIN_BUCKET is genuinely used (the sweep writes under logs/); the rest are the
      # cpcommon layer's config._require union — the layer runs it AT IMPORT for every
      # attaching function, so omitting one crashes this function at COLD START rather than at
      # the line that would have used it (PR #196).
      ADMIN_BUCKET          = var.admin_bucket_name
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
      USER_SPACE_BUCKET     = var.user_space_bucket_name
      SHARED_SPACE_BUCKET   = var.shared_space_bucket_name
      ATHENA_WORKGROUP      = var.athena_workgroup
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
# 5 minutes, not the DLQ drain's 10: a log you cannot see for ten minutes is not usable while
# you are debugging the run that produced it. And not 1 minute: ~43k mostly-empty invocations a
# month would dominate this function's own log group, which is itself something you have to read
# when the pipe misbehaves. (User decision, 2026-07-22.)
resource "aws_cloudwatch_event_rule" "sweep" {
  name                = local.schedule_name
  description         = "Fires the SPEC-127 structured-logging sweep every 5 minutes."
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "sweep" {
  rule = aws_cloudwatch_event_rule.sweep.name
  arn  = aws_lambda_function.sweep.arn
}

# No invoke role is needed — EventBridge invokes Lambda through a resource policy on the
# function, scoped to this rule's ARN. Same mechanism as SPEC-126's sweep.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sweep.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
