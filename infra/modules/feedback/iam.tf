# ── Feedback-writer role ──────────────────────────────
# May read and write objects under the admin bucket's `feedback/` prefix and nothing else.
#
# NO DeleteObject ANYWHERE — the day's document is only ever read-modify-rewritten, and the
# records are somebody's only copy.
#
# NO s3:ListBucket, and that is a decision rather than an oversight: the writer treats ANY read
# failure as "no object", which makes the following write create-only, so it never needs to be
# told that a key is absent. Adding a list grant here would widen the role for a branch that does
# not exist. README.md.
resource "aws_iam_role" "writer" {
  name               = local.writer_role_name
  assume_role_policy = templatefile("${path.module}/policies/writer-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "writer" {
  name = "writer"
  role = aws_iam_role.writer.id

  policy = templatefile("${path.module}/policies/writer-permissions.json.tftpl", {
    admin_bucket_arn     = local.admin_bucket_arn
    request_queue_arn    = aws_sqs_queue.requests.arn
    lambda_log_group_arn = local.lambda_log_group_arn
    logs_queue_arn       = var.logs_queue_arn
  })
}
