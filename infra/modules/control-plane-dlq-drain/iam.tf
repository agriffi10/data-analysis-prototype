# ── Drain execution role ───────────────────────────────────
# Receive and delete on each drained DLQ, one send, logs. NO access to any REQUEST queue — a drain
# that could enqueue into a control plane would be a way to inject work. README.md.
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
    logs_queue_arn          = var.logs_queue_arn
    lambda_log_group_arn    = local.log_group_arn
  })
}
