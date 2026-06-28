# ── Request Queue + DLQ (SPEC-058 FR-001) ────────────────────────────────────
# The write-path entry point. Producers enqueue an action-discriminated envelope
# (create | markRead | markAllRead); an SQS event-source mapping (lambda.tf) invokes
# the notifications-writer Lambda directly, batch size 1 — NO EventBridge Pipe and NO
# Step Function (best-practices/lambdas §10: no Step Function for a one-task write).
#
# FIFO with MessageGroupId = the TARGET USERNAME (a producer convention). FIFO then
# delivers a single user's messages strictly in arrival order, one at a time (the next
# isn't released until the prior is deleted), so the writer never races itself on one
# user's notifications.json — single-writer-per-user without a lock or Step Function.
# Different users = different groups = may process concurrently (different files, no
# contention). Content-based dedup collapses an accidental byte-identical re-send within
# the 5-minute window (e.g. a double-click); producers may still set an explicit
# MessageDeduplicationId (FR-003).
#
# No time_sleep guard here: the deploy-role grants these resource types need
# (modules/base, SPEC-058 PR 1/2) were applied and propagated in an earlier deploy, so
# there is no self-grant race for this apply (the two-PR split is exactly what removes
# the need for the in-module propagation pause the shared-spaces module carries).

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
