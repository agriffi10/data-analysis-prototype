# ── Builder execution role ─────────────────────────────────
# It lists one bucket, writes one object, and emits log events. No Cognito (the source is S3,
# deliberately — see build_directory.py's module docstring), no Glue, no Athena, no
# notifications queue: nobody is told when the directory is rebuilt.
#
# **The ListBucket grant is UNCONDITIONED, and what that actually grants is stated here rather
# than minimised.** `Delimiter="/"` is a property of the Lambda's CODE, not of the grant — so
# this role can enumerate every object key under every user's prefix, not merely the top-level
# common prefixes it asks for. That is accepted, for three reasons taken together:
#
#   1. It holds NO s3:GetObject ANYWHERE, so it can list key names and read nothing.
#   2. Key names are metadata, which this repo's field rule already treats as loggable and
#      non-sensitive (cpcommon.observability's module docstring).
#   3. It is a Lambda execution role with no user-assumable path.
#
# Check (1) before adding any grant here — it is the property the other two rest on.
#
# **The obvious tightening — an `s3:prefix` condition scoped to the empty string — is
# REJECTED, not overlooked.** Whether botocore serialises an empty `Prefix` into a condition
# key at all is an AWS implementation detail; if it does not, a `StringEquals` on "" fails
# closed and this role's only listing call breaks. And `simulate-custom-policy` agrees with
# whatever context key the author supplies, so the check would confirm the assumption rather
# than test it. If this grant ever becomes uncomfortable, the sound fix is a separate bucket
# for the directory, not a condition key whose presence cannot be verified.
#
# The role's ARN is NOT exported as a module output. It goes into the user-space bucket
# policy's principal allowlist, and an unknown-at-plan ARN inside a list attribute silently
# drops the change (architecture.md → "unknown ARN inside compact()/a list") — so the root
# module passes a CONSTRUCTED STRING instead, and this module deliberately gives it nothing to
# reach for. See infra/main.tf's user_directory_build_role_arn local.
#
# Trust + permission policies are .tftpl templates rendered with templatefile() (no inline
# jsonencode IAM, per architecture.md Lambda code/infra split).
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
