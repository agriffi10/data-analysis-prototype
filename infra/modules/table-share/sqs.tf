# ── Request Queue + DLQ (SPEC-088 FR-001) ────────────────────────────────────
# The control-plane entry point. The browser (SPEC-089/093) enqueues a share-table
# request; an EventBridge Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the SOURCE `database.table` (set by the producer,
# SPEC-089), so repeated shares of the SAME source serialize strictly one-at-a-time
# (a heavy copy never overlaps itself), while shares of different sources run in
# parallel. The Pipe reads a batch of 1 (pipe.tf).
#
# content_based_deduplication is OFF (SPEC-088 FR-001, unlike the table-builder
# queue): the producer sends an explicit MessageDeduplicationId = requestId
# (SPEC-089) as the double-submit guard, and two byte-identical share requests a
# user genuinely repeats (e.g. re-share after deleting the copy) must NOT be
# silently absorbed by a 5-minute content-dedup window.
#
# No time_sleep guard here: the deploy-role grants these resource types need were
# applied in the SPEC-088 PR1 (modules/base deploy-table-share policy) BEFORE this
# module's resources land (the deploy-perms-before-resources rule), so there is no
# self-grant propagation race to wait out — same as the table-builder module.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = false
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = false
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
