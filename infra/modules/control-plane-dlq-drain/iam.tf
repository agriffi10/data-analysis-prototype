# ── Drain execution role (SPEC-126 FR-006) ───────────────────────────────────
# The smallest role in the repo, and deliberately so. The drain reads four queues, sends to
# one, and writes logs. No S3, no Glue, no Athena, no Cognito (token verification is offline
# JWKS), and no access to any REQUEST queue — a drain that could enqueue into a control plane
# would be a way to inject work, and it has no reason to.
#
# The four DLQ ARNs arrive as CONSTRUCTED STRINGS from the root module, not as other modules'
# outputs: known at plan time, no cycle, and IAM never validates that a queue exists. Same
# pattern as the notifications queue ARN every producer already scopes to.
#
# Trust + permission policies are .tftpl templates rendered with templatefile() (no inline
# jsonencode IAM, per architecture.md Lambda code/infra split).
resource "aws_iam_role" "drain" {
  name               = local.role_name
  assume_role_policy = templatefile("${path.module}/policies/drain-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "drain" {
  name = "drain"
  role = aws_iam_role.drain.id

  policy = templatefile("${path.module}/policies/drain-permissions.json.tftpl", {
    dlq_arns                = var.dlq_arns
    notifications_queue_arn = var.notifications_queue_arn
    lambda_log_group_arn    = local.log_group_arn
  })
}
