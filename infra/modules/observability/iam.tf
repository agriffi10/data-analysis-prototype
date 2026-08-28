# The producer fragment: sqs:SendMessage on the logs queue and nothing else.
#
# The PORTAL role is granted NOTHING on this queue, here or anywhere — a browser that could
# enqueue could forge log events. Producers are execution roles only. README.md.
data "aws_iam_policy_document" "logs_producer" {
  statement {
    sid       = "SendStructuredLogEvents"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.logs.arn]
  }
}

data "aws_iam_policy_document" "sweep_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sweep" {
  name               = local.sweep_role_name
  assume_role_policy = data.aws_iam_policy_document.sweep_assume.json
}

# The sweep writes logs and reads BACK ONLY WHAT IT WROTE. No s3:DeleteObject, no Glue, no
# Athena, no access to either user-data bucket — and so no user-space bucket-policy allowlist
# entry is needed for this role. Why it reads at all, and what bounds it: README.md.
data "aws_iam_policy_document" "sweep" {
  statement {
    sid    = "DrainLogsQueue"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.logs.arn]
  }

  # Both scoped to logs/* — NOT the bucket root, which also holds fallback-results/,
  # shared-spaces/ and table-share/. Widening this lets the sweep overwrite a user's query
  # results with log lines, or copy them into logs/.
  statement {
    sid       = "AppendLogObjects"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${var.admin_bucket_arn}/${local.logs_prefix}/*"]
  }

  statement {
    sid    = "WriteOwnCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.sweep.arn}:*"]
  }
}

resource "aws_iam_role_policy" "sweep" {
  name   = "sweep"
  role   = aws_iam_role.sweep.id
  policy = data.aws_iam_policy_document.sweep.json
}

# The sweep is also a PRODUCER — it instruments itself, which proves the whole path without
# touching a control plane.
resource "aws_iam_role_policy" "sweep_producer" {
  name   = "logs-producer"
  role   = aws_iam_role.sweep.id
  policy = data.aws_iam_policy_document.logs_producer.json
}
