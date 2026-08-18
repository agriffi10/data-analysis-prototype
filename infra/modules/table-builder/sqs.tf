# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser enqueues a create-table
# request; an EventBridge Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the target DATABASE (set by the producer), so
# two concurrent "create table X" requests against the SAME database serialize
# strictly one-at-a-time (the duplicate-name race is closed by check-table-absent +
# CREATE … IF NOT EXISTS), while creates in DIFFERENT databases run in parallel. The
# Pipe reads a batch of 1 (pipe.tf).
#
# content_based_deduplication is on, but the producer ALSO sends an explicit
# MessageDeduplicationId = requestId: the explicit id is the real
# double-submit guard; content dedup just usefully absorbs a byte-identical retry
# inside the 5-minute window. Per-DB serialization comes from MessageGroupId, above.
#
# No time_sleep guard here: the deploy-role grants these resource types need were
# applied in the SPEC-066 PR1 (modules/base deploy-policy-table-builder) BEFORE this
# module's resources land (the deploy-perms-before-resources rule), so there is no
# self-grant propagation race to wait out — same as the notifications module.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
