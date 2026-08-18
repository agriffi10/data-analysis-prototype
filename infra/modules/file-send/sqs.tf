# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser enqueues a send request; an EventBridge
# Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the SHA-256 hex digest of "{bucket}/{sourceSpaceRoot}"
# (set by the producer, FR-002), so repeated sends OUT OF one space serialize strictly
# one-at-a-time while sends from different spaces run in parallel. A HASH, never the
# raw path: SQS caps the group id at 128 characters and an S3 key reaches 1024, so the
# raw form would be a length failure that only appears for deeply-nested sources.
#
# content_based_deduplication is OFF (FR-001): the producer sends an explicit
# MessageDeduplicationId = requestId (FR-002) as the double-submit guard, and two
# byte-identical sends a user genuinely repeats must NOT be silently absorbed by a
# 5-minute content-dedup window.
#
# ITS OWN QUEUE AND ITS OWN DLQ, which is half the reason this plane is not a mode of
# table share: a malformed send must never dead-letter someone's table share. The DLQ
# is registered with the drain sweep (root main.tf drained_dlq_names +
# dlq_drain.py SOURCES), so a dead-lettered send becomes a user notification rather
# than silence.
#
# No time_sleep guard here: the deploy-role grants these resource types need were
# applied in the SPEC-164 PR1 (modules/base deploy-file-send policy) BEFORE this
# module's resources land (the deploy-perms-before-resources rule), so there is no
# self-grant propagation race to wait out.

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
