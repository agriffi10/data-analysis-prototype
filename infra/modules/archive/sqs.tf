# ── Request Queue + DLQ ────────────────────────────────────
# An ARCHIVE keys on the SHA-256 of "{bucket}/{sourceSpaceRoot}" — a HASH, never the raw path.
# A RESTORE keys on the archive root instead. The API derives that key when it enqueues, so no
# caller chooses it; docs/testing/owed.md §2.2 spells it out for a hand-built request.
#
# ⚠ NEITHER KEY SERIALIZES EXECUTION. The Pipe starts the machine FIRE_AND_FORGET, so a group
# orders the STARTS, and two archives from one space or two restores of one archive run at once.
# The commit gate is what keeps overlapping archives safe. Overlapping restores are not safe: the
# copy-back overwrites, so a second restore can land on a file the user edited after the first.
# README.md says what each overlap does.
#
# content_based_deduplication is OFF; the explicit MessageDeduplicationId IS the archive's
# permanent identity, so a resend cannot open a second archive under a second uuid. Past the
# five-minute window it opens a second RUN under the same one, which the queue does not stop.
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
