# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Names are what the deploy policy scopes to, and every ARN here is KNOWN AT PLAN TIME.
# This module plans standalone. ../../info/control-plane-shape.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-table-share-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-table-share-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-table-share-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-table-share-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-table-share-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-table-share-sfn-role"

  # The ARN is a constructed string so the LF-admin wiring from root is cycle-free.
  execution_role_name = "${var.project_name}-${var.environment}-table-share-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-share-execution-role"

  # The verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/table-share-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # Module names carry the table_share_ prefix so they cannot collide with the table-builder's
  # identically-named verbs on sys.modules under one `pytest lambdas/` process.
  #
  # A NEW ENTRY still needs a key added in stepfunction.tf, whose map is explicit.
  table_share_functions = {
    "validate-authorize" = { handler = "table_share_validate_authorize.handler", timeout = 15, memory = 256 }
    # Sized above 60s/512MB: this verb holds the whole copy plan in memory before writing it,
    # and at worst-case 1024-byte keys that plan is ~21 MB serialised. README.md.
    "inspect-source"      = { handler = "table_share_inspect_source.handler", timeout = 120, memory = 1024 }
    "check-target-absent" = { handler = "table_share_check_target_absent.handler", timeout = 15, memory = 256 }
    "copy-objects"        = { handler = "table_share_copy_objects.handler", timeout = 900, memory = 1024 }
    "create-table"        = { handler = "table_share_create_table.handler", timeout = 300, memory = 512 }
    # THESE TWO ARE THE BINDING CONSTRAINT ON SHARE_MAX_TRANSFER_ITEMS, handling the same
    # volume in opposite directions — a ~46 MB manifest out, and the Map Run export back.
    # Parsing that at 512 MB is where it would have died first, and the memory is also the
    # CPU dial. README.md.
    "build-transfer-manifest"  = { handler = "table_share_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "table_share_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # 60s rather than 15s, because the EventBridge TIMED_OUT door does strictly more work
    # than the ASL one: a cold-start JWKS fetch and a JWT verify before the send. README.md.
    "notify-failure" = { handler = "ts_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything tscommon/config.py requires belongs in
  # the COMMON env in lambda.tf.
  table_share_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  athena_workgroup_arn    = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  user_pool_arn           = "arn:aws:cognito-idp:${var.aws_region}:${var.account_id}:userpool/${var.user_pool_id}"
  glue_catalog_arn        = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any       = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any          = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"

  table_share_function_names = {
    for suffix, _ in local.table_share_functions :
    suffix => "${var.project_name}-${var.environment}-table-share-${suffix}"
  }

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  table_share_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard statement covers them.
  table_share_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-table-share-*"

  # CI builds, publishes and attaches this. Named here for the deploy-role wildcard's
  # benefit, and referenced for parity only.
  tscommon_layer_name = "${var.project_name}-${var.environment}-table-share-common"

  # THE BATCH EQUALS COPY_CONCURRENCY (8) ON PURPOSE. copy_batch gives one WHOLE object to
  # each worker, so a batch costs ceil(items/workers) rounds of its SLOWEST object — a
  # MAKESPAN, not bytes over a bandwidth. At 10 it was two rounds and 859s against a 900s
  # timeout. cpcommon/transfer/config.py holds the same pair and a test matches them.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # A TOP-LEVEL ASL field, not a resource argument. Without it a Standard workflow's ceiling
  # is ONE YEAR, so a wedged run never ends.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure — catchers do not cover top-level execution
  # failures, so the sender is told by the EventBridge TIMED_OUT rule in stepfunction.tf.
  #
  # The arithmetic is SHARE_MAX_TRANSFER_BYTES, NOT SHARE_MAX_TOTAL_BYTES (the Map moves the
  # source once PER RECIPIENT), and the denominator is a MAKESPAN, not an aggregate
  # bandwidth. Each reading cost a review round. A TEST COMPUTES ALL OF IT. README.md.
  state_machine_timeout_seconds = 10800

  # ⚠ The Distributed Map's OWN permissions belong to the STATE MACHINE role. Granting them
  # to the Lambda execution role renders, applies and unit-tests green, then fails on the
  # first real share with AccessDenied. README.md.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
