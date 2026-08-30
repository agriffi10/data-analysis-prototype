# ── Notifications-writer Lambda and its trigger ───────────────────────────
# The single writer of every user's notifications.json, triggered directly by the queue.
# Terraform owns the function INFRASTRUCTURE + a placeholder zip; CI owns the code.
# README.md.

data "archive_file" "writer_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/notifications-writer-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('notifications-writer Lambda code not yet deployed by CI')\n"
    filename = "notifications_writer.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
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
      USER_SPACE_BUCKET = var.user_space_bucket_name
      NOTIFICATIONS_MAX = tostring(var.notifications_max)
      # The portal role's IAM unique ID — the half of SenderId before the ':'. NEVER the
      # role name or ARN: SenderId carries neither, and a wrong value never matches, which
      # reads exactly like a control that works. Unset, the writer refuses EVERY create.
      NOTIFICATIONS_UNTRUSTED_SENDER_ID = var.portal_role_unique_id
      # Optional BY CONSTRUCTION — observability reads it with os.environ.get, so a writer
      # without it logs to stdout rather than failing at cold start.
      #
      # ADMIN_BUCKET, SHARED_SPACE_BUCKET and ATHENA_WORKGROUP are absent ON PURPOSE, and a
      # probe imports the module without them (test_layer_import_safety.py). README.md.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.writer_placeholder.output_path
  source_code_hash = data.archive_file.writer_placeholder.output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment. `layers` was once missing here while the
    # code already imported cpcommon — an apply after a deploy stripped the layer back off.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.writer,
    aws_cloudwatch_log_group.writer,
  ]
}

# Batch size 1 so each FIFO message is its own invocation — this is what preserves the
# per-user one-at-a-time processing the single-writer model relies on.
resource "aws_lambda_event_source_mapping" "writer" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = aws_lambda_function.writer.arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.writer]
}
