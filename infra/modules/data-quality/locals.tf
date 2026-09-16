# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Names are what the deploy policy scopes to, and every ARN here is KNOWN AT PLAN TIME.
# This module plans standalone. ../../info/control-plane-shape.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-data-quality-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-data-quality-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-data-quality-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-data-quality-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-data-quality-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-data-quality-sfn-role"

  # A constructed string so it can join the analytics LF admins list without a cycle.
  execution_role_name = "${var.project_name}-${var.environment}-data-quality-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-data-quality-execution-role"

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
  # README.md.
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

  data_quality_function_names = {
    for suffix, _ in local.data_quality_functions :
    suffix => "${var.project_name}-${var.environment}-data-quality-${suffix}"
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything cpcommon/config.py requires belongs in
  # the COMMON env in lambda.tf.
  data_quality_verb_env = {}

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  data_quality_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard statement covers them.
  data_quality_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-data-quality-*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  # Bucket ARNs for the execution role's S3 statements.
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"

  # Where a request id is claimed for the one execution allowed to use it. Mirrors
  # dqcommon.config.CLAIM_PREFIX, and a test holds the two equal. No admin-bucket lifecycle rule
  # may reach it: an expired claim hands its id to the next execution that sends it.
  claim_prefix = "data-quality/claims"

  # The SHARED portal workgroup. A dedicated one fails Lake Formation's Create/Describe checks
  # because Athena ties LF to the workgroup — proved by a live run. README.md.
  athena_workgroup_arn = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"

  # WILDCARD database and table ON PURPOSE: the temp table lands in the actor's own database
  # or the shared space's, known only at request time and not enumerable in static Terraform.
  glue_catalog_arn  = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any    = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"
}
