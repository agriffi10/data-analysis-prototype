# ── Constructed names + ARNs (SPEC-050; SPEC-062 decomposition) ───────────────
# All resource names are derived from {project_name}-{environment} so the deploy
# policy can scope to the same patterns (modules/base) and so cross-resource ARNs
# referenced inside IAM policy templates are KNOWN AT PLAN TIME (constructed
# strings, not resource attributes) — the architecture.md "unknown ARN" discipline.

locals {
  requests_queue_name    = "${var.project_name}-${var.environment}-shared-space-requests.fifo"
  dlq_name               = "${var.project_name}-${var.environment}-shared-space-requests-dlq.fifo"
  orchestrator_role_name = "${var.project_name}-${var.environment}-shared-space-orchestrator-role"
  pipe_role_name         = "${var.project_name}-${var.environment}-shared-space-pipe-role"
  state_machine_name     = "${var.project_name}-${var.environment}-shared-space-orchestrator"
  pipe_name              = "${var.project_name}-${var.environment}-shared-space-pipe"

  # SPEC-062: the single provisioner monolith is decomposed into a validate-authorize
  # Lambda + five single-task verb Lambdas. Keyed by the function suffix (= the
  # lambdas/ subdir suffix + the deploy-lambdas.yml matrix name); value = the Python
  # handler. The Step Function orchestrates them (validate -> Choice(action) -> verb);
  # all run under the single shared orchestrator role (no per-verb roles — user
  # decision, see SPEC-062 FR-005 note).
  shared_space_functions = {
    "validate"       = "validate.handler"
    "create"         = "create_space.handler"
    "add-members"    = "add_members.handler"
    "remove-members" = "remove_members.handler"
    "leave"          = "leave.handler"
    "delete"         = "delete_space.handler"
  }

  shared_space_function_names = {
    for suffix, handler in local.shared_space_functions :
    suffix => "${var.project_name}-${var.environment}-shared-space-${suffix}"
  }

  # Constructed function ARNs (known at plan time) — fed to the orchestrator policy's
  # InvokeFunction list and the Step Function tasks.
  shared_space_function_arns = [
    for suffix, name in local.shared_space_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  # Shared-code Lambda layer (CI builds + publishes; functions attach via
  # update-function-configuration, so TF ignores the `layers` attribute). Named to
  # match the deploy-role `*-shared-space-*` layer wildcard (modules/base).
  common_layer_name = "${var.project_name}-${var.environment}-shared-space-common"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"

  # Wildcard log-group ARN covering every verb/validator function's group — the
  # orchestrator role is the exec role for all of them.
  lambda_log_groups_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-shared-space-*:*"

  state_machine_arn = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
  sfn_log_group_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"

  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.athena_admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"

  # The shared portal role (SPEC-011, created in module.data) — the LF grant target
  # the create/delete verbs target per shared DB, and the env var passed to the verbs.
  # Constructed from the role name (known at plan; no cross-module resource dependency).
  portal_role_arn = "arn:aws:iam::${var.account_id}:role/${var.portal_role_name}"
}
