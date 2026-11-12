# The table-builder control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/table-builder/.
#
# MessageGroupId is the TARGET DATABASE, so two creates against the same database are STARTED in
# order and creates in different ones start independently.
# ⚠ NOT SERIALIZED: the Pipe starts the machine FIRE_AND_FORGET, so the runs overlap. A refresh
# holds a per-table lock; a create holds none, so check-table-absent plus CREATE … IF NOT EXISTS
# narrows the duplicate-name race and does not close it. README.md.
#
# Standard, TWO branches over one shared spine. Each Task retries only transient Lambda
# SERVICE errors; a shared Catch routes any failure to the terminal Fail state.
# Standard over Express keeps per-execution history. README.md.

locals {
  # The verb Lambdas, in pipeline order. Keyed by the function SUFFIX, which is also the
  # lambdas/table-builder-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # A NEW ENTRY needs no edit to lambda.tf (for_each) and none to the deploy role, but DOES
  # need a key added in stepfunction.tf, whose templatefile() map is explicit. README.md.
  table_builder_functions = {
    "validate-authorize"    = { handler = "validate_authorize.handler", timeout = 15, memory = 256 }
    "check-table-absent"    = { handler = "check_table_absent.handler", timeout = 15, memory = 256 }
    "load-table-definition" = { handler = "load_table_definition.handler", timeout = 15, memory = 256 }
    # These 15 s timeouts are INPUTS to the machine's TimeoutSeconds derivation and to
    # tbcommon/table_lock.py's MACHINE_TIMEOUT_SECONDS. Raising one without the other is
    # caught by test_table_lock_timeout.py.
    "acquire-refresh-lock" = { handler = "acquire_refresh_lock.handler", timeout = 15, memory = 256 }
    "release-refresh-lock" = { handler = "release_refresh_lock.handler", timeout = 15, memory = 256 }
    "inspect-source"       = { handler = "inspect_source.handler", timeout = 60, memory = 512 }
    "infer-schema"         = { handler = "infer_schema.handler", timeout = 120, memory = 1024 }
    "diff-schema"          = { handler = "diff_schema.handler", timeout = 15, memory = 256 }
    "apply-refresh"        = { handler = "apply_refresh.handler", timeout = 300, memory = 512 }
    "execute-ddl"          = { handler = "execute_ddl.handler", timeout = 300, memory = 512 }
    # The notification of last resort: one decode + one SQS send.
    "notify-failure" = { handler = "tb_notify_failure.handler", timeout = 15, memory = 256 }
  }
}

module "table_builder" {
  source = "./modules/control-plane"

  name         = "table-builder"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.table_builder_functions

  environment_variables = {
    USER_SPACE_BUCKET       = local.user_space_bucket_name
    SHARED_SPACE_BUCKET     = local.shared_space_bucket_name
    ADMIN_BUCKET            = local.athena_admin_bucket_name
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    # Deliberately NOT mirrored by a config._require — see variables.tf.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME         = var.environment
    ATHENA_WORKGROUP = local.athena_workgroup_name
  }

  content_based_deduplication     = true
  dlq_content_based_deduplication = true
  dlq_max_receive_count           = 3

  definition_template = "${path.root}/planes/table-builder/state-machine.asl.json.tftpl"

  ceiling = {
    seconds          = 3600
    notifier_verb    = "notify-failure"
    rule_description = "Notify the actor when a table-builder execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/table-builder/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      log_group_arn = "${local.control_plane_arn_prefix.lambda_logs}-table-builder-*"
    },
  ))
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
