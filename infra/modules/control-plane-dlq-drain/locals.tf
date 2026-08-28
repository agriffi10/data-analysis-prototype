# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# These names are what the deploy policy scopes to, and the ARNs must be KNOWN AT PLAN TIME.
# This module plans standalone. README.md.

locals {
  function_name  = "${var.project_name}-${var.environment}-control-plane-dlq-drain"
  role_name      = "${var.project_name}-${var.environment}-control-plane-dlq-drain"
  log_group_name = "/aws/lambda/${local.function_name}"
  log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.log_group_name}"
}
