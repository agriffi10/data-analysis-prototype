# ── Notifications-writer role (SPEC-058 FR-002) ──────────────────────────────
# The single privileged role the writer Lambda runs under. It may read+write ANY
# user's notifications.json (the `*` is the per-user prefix segment) and nothing else
# app-relevant: no DeleteObject anywhere (the doc is only ever read-modify-rewritten via
# PutObject — consistent with saved-queries/history), no admin/shared bucket access.
# Plus the SQS receive actions the event-source mapping needs on the request queue, and
# logs. Token verification is offline JWKS, so NO Cognito IAM is required.
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
  })
}

# ── Portal role — notifications enqueue policy (SPEC-058 FR-006) ──────────────
# A small inline policy on the shared portal role (SPEC-011), attached BY NAME like the
# analytics / shared-spaces modules do (the role is created in module.data; the
# module-level depends_on = [module.data] guarantees it exists first). The browser's
# ONLY notifications privilege: sqs:SendMessage to the request queue — for user-action
# messages (markRead/markAllRead). It gets no Lambda invoke, no DLQ, no writer-role
# access, and cannot enqueue a `create` for another user (the writer ignores the body
# username for user actions and derives it from the verified token; `create` is reserved
# for trusted producers granted SendMessage separately — SPEC-061).
resource "aws_iam_role_policy" "portal_notifications" {
  name = "notifications-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-notifications.json.tftpl", {
    request_queue_arn = aws_sqs_queue.requests.arn
  })
}
