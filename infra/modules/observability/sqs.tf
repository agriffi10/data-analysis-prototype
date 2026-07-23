# The structured-logging transport (SPEC-127 FR-002).
#
# STANDARD, not FIFO — and it is the only queue in this repo that isn't. This is not an
# oversight to be tidied up later: log-foundry's SQSSink builds its batch entries as
# {"Id": ..., "MessageBody": ...} and nothing else — no MessageGroupId, no
# MessageDeduplicationId — and a FIFO queue REJECTS a SendMessageBatch that omits them. On a
# FIFO queue every batch would fail, the sink's worker would retry three times, and the events
# would be abandoned to stderr.
#
# What standard delivery costs, and why neither cost lands here:
#   - No ordering guarantee. Ordering was never a property of the queue anyway; every event
#     carries `timestamp` and `span_id`, so order is reconstructed at read time.
#   - At-least-once delivery. Every event carries a unique `log_id`, so duplicates collapse on
#     it at read time. The sweep's put-then-delete ordering (FR-005) can also produce duplicates
#     deliberately — losing logs is worse than duplicating them.
resource "aws_sqs_queue" "logs" {
  name                    = local.logs_queue_name
  sqs_managed_sse_enabled = true

  # 14 days is HEADROOM AGAINST A BROKEN SWEEP, not the working buffer. The sweep runs every 5
  # minutes, so under normal operation a message lives for seconds; this is what gives a week
  # and a half to notice and fix a sweep that has stopped before anything is actually lost.
  message_retention_seconds = 1209600

  # MUST exceed the sweep function's timeout (300s). If visibility were shorter than the
  # function timeout, a slow sweep's in-flight messages would become visible again to the NEXT
  # scheduled sweep while the first is still working on them, and both would write them to S3.
  visibility_timeout_seconds = 360

  # No redrive_policy, and no DLQ, deliberately. The only failure the sweep can suffer on a
  # message is a failed S3 write, which is not the message's fault — a maxReceiveCount would
  # move perfectly good events onto a second queue that nothing reads. FR-005 makes every
  # message routable (an unparseable body goes to logs/_unrouted/) and therefore deletable, so
  # there is no poison message for a DLQ to isolate.
}
