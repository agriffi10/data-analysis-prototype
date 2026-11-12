# One function that is the single writer of a FIFO queue: the queue and its own DLQ, the
# function's role, the function, and the event-source mapping that feeds it one message at a time.
# README.md.

resource "aws_sqs_queue" "requests_dlq" {
  name                        = var.dlq_name
  fifo_queue                  = true
  content_based_deduplication = true
  message_retention_seconds   = 1209600
  sqs_managed_sse_enabled     = true
}

resource "aws_sqs_queue" "requests" {
  name                        = var.queue_name
  fifo_queue                  = true
  content_based_deduplication = var.content_based_deduplication
  deduplication_scope         = var.deduplication_scope
  visibility_timeout_seconds  = 60
  sqs_managed_sse_enabled     = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.requests_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_iam_role" "this" {
  name               = var.role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "this" {
  name   = "writer"
  role   = aws_iam_role.this.id
  policy = var.role_policy
}

module "function" {
  source = "../docker-lambda"

  function_name        = var.function_name
  role_arn             = aws_iam_role.this.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  command = [var.handler]

  # Under the queue's 60s visibility timeout. Breaking that inequality delivers a message to a
  # second invocation while the first is still writing it.
  timeout_seconds = 30
  memory_mb       = var.memory_mb

  environment = var.environment_variables

  depends_on = [aws_iam_role_policy.this]
}

# Batch size 1 is what makes the single writer true without a lock: each message is its own
# invocation, and the FIFO group orders them.
resource "aws_lambda_event_source_mapping" "this" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = module.function.function_arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.this]
}
