# The structured-logging transport, a FIFO queue.
#
# NO content_based_deduplication, and turning it on would be actively wrong: log-foundry mints a
# fresh UUID MessageDeduplicationId per event, and two identical events inside the 5-minute
# window are ordinary for a retry-heavy plane — SQS would silently drop the second.
#
# `.fifo` is a ForceNew attribute, so renaming this queue is a DESTROY-AND-CREATE. README.md.
resource "aws_sqs_queue" "logs" {
  name                    = local.logs_queue_name
  fifo_queue              = true
  sqs_managed_sse_enabled = true

  # HEADROOM AGAINST A BROKEN SWEEP, not the working buffer — normally a message lives for
  # minutes. This is the week and a half to notice one that has stopped.
  message_retention_seconds = 1209600

  # MUST exceed the function timeout (300s), or a slow sweep's in-flight messages become
  # visible to the next sweep and both append them.
  visibility_timeout_seconds = 360

  # No redrive_policy and no DLQ, deliberately: every message is routable (an unparseable body
  # goes to logs/service=_unrouted/), so there is no poison message to isolate. README.md.
}
