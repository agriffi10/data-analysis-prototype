# ── Request Queue + DLQ ────────────────────────────────────
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
# (modules/base PR 1/2) were applied and propagated in an earlier deploy, so
# there is no self-grant race for this apply (the two-PR split is exactly what removes
# the need for the in-module propagation pause the shared-spaces module carries).

# THIS DLQ IS DELIBERATELY UNDRAINED, AND IT IS THE ONE HOLE SPEC-126 CANNOT CLOSE.
#
# Every OTHER control plane's request DLQ is drained back into a user notification
# (modules/control-plane-dlq-drain): a request that never started still reaches the person
# who made it. This queue is the exception, and not by oversight — the drain's only delivery
# channel IS the notifications queue, so draining this one would ask the queue that just
# failed to deliver a message to deliver the news about that failure. Circular by
# construction; a drain here would fail exactly when it was needed.
#
# What is actually needed here is an OPERATOR-facing signal, which is a different mechanism
# from the user-facing one SPEC-126 built, and out of its scope. Until that exists, a message
# in this queue is visible only to someone who looks. The 14-day retention is what buys that
# someone the time to look.
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
