# The producer fragment.
#
# sqs:SendMessage on the logs queue ARN and nothing else — no other action, no other queue. This
# spec attaches it to the sweep's OWN role (the sweep instruments itself, which is what makes the
# pipe end-to-end verifiable without instrumenting a control plane); SPEC-128 attaches the same
# document to the data-quality execution role.
#
# The PORTAL role is deliberately granted NOTHING on this queue, here or anywhere. The queue's
# contents are the operational record of what the control planes did, and a browser that could
# enqueue could forge log events attributing arbitrary activity to arbitrary services. Producers
# are execution roles only.
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
# Athena, and no access to the user-space or shared-space buckets.
#
# SPEC-129 REVERSED the "it reads nothing" property this role shipped with (SPEC-127 FR-006),
# and that is a deliberate trade rather than a slip. One object per service per day means
# read-modify-write, because S3 has no append: the sweep must GET the day's object to extend it.
# What bounds the reversal is that s3:GetObject is scoped to the SAME logs/* prefix as the
# write, so the role can read its own output and nothing else in the admin bucket — not
# fallback-results/, not shared-spaces/, not table-share/. It still cannot read a single byte of
# user data anywhere.
#
# The admin bucket is NOT in the user-space bucket-policy allowlist problem space — that
# Deny-all-but-allowlist resource policy is on the USER-SPACE bucket, and this role touches
# neither user-data bucket. Stated explicitly because "a new role got a 403 from the user-space
# bucket policy" has bitten this repo three times (table-builder, table-share, data-quality, all
# fixed in #241). No allowlist entry is needed for this role.
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

  # PutObject to extend a day's object, GetObject to read what is already in it. Both scoped to
  # logs/* — NOT the bucket root, which also holds fallback-results/, shared-spaces/ and
  # table-share/. A sweep that could write anywhere in the admin bucket could overwrite a user's
  # query results with log lines; one that could READ anywhere could copy them into logs/.
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

# FR-004/FR-006: the sweep is also a PRODUCER — it instruments itself through
# cpcommon.observability, which is what proves the whole path without touching a control plane.
resource "aws_iam_role_policy" "sweep_producer" {
  name   = "logs-producer"
  role   = aws_iam_role.sweep.id
  policy = data.aws_iam_policy_document.logs_producer.json
}
