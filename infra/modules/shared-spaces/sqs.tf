# ── Request Queue + DLQ ────────────────────────────────────
# The control-plane entry point. The browser (SPEC-056+) enqueues a request
# message; an EventBridge Pipe (pipe.tf) drains it into the Step Function.
#
# FIFO with a single, constant MessageGroupId (a producer convention) so
# requests are processed strictly one-at-a-time, in order — the user-required serial
# intake that, together with the create action's atomic conditional PutObject
# (If-None-Match), makes duplicate shared-space names impossible even when
# two users submit the same name at once. The Pipe reads a batch of 1 (pipe.tf).
#
# Duplicate-name safety does NOT depend on SQS content dedup — content-based
# deduplication only collapses byte-identical bodies inside the 5-minute window
# (it usefully absorbs a double-click); the registry conditional-put is the real
# guard. Producers may still set an explicit MessageDeduplicationId to override.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = 3
  })

  depends_on = [time_sleep.wait_for_deploy_policy]
}
