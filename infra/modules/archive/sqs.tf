# ── Request Queue + DLQ ────────────────────────────────────
# An ARCHIVE keys on the SHA-256 of "{bucket}/{sourceSpaceRoot}" — a HASH, never the raw path.
# THAT SERIALISATION IS WANTED, not merely tolerated: two archives from one space may select
# overlapping folders, and an archive DELETES its source, so two at once could have one
# deleting objects the other is still copying.
#
# A RESTORE KEYS ON THE ARCHIVE, NOT THE SPACE, or a double-submitted restore passes the
# destination guard twice before either copy lands — the guard is a READ. The API derives that
# key from the archive root when it enqueues, so no caller chooses it; docs/testing/owed.md §2.2
# spells it out for a hand-built request.
#
# content_based_deduplication is OFF; the explicit MessageDeduplicationId IS the archive's
# permanent identity, so a resend cannot open a second archive under a second uuid.
#
# Its OWN queue and its OWN DLQ, registered with the drain sweep. README.md.

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
