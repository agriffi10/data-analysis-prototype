# ── The drain Lambda and its scheduled sweep ───────────────────────────────
# ONE function over FOUR queues; the per-domain differences are a table in the handler. A fifth
# plane is one map entry and one more ARN in DLQ_ARNS. README.md.

module "drain" {
  source = "../docker-lambda"

  function_name        = local.function_name
  role_arn             = aws_iam_role.drain.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag
  command              = ["dlq_drain.handler"]

  # The handler's per-queue round cap already bounds a sweep well under this.
  timeout_seconds = 60
  memory_mb       = 256

  environment = merge({
    # The Cognito pair, the notifications URL and DLQ_ARNS are genuinely used; the buckets
    # and workgroup are the shared code's union. Do not prune one — README.md.
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
  })

  # THE LOG GROUP IS THE ONLY COPY OF A DEAD-LETTERED BODY — consuming a DLQ message deletes
  # it — so the module's retention is what bounds the forensic window. README.md.
  depends_on = [aws_iam_role_policy.drain]
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
  arn  = module.drain.function_arn
}

# Resource-based grant, so the sweep needs no invoke role. Scoped to this rule's ARN.
resource "aws_lambda_permission" "sweep" {
  statement_id  = "AllowEventBridgeSweep"
  action        = "lambda:InvokeFunction"
  function_name = module.drain.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.sweep.arn
}
