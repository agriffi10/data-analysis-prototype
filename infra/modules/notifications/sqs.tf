# ── Request Queue + DLQ ────────────────────────────────────
# The write-path entry point. NO Pipe and NO Step Function — a one-task write does not get a
# state machine.
#
# FIFO with MessageGroupId = the TARGET USERNAME. That, plus batch size 1, is what makes
# single-writer-per-user true without a lock. README.md.

# THIS DLQ IS DELIBERATELY UNDRAINED, AND IT IS THE ONE HOLE THE DRAIN CANNOT CLOSE — the
# drain's only delivery channel IS this queue, so draining it is circular. A message here is
# visible only to someone who looks, and the 14-day retention is what buys them the time.
# README.md.
resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

# DEDUPLICATION IS PER RECIPIENT. Most producers key a notice on a request id, and a request
# id is chosen by whoever sent the request. Deduplicated across the whole queue, a request carrying
# somebody else's id dropped that person's notice if it landed within five minutes. Scoped to the
# message group — the recipient's username — two notices collapse only when they go to the same
# person, which is every duplicate a producer means to collapse. Throughput stays per queue.
resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = true
  deduplication_scope         = "messageGroup"
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
