# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser enqueues an archive request; an EventBridge
# Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with MessageGroupId = the SHA-256 hex digest of "{bucket}/{sourceSpaceRoot}" (set
# by the producer, FR-004), so repeated archives OUT OF one space serialize strictly
# one-at-a-time while archives from different spaces run in parallel. THAT SERIALISATION
# IS WANTED HERE, not merely tolerated: two archives from one space may select
# overlapping folders, and an archive DELETES its source — so two running at once could
# have one deleting objects the other is still copying.
#
# A HASH, never the raw path: SQS caps the group id at 128 characters and an S3 key
# reaches 1024, so the raw form would be a length failure that only appears for deeply
# nested sources (the reason first recorded for data quality).
#
# A RESTORE KEYS ON THE ARCHIVE, NOT THE SPACE: MessageGroupId is the
# SHA-256 of "{archiveBucket}/{archiveRoot}", so two restores OF ONE ARCHIVE serialize
# while restores of different archives in the same space proceed in parallel. Without it a
# double-submitted restore can pass the destination guard twice before either copy lands —
# the guard is a read, and two of them see the same empty destinations. **NOTHING ENFORCES
# THIS YET.** The producer is the browser, which SPEC-172 builds; SPEC-170 could not
# enforce a rule about a message nothing in it sends, and the contract is recorded here
# rather than left in a spec file, because this is where its reader will be standing.
# `docs/testing/owed.md` §2.2 types it correctly so the live check exercises it.
#
# content_based_deduplication is OFF (FR-003): the producer sends an explicit
# MessageDeduplicationId = requestId (FR-004) as the double-submit guard. That id is also
# the archive's permanent identity, which makes the two properties one: a resend of the
# same request cannot open a second archive under a second uuid.
#
# ITS OWN QUEUE AND ITS OWN DLQ. A malformed archive must never dead-letter someone's
# file send. The DLQ is registered with the drain sweep (root main.tf
# drained_dlq_names + dlq_drain.py SOURCES), so a dead-lettered archive becomes a user
# notification rather than silence.
#
# No time_sleep guard here: the deploy-role grants these resource types need are applied
# before this module's resources land (the deploy-perms-before-resources rule), so there
# is no self-grant propagation race to wait out.

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
