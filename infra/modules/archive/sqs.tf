# ── Request Queue + DLQ ────────────────────────────────────
# An ARCHIVE keys on the SHA-256 of "{bucket}/{sourceSpaceRoot}" — a HASH, never the raw path.
# A RESTORE keys on the archive root instead. The API derives that key when it enqueues, so no
# caller chooses it; docs/testing/owed.md §2.2 spells it out for a hand-built request.
#
# ⚠ NEITHER KEY SERIALIZES EXECUTION. The Pipe starts the machine FIRE_AND_FORGET, so a group
# orders the STARTS, and two archives from one space or two restores of one archive can run at
# once. The commit gate is what keeps overlapping archives of DIFFERENT ids safe. Two restores of
# one archive still both run, and still both report — what is no longer at risk is the user's
# data: every restore manifest line is a conditional write, so a copy-back never lands on a file
# that was not there when it started. README.md says what each overlap does.
#
# content_based_deduplication is OFF; the explicit MessageDeduplicationId IS the archive's
# permanent identity, so a resend cannot open a second archive under a second uuid. Past the
# five-minute window it opens a second RUN under the same one, which the queue does not stop —
# and inspect-source claims the id with a create-only write before it writes anything else, so
# the second run refuses before it can reach the first run's archive. That claim, not this queue,
# is what closed this plane's one unrecoverable case.
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
