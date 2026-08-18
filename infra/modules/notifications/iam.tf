# ── Notifications-writer role ──────────────────────────────
# The single privileged role the writer Lambda runs under. It may read+write ANY
# user's notifications.json (the `*` is the per-user prefix segment) and nothing else
# app-relevant: no DeleteObject anywhere (the doc is only ever read-modify-rewritten via
# PutObject — consistent with saved-queries/history), no admin/shared bucket access.
# Plus the SQS receive actions the event-source mapping needs on the request queue, and
# logs. Token verification is offline JWKS, so NO Cognito IAM is required.
#
# It also needs s3:ListBucket conditioned to the notifications-key prefix: a GetObject on
# a key that does NOT yet exist (a brand-new user's first notification) returns 403 (not
# NoSuchKey) unless the caller holds s3:ListBucket on the bucket — so without it the
# read-modify-write can never bootstrap a new user's inbox. The prefix condition keeps the
# grant tight (the writer never lists, it just needs ListBucket present for the 404
# disambiguation), mirroring the portal role's prefix-conditioned user-space ListBucket.
#
# Trust + permission policies are .tftpl templates rendered with templatefile()
# (no inline jsonencode IAM, per architecture.md Lambda code/infra split).
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
# A small inline policy on the shared portal role, attached BY NAME like the
# analytics / shared-spaces modules do (the role is created in module.data; the
# module-level depends_on = [module.data] guarantees it exists first). The browser's
# ONLY notifications privilege: sqs:SendMessage to the request queue — for user-action
# messages (markRead/markAllRead). It gets no Lambda invoke, no DLQ, no writer-role
# access, and cannot enqueue a `create` for another user (the writer ignores the body
# username for user actions and derives it from the verified token; `create` is reserved
# for trusted producers granted SendMessage separately).
resource "aws_iam_role_policy" "portal_notifications" {
  name = "notifications-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-notifications.json.tftpl", {
    request_queue_arn = aws_sqs_queue.requests.arn
  })
}
