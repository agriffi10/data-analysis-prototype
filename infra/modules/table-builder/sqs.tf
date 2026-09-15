# ── Request Queue + DLQ ────────────────────────────────────
# MessageGroupId is the TARGET DATABASE, so two creates against the same database are STARTED in
# order and creates in different ones start independently.
# ⚠ NOT SERIALIZED: the Pipe starts the machine FIRE_AND_FORGET, so the runs overlap. A refresh
# holds a per-table lock; a create holds none, so check-table-absent plus CREATE … IF NOT EXISTS
# narrows the duplicate-name race and does not close it. README.md.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = local.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600 # 14 days — keep failed requests for inspection
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = local.requests_queue_name
  fifo_queue                  = true
  content_based_deduplication = true
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = var.dlq_max_receive_count
  })
}
