# The data-quality control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/data-quality/.
#
# MessageGroupId is the SHA-256 HEX DIGEST of the canonical target location, NEVER the raw
# location: SQS caps a group id at 128 characters and S3 keys reach 1024. The other producers
# get away with raw ids only because they group by a bounded catalog identifier.
#
# content_based_deduplication is OFF, and turning it on would be ACTIVELY WRONG: a re-check of
# the same location with the same body is a legitimate re-run the user asked for. planes/data-quality/README.md.
#
# A linear pipeline AROUND AN ATHENA QUERY.
#
# STANDARD (not Express) IS MANDATORY, not a preference: a Standard execution runs for up to a
# year, which is what lets the query poll live in the state machine rather than inside a 900 s
# Lambda. planes/data-quality/README.md.

locals {
  # The nine verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/data-quality-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # ⚠ BOTH timeout AND memory_size are set for EVERY verb. The shared-space verbs set a
  # timeout and never a memory_size, leaving the AWS default of 128 MB — AN UNSET MEMORY TIER
  # IS INVISIBLE IN THE PLAN AND ONLY SHOWS UP AS AN OOM IN PRODUCTION.
  #
  # No verb here streams bulk data; Athena does the heavy work. byte-scan is the only one that
  # touches file bytes, and its budget is bounded PER REQUEST. A per-FILE budget would need
  # ~920 MB/s through one Lambda — it would pass on a three-file fixture and time out live.
  #
  # ⚠ Modules are dq_<verb>.py, NEVER a uniform handler.py: pytest flattens every verb
  # directory into ONE module namespace, so nine handler.py files mean the first import wins
  # and the tests assert against the wrong module — and the image gives the whole fleet ONE
  # task root, where a repeated module name does not collide but silently wins. The `handler`
  # string here is the image's command, so this map and the source file MUST move together.
  # planes/data-quality/README.md.
  data_quality_functions = {
    "validate-authorize"  = { handler = "dq_validate_authorize.handler", timeout = 15, memory = 256 }
    "inspect-source"      = { handler = "dq_inspect_source.handler", timeout = 120, memory = 1024 }
    "create-temp-tables"  = { handler = "dq_create_temp_tables.handler", timeout = 60, memory = 512 }
    "start-profile-query" = { handler = "dq_start_profile_query.handler", timeout = 30, memory = 512 }
    "check-query"         = { handler = "dq_check_query.handler", timeout = 15, memory = 256 }
    "byte-scan"           = { handler = "dq_byte_scan.handler", timeout = 300, memory = 1024 }
    "assemble-report"     = { handler = "dq_assemble_report.handler", timeout = 120, memory = 1024 }
    "drop-temp-tables"    = { handler = "dq_drop_temp_tables.handler", timeout = 60, memory = 512 }
    "notify-failure"      = { handler = "dq_notify_failure.handler", timeout = 15, memory = 256 }
  }
}

module "data_quality" {
  source = "./modules/control-plane"

  name         = "data-quality"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.data_quality_functions

  environment_variables = {
    USER_SPACE_BUCKET       = local.user_space_bucket_name
    SHARED_SPACE_BUCKET     = local.shared_space_bucket_name
    ADMIN_BUCKET            = local.athena_admin_bucket_name
    ATHENA_WORKGROUP        = local.athena_workgroup_name
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    # Optional by construction: a function missing it logs to stdout rather than
    # failing at cold start.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    ENV_NAME       = var.environment
  }

  content_based_deduplication     = false
  dlq_content_based_deduplication = true
  dlq_max_receive_count           = 3

  definition_template = "${path.root}/planes/data-quality/state-machine.asl.json.tftpl"

  execution_policy = templatefile("${path.root}/planes/data-quality/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      log_group_arn = "${local.control_plane_arn_prefix.lambda_logs}-data-quality-*"
      claim_prefix  = "data-quality/claims"
    },
  ))
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
