# ── The drain Lambda and its scheduled sweep ───────────────────────────────
# ONE function over FOUR queues; the per-domain differences are a table in the handler. A fifth
# plane is one map entry and one more ARN in DLQ_ARNS. README.md.

data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/control-plane-dlq-drain-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('control-plane-dlq-drain Lambda code not yet deployed by CI')\n"
    filename = "dlq_drain.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
#
# THIS LOG GROUP IS THE ONLY COPY OF A DEAD-LETTERED BODY — consuming a DLQ message deletes it.
# Shortening this retention shortens the forensic window. README.md.
resource "aws_cloudwatch_log_group" "drain" {
  name              = local.log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "drain" {
  function_name = local.function_name
  role          = aws_iam_role.drain.arn
  runtime       = "python3.12"
  handler       = "dlq_drain.handler"
  # The handler's per-queue round cap already bounds a sweep well under this.
  timeout     = 60
  memory_size = 256

  environment {
    variables = {
      # The Cognito pair, the notifications URL and DLQ_ARNS are genuinely used; the buckets
      # and workgroup are the cpcommon layer's union. Do not prune one — README.md.
      COGNITO_USER_POOL_ID    = var.user_pool_id
      COGNITO_APP_CLIENT_ID   = var.app_client_id
      NOTIFICATIONS_QUEUE_URL = var.notifications_queue_url
      DLQ_ARNS                = jsonencode(var.dlq_arns)
      USER_SPACE_BUCKET       = var.user_space_bucket_name
      SHARED_SPACE_BUCKET     = var.shared_space_bucket_name
      ADMIN_BUCKET            = var.admin_bucket_name
      ATHENA_WORKGROUP        = var.athena_workgroup
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
    aws_iam_role_policy.drain,
    aws_cloudwatch_log_group.drain,
  ]
}

# ── The scheduled sweep trigger ──────────────────────────────────────────────
# ONE rule every 10 minutes; the handler polls all four DLQs itself. This replaced four
# always-on event-source mappings whose idle long-polling dominated the account's SQS volume.
#
# NOTHING re-drives a message: the sweep deletes every message it reads, notified or not.
# README.md.
resource "aws_cloudwatch_event_rule" "sweep" {
  name                = "${local.function_name}-sweep"
  description         = "Sweep the control-plane request DLQs into user notifications every 10 minutes."
  schedule_expression = "rate(10 minutes)"
}

resource "aws_cloudwatch_event_target" "sweep" {
  rule = aws_cloudwatch_event_rule.sweep.name
  arn  = aws_lambda_function.drain.arn
}

# Resource-based grant, so the sweep needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowEventBridgeSweep"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.drain.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
