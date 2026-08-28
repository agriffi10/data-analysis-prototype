# ── Notifications-writer role ──────────────────────────────
# May read+write ANY user's notifications.json and nothing else app-relevant. NO DeleteObject
# anywhere — the document is only ever read-modify-rewritten.
#
# The s3:ListBucket is NOT dead weight: a GetObject on a key that does not yet exist returns
# 403, not NoSuchKey, without it — so a new user's first notification could never bootstrap.
# README.md.
resource "aws_iam_role" "writer" {
  name               = local.writer_role_name
  assume_role_policy = templatefile("${path.module}/policies/writer-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "writer" {
  name = "writer"
  role = aws_iam_role.writer.id

  policy = templatefile("${path.module}/policies/writer-permissions.json.tftpl", {
    user_space_bucket_arn = local.user_space_bucket_arn
    request_queue_arn     = aws_sqs_queue.requests.arn
    lambda_log_group_arn  = local.lambda_log_group_arn
    logs_queue_arn        = var.logs_queue_arn
  })
}

# ── Portal role — notifications enqueue policy ──────────────
# Attached BY NAME (the role is created in module.data). The browser's ONLY notifications
# privilege: sqs:SendMessage. No Lambda invoke, no DLQ, no writer-role access.
#
# THE GRANT IS UNCONDITIONED AND CANNOT BE OTHERWISE — no SQS condition key reaches a message
# body. The `create` boundary is enforced at RUNTIME by the writer, against SenderId.
# README.md.
resource "aws_iam_role_policy" "portal_notifications" {
  name = "notifications-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-notifications.json.tftpl", {
    request_queue_arn = aws_sqs_queue.requests.arn
  })
}
