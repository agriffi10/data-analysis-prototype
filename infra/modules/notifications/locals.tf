# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# Names are what the deploy policy scopes to. The constructed-string rule applies to CROSS-module
# ARNs feeding lists; a same-module resource attribute is referenced directly. README.md.

locals {
  requests_queue_name  = "${var.project_name}-${var.environment}-notifications-requests.fifo"
  dlq_name             = "${var.project_name}-${var.environment}-notifications-requests-dlq.fifo"
  writer_function_name = "${var.project_name}-${var.environment}-notifications-writer"
  writer_role_name     = "${var.project_name}-${var.environment}-notifications-writer-role"

  lambda_log_group_name = "/aws/lambda/${local.writer_function_name}"
  lambda_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.lambda_log_group_name}"

  # Cross-module, so constructed rather than read from module.data.
  user_space_bucket_arn = "arn:aws:s3:::${var.user_space_bucket_name}"
}
