# ── Constructed names + ARNs (SPEC-126) ──────────────────────────────────────
# Names derive from {project_name}-{environment} so the deploy policy (modules/base, the
# SPEC-126 PR1 grant) scopes to the same {project}-*-control-plane-dlq-drain patterns, and
# so ARNs referenced inside IAM policy templates are KNOWN AT PLAN TIME — the
# architecture.md "unknown ARN in list" discipline. This module plans standalone.

locals {
  function_name  = "${var.project_name}-${var.environment}-control-plane-dlq-drain"
  role_name      = "${var.project_name}-${var.environment}-control-plane-dlq-drain"
  log_group_name = "/aws/lambda/${local.function_name}"
  log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.log_group_name}"

  # Event-source mappings keyed by QUEUE NAME rather than by list index, so adding or
  # removing a control plane doesn't renumber (and therefore recreate) the others'
  # mappings. The two input lists are positional partners; the root module builds both.
  dlq_by_name = zipmap(var.dlq_queue_names, var.dlq_arns)
}
