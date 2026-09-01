# ── Feedback-writer Lambda and its trigger ───────────────────────────
# The single writer of each day's feedback document. Triggered directly by the queue.
# Terraform owns the function INFRASTRUCTURE + a placeholder zip; CI owns the code. README.md.

data "archive_file" "writer_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/feedback-writer-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('feedback-writer Lambda code not yet deployed by CI')\n"
    filename = "feedback_writer.py"
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
  handler       = "feedback_writer.handler"
  timeout       = 30

  environment {
    variables = {
      ADMIN_BUCKET = var.admin_bucket_name
      # Optional BY CONSTRUCTION — observability reads it with os.environ.get, so a writer
      # without it logs to stdout rather than failing at cold start. Passed so it is set in
      # practice.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.writer_placeholder.output_path
  source_code_hash = data.archive_file.writer_placeholder.output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment. Without `layers` here, an apply landing after a
    # deploy strips the cpcommon layer back off and the function fails at its next cold start on
    # an import that had been working.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.writer,
    aws_cloudwatch_log_group.writer,
  ]
}

# Batch size 1 so each FIFO message is its own invocation — this is what preserves the
# one-day-at-a-time processing the single-writer model relies on. The handler REFUSES a batch
# rather than absorbing one, so raising this is a change somebody has to make on purpose.
resource "aws_lambda_event_source_mapping" "writer" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = aws_lambda_function.writer.arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.writer]
}
