# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# Names are what the deploy policy scopes to — every one of these has to match a pattern in
# `base/policies/github-actions-deploy-feedback.json.tftpl`, and a test reads this file to hold the
# pair together. The constructed-string rule applies to CROSS-module ARNs feeding lists; a
# same-module resource attribute is referenced directly. README.md.

locals {
  requests_queue_name  = "${var.project_name}-${var.environment}-feedback-requests.fifo"
  dlq_name             = "${var.project_name}-${var.environment}-feedback-requests-dlq.fifo"
  writer_function_name = "${var.project_name}-${var.environment}-feedback-writer"
  writer_role_name     = "${var.project_name}-${var.environment}-feedback-writer-role"

  lambda_log_group_name = "/aws/lambda/${local.writer_function_name}"
  lambda_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.lambda_log_group_name}"

  # Cross-module, so constructed rather than read from module.analytics.
  admin_bucket_arn = "arn:aws:s3:::${var.admin_bucket_name}"
}
