# ── Notifications-writer Lambda + trigger (SPEC-058 FR-001/FR-004/FR-005) ─────
# The single writer of every user's notifications.json. The request queue triggers it
# directly via an SQS event-source mapping (batch size 1 → one message = one
# invocation). The handler is an action-switch read-modify-write; for user-originated
# actions it verifies the caller's Cognito ID token against the pool JWKS (offline — no
# Cognito IAM needed) and derives the target username from the verified claim.
#
# Code-ownership split (architecture.md, SPEC-012): Terraform owns the function
# INFRASTRUCTURE + a placeholder zip; deploy-lambdas.yml owns the Python code (builds
# lambdas/notifications-writer, uploads it, update-function-code). `ignore_changes`
# keeps `tofu apply` from reverting CI's deployed code.

data "archive_file" "writer_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/notifications-writer-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('notifications-writer Lambda code not yet deployed by CI')\n"
    filename = "notifications_writer.py"
  }
}

# Explicit log group so retention is managed (Lambda would otherwise create one with
# infinite retention on first invoke). 14-day retention (matches SPEC-012/033).
resource "aws_cloudwatch_log_group" "writer" {
  name              = local.lambda_log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "writer" {
  function_name = local.writer_function_name
  role          = aws_iam_role.writer.arn
  runtime       = "python3.12"
  handler       = "notifications_writer.handler"
  timeout       = 30

  environment {
    variables = {
      USER_SPACE_BUCKET     = var.user_space_bucket_name
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
      NOTIFICATIONS_MAX     = tostring(var.notifications_max)
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.writer_placeholder.output_path
  source_code_hash = data.archive_file.writer_placeholder.output_base64sha256

  lifecycle {
    # CI owns the code — never revert it on apply.
    ignore_changes = [filename, source_code_hash]
  }

  depends_on = [
    aws_iam_role_policy.writer,
    aws_cloudwatch_log_group.writer,
  ]
}

# SQS event-source mapping — the queue triggers the writer directly (no Pipe, no Step
# Function). Batch size 1 so each FIFO message is its own invocation, preserving the
# per-user one-at-a-time processing the single-writer model relies on (FR-001/FR-004).
resource "aws_lambda_event_source_mapping" "writer" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = aws_lambda_function.writer.arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.writer]
}
