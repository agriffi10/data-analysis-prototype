# ── Builder execution role ─────────────────────────────────
# Lists one bucket, writes one object, emits log events. No Cognito, no Glue, no Athena, no
# notifications queue.
#
# This role holds NO s3:GetObject ANYWHERE. Check that before adding any grant here — the
# unconditioned ListBucket is accepted only because of it, and the `s3:prefix` tightening that
# looks obvious is rejected rather than overlooked. Reasoning: README.md.
resource "aws_iam_role" "build" {
  name               = local.role_name
  assume_role_policy = templatefile("${path.module}/policies/build-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "build" {
  name = "build"
  role = aws_iam_role.build.id

  policy = templatefile("${path.module}/policies/build-permissions.json.tftpl", {
    user_space_bucket_arn = var.user_space_bucket_arn
    directory_prefix      = local.directory_prefix
    logs_queue_arn        = var.logs_queue_arn
    lambda_log_group_arn  = local.log_group_arn
  })
}
