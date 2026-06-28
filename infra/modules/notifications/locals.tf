# ── Constructed names + ARNs (SPEC-058) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base) can scope to the same {project_name}-*-notifications-* patterns and
# so cross-module ARNs referenced inside IAM policy templates are KNOWN AT PLAN TIME
# (constructed strings, not resource attributes) — the architecture.md "unknown ARN"
# discipline. (The notifications queue ARN is a same-module resource attribute, so it
# can be referenced directly in iam.tf — the constructed-string rule is only for
# CROSS-module ARNs feeding lists.)

locals {
  requests_queue_name  = "${var.project_name}-${var.environment}-notifications-requests.fifo"
  dlq_name             = "${var.project_name}-${var.environment}-notifications-requests-dlq.fifo"
  writer_function_name = "${var.project_name}-${var.environment}-notifications-writer"
  writer_role_name     = "${var.project_name}-${var.environment}-notifications-writer-role"

  lambda_log_group_name = "/aws/lambda/${local.writer_function_name}"
  lambda_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.lambda_log_group_name}"

  # Cross-module bucket ARN as a constructed string (the user-space bucket is created
  # in module.data; this module only needs the ARN string to scope the writer policy).
  user_space_bucket_arn = "arn:aws:s3:::${var.user_space_bucket_name}"
}
