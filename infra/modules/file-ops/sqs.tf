# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser enqueues a file operation; an EventBridge
# Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the SHA-256 hex digest of "{bucket}/{sourceSpaceRoot}" (set
# by the producer), so requests against one space are DELIVERED in order while different
# spaces run in parallel. A HASH, never the raw path: SQS caps the group id at 128
# characters and an S3 key reaches 1024, so the raw form would be a length failure that
# only appears for deeply-nested spaces.
#
# ORDERED DELIVERY IS NOT SERIALIZED EXECUTION, and on this plane that distinction is the
# difference between working and losing data. The Pipe starts the machine
# FIRE_AND_FORGET and returns, so it is free to deliver the next message while the
# previous execution is still running — a delete removing objects a concurrent move has
# already relocated is silent, unrecoverable loss with versioning off. The serialization
# is the per-space lock inside the machine; this group id buys ordering and throughput
# isolation, and nothing else.
#
# content_based_deduplication is OFF: the producer sends an explicit
# MessageDeduplicationId = requestId as the double-submit guard, and two byte-identical
# operations a user genuinely repeats must NOT be silently absorbed by a 5-minute
# content-dedup window.
#
# ITS OWN QUEUE AND ITS OWN DLQ. A malformed file operation must never dead-letter
# someone's file send. The DLQ is registered with the drain sweep (root main.tf
# drained_dlq_names + dlq_drain.py SOURCES), so a dead-lettered request becomes a user
# notification rather than silence.
#
# No time_sleep guard here: the deploy-role grants these resource types need are applied
# in modules/base BEFORE this module's resources land.

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
