# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser enqueues a check-data-quality
# request; an EventBridge Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the SHA-256 HEX DIGEST of the canonical target location
# (set by the producer), so two checks of the SAME location serialize while
# checks of different locations run in parallel. The digest — not the raw location — is
# deliberate: SQS caps MessageGroupId at 128 characters and S3 keys reach 1024, so a raw
# location would be rejected outright. The other producers get away with raw ids only
# because they group by a bounded catalog identifier (a database name).
#
# content_based_deduplication is OFF (FR-001): the producer sends an explicit
# MessageDeduplicationId = requestId, which is the real double-submit guard.
# Content dedup would be actively wrong here — two DIFFERENT requestIds checking the same
# location within the 5-minute window are byte-different anyway, but a re-check of the
# same location with the same body is a legitimate re-run the user asked for.
#
# No time_sleep guard here: the deploy-role grants these resource types need were applied
# in modules/base (deploy-data-quality) BEFORE this module's resources
# land (the deploy-perms-before-resources rule), so there is no self-grant race to wait out.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                       = local.requests_queue_name
  fifo_queue                 = true
  visibility_timeout_seconds = 60
  sqs_managed_sse_enabled    = true

  # OFF by design — the producer's explicit MessageDeduplicationId (= requestId) is the
  # dedup key (FR-001). Do not turn this on: it would collapse a deliberate re-check of
  # an unchanged location into a no-op inside the 5-minute dedup window.
  content_based_deduplication = false

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
