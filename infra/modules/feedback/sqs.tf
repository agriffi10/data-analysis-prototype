# ── Request Queue + DLQ ────────────────────────────────────
# The write-path entry point. NO Pipe and NO Step Function — a one-task append does not get a
# state machine. README.md.
#
# FIFO with MessageGroupId = the SUBMISSION'S UTC DATE, set by the API. That, plus batch size 1,
# is what makes single-writer-per-day true without a lock: every message destined for one day's
# object waits for the previous one, which is precisely the contention the writer's
# compare-and-swap would otherwise have to retry through.

# ITS OWN DLQ, never another plane's. A malformed feedback submission must not dead-letter
# somebody's file operation.
#
# THIS DLQ IS DELIBERATELY UNDRAINED (`dlq_drain.UNDRAINED_QUEUES`), and for a different reason
# from the notifications one: the drain notifies from the verified identity in the message body,
# and this body carries none by design — the API verified the caller and the browser never touches
# this queue. Draining it would mean notifying from an untrusted body field, which is the exact
# inversion the drain exists to prevent. README.md.
resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed submissions for inspection
  sqs_managed_sse_enabled     = true
}

# `content_based_deduplication` is OFF on purpose. The API sets an explicit
# MessageDeduplicationId (the event id) on every send, and with the fallback available a send
# that stopped setting one would still mostly collapse double-submits — so the guard would be
# gone with nothing going red. A test pins this value; the contract's dedup registry is keyed to
# the ten enqueue routes and this queue is deliberately not one of them, so there is no second
# record to hold it against.
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
