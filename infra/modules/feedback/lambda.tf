# ── Feedback-writer Lambda and its trigger ───────────────────────────
# The single writer of each day's feedback document. Triggered directly by the queue.
# Terraform owns the function INFRASTRUCTURE + a placeholder zip; CI owns the code. README.md.

data "archive_file" "writer_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/feedback-writer-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('feedback-writer Lambda code not yet deployed by CI')\n"
    filename = "feedback_writer.py"
  }
}

# Explicit so retention is managed (Lambda would otherwise default to infinite).
resource "aws_cloudwatch_log_group" "writer" {
  name              = local.lambda_log_group_name
  retention_in_days = 14
}

resource "aws_lambda_function" "writer" {
  function_name = local.writer_function_name
  role          = aws_iam_role.writer.arn
  runtime       = "python3.12"
  handler       = "feedback_writer.handler"

  # One append, not a drain loop — so 30s, matching notifications rather than log-sweep's 300.
  # It stays under the queue's 60s visibility timeout, and breaking that inequality writes a
  # submission twice.
  timeout = 30

  # 512, NOT the 128 default, and this is the one place feedback must NOT copy notifications.
  # That writer's document is capped (NOTIFICATIONS_MAX, MAX_PAYLOAD_BYTES); this one's grows
  # all day with no cap, because the spec declines a per-user quota. The right analogue is
  # log-sweep, the fleet's other unbounded read-modify-write over a day object, which is 512 for
  # exactly this reason: the whole object is read back, parsed, re-serialised and encoded before
  # the PUT, so peak resident is several times the object's own size.
  #
  # An OOM here is worse than an ordinary failure and that is why it is sized rather than
  # watched: SIGKILL skips observability's flush, so the ONE durable operator signal is absent
  # for precisely this failure, and every later submission that day fails the same way into a
  # DLQ nobody drains. A test computes the entry ceiling this budget buys; the writer's own
  # size warning, which makes the growth visible long before it is fatal, arrives with its code.
  memory_size = 512

  environment {
    variables = {
      # The one variable the writer requires. The rest of `cpcommon.config`'s required union is
      # deliberately absent, as it is on notifications-writer: this function imports `cas`,
      # `clients` and `observability`, none of which reads the config module. A probe imports it
      # under exactly this environment — see `test_layer_import_safety.py`'s singleton set, which
      # feedback-writer joins with the code it probes.
      ADMIN_BUCKET = var.admin_bucket_name
      # Optional BY CONSTRUCTION — observability reads it with os.environ.get, so a writer
      # without it logs to stdout rather than failing at cold start. Passed so it is set in
      # practice.
      LOGS_QUEUE_URL = var.logs_queue_url
      # Same source of truth as the feature-flag document's `environments` keys.
      ENV_NAME = var.environment
    }
  }

  # Bootstrap with the placeholder; CI replaces the code via update-function-code.
  filename         = data.archive_file.writer_placeholder.output_path
  source_code_hash = data.archive_file.writer_placeholder.output_base64sha256

  lifecycle {
    # CI owns the code AND the layer attachment. Without `layers` here, an apply landing after a
    # deploy strips the cpcommon layer back off and the function fails at its next cold start on
    # an import that had been working.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.writer,
    aws_cloudwatch_log_group.writer,
  ]
}

# Batch size 1 so each FIFO message is its own invocation — this is what preserves the
# one-day-at-a-time processing the single-writer model relies on. The handler REFUSES a batch
# rather than absorbing one, so raising this is a change somebody has to make on purpose.
resource "aws_lambda_event_source_mapping" "writer" {
  event_source_arn = aws_sqs_queue.requests.arn
  function_name    = aws_lambda_function.writer.arn
  batch_size       = 1
  enabled          = true

  depends_on = [aws_iam_role_policy.writer]
}
