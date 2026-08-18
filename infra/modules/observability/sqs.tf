# The structured-logging transport, a FIFO queue.
#
# FIFO, like every other queue in this repo. It was STANDARD when it shipped, for a concrete
# reason: log-foundry's SQSSink built its batch entries as {"Id", "MessageBody"} and nothing
# else, and a FIFO queue REJECTS a SendMessageBatch that omits MessageGroupId — every batch
# would have failed and the events would have been abandoned to stderr. log-foundry 0.5.0
# added FIFO support, which removed that constraint.
#
# `.fifo` is not decoration: AWS requires a FIFO queue's name to end in it, and the name is a
# ForceNew attribute — so this rename is a DESTROY-AND-CREATE. The deploy role was granted
# DeleteQueue on the old name alongside CreateQueue on the new one in its own prior PR, because
# the single apply that performs the swap needs both.
#
# NO content_based_deduplication: log-foundry mints a fresh UUID MessageDeduplicationId per
# event, so every message is already unique. Turning content-based dedup on would be actively
# wrong — two identical events inside the 5-minute dedup window are a real thing for a
# retry-heavy control plane, and SQS would silently drop the second.
resource "aws_sqs_queue" "logs" {
  name                    = local.logs_queue_name
  fifo_queue              = true
  sqs_managed_sse_enabled = true

  # 14 days is HEADROOM AGAINST A BROKEN SWEEP, not the working buffer. The sweep runs every 10
  # minutes, so under normal operation a message lives for minutes; this is what gives a week
  # and a half to notice and fix a sweep that has stopped before anything is actually lost.
  message_retention_seconds = 1209600

  # MUST exceed the sweep function's timeout (300s). If visibility were shorter than the
  # function timeout, a slow sweep's in-flight messages would become visible again to the NEXT
  # scheduled sweep while the first is still working on them, and both would append them.
  visibility_timeout_seconds = 360

  # No redrive_policy, and no DLQ, deliberately. The only failure the sweep can suffer on a
  # message is a failed S3 write, which is not the message's fault — a maxReceiveCount would
  # move perfectly good events onto a second queue that nothing reads. FR-005 makes every
  # message routable (an unparseable body goes to logs/service=_unrouted/) and therefore
  # deletable, so there is no poison message for a DLQ to isolate.
}
