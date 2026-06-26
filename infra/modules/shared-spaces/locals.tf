# ── Constructed names + ARNs (SPEC-050) ──────────────────────────────────────
# All resource names are derived from {project_name}-{environment} so the deploy
# policy can scope to the same patterns (modules/base) and so cross-resource ARNs
# referenced inside IAM policy templates are KNOWN AT PLAN TIME (constructed
# strings, not resource attributes) — the architecture.md "unknown ARN" discipline.

locals {
  requests_queue_name       = "${var.project_name}-${var.environment}-shared-space-requests.fifo"
  dlq_name                  = "${var.project_name}-${var.environment}-shared-space-requests-dlq.fifo"
  provisioner_function_name = "${var.project_name}-${var.environment}-shared-space-provisioner"
  orchestrator_role_name    = "${var.project_name}-${var.environment}-shared-space-orchestrator-role"
  pipe_role_name            = "${var.project_name}-${var.environment}-shared-space-pipe-role"
  state_machine_name        = "${var.project_name}-${var.environment}-shared-space-orchestrator"
  pipe_name                 = "${var.project_name}-${var.environment}-shared-space-pipe"

  lambda_log_group_name = "/aws/lambda/${local.provisioner_function_name}"
  sfn_log_group_name    = "/aws/vendedlogs/states/${local.state_machine_name}"

  # Constructed ARNs for the orchestrator permission policy. Known at plan time so
  # the policy renders without a create-order dependency on the resources it names.
  provisioner_function_arn = "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${local.provisioner_function_name}"
  state_machine_arn        = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
  lambda_log_group_arn     = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.lambda_log_group_name}"
  sfn_log_group_arn        = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"

  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.athena_admin_bucket_name}"
}
