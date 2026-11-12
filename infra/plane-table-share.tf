# The table-share control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/table-share/.
#
# MessageGroupId is the SOURCE database.table, so repeated shares of one source are STARTED in
# order. ⚠ NOT SERIALIZED: the Pipe starts the machine FIRE_AND_FORGET, so a heavy copy can
# overlap itself, and two same-name shares to one recipient can both pass the guard. planes/table-share/README.md.
#
# content_based_deduplication is OFF here, unlike the table-builder queue: two byte-identical
# share requests a user GENUINELY repeats (a re-share after deleting the copy) must not be
# silently absorbed by a 5-minute window. The explicit MessageDeduplicationId is the guard.
#
# Standard. Each per-recipient Map carries a PER-ITEM Catch, so one recipient's failure never
# aborts its siblings. planes/table-share/README.md.

locals {
  # The verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/table-share-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # Module names carry the table_share_ prefix so they cannot collide with the table-builder's
  # identically-named verbs on sys.modules under one `pytest lambdas/` process.
  #
  # A NEW ENTRY reaches the definition as <verb>_function_arn with no other edit.
  table_share_functions = {
    "validate-authorize" = { handler = "table_share_validate_authorize.handler", timeout = 15, memory = 256 }
    # Sized above 60s/512MB: this verb holds the whole copy plan in memory before writing it,
    # and at worst-case 1024-byte keys that plan is ~21 MB serialised. planes/table-share/README.md.
    "inspect-source"      = { handler = "table_share_inspect_source.handler", timeout = 120, memory = 1024 }
    "check-target-absent" = { handler = "table_share_check_target_absent.handler", timeout = 15, memory = 256 }
    # 900s is COPY_TIMEOUT_SECONDS, the budget cpcommon/transfer/config.py divides by to size
    # MAX_ITEMS_PER_BATCH. This plane has no local guard on it: the holder is
    # test_every_plane_running_the_engine_deploys_the_timeout_it_divides_by in
    # control-plane-common, which derives every plane deploying this verb rather than naming one.
    "copy-objects" = { handler = "table_share_copy_objects.handler", timeout = 900, memory = 1024 }
    "create-table" = { handler = "table_share_create_table.handler", timeout = 300, memory = 512 }
    # THESE TWO ARE THE BINDING CONSTRAINT ON SHARE_MAX_TRANSFER_ITEMS, handling the same
    # volume in opposite directions — a ~46 MB manifest out, and the Map Run export back.
    # Parsing that at 512 MB is where it would have died first, and the memory is also the
    # CPU dial. planes/table-share/README.md.
    "build-transfer-manifest"  = { handler = "table_share_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "table_share_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # 60s rather than 15s, because the EventBridge TIMED_OUT door does strictly more work
    # than the ASL one: a cold-start JWKS fetch and a JWT verify before the send. planes/table-share/README.md.
    "notify-failure" = { handler = "ts_notify_failure.handler", timeout = 60, memory = 256 }
  }
}

module "table_share" {
  source = "./modules/control-plane"

  name         = "table-share"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.table_share_functions

  environment_variables = {
    ADMIN_BUCKET         = local.athena_admin_bucket_name
    USER_SPACE_BUCKET    = local.user_space_bucket_name
    SHARED_SPACE_BUCKET  = local.shared_space_bucket_name
    COGNITO_USER_POOL_ID = module.auth.user_pool_id
    ATHENA_WORKGROUP     = local.athena_workgroup_name
    # Optional in tscommon.config — unset ⇒ emits are logged no-ops.
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    # Deliberately NOT mirrored by a config._require: a verb that loses it must log to stdout and
    # keep working, never crash the plane at cold start.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }

  content_based_deduplication     = false
  dlq_content_based_deduplication = false
  dlq_max_receive_count           = 3

  definition_template = "${path.root}/planes/table-share/state-machine.asl.json.tftpl"
  definition_vars = {
    # THE BATCH EQUALS COPY_CONCURRENCY (8) ON PURPOSE. copy_batch gives one WHOLE object to
    # each worker, so a batch costs ceil(items/workers) rounds of its SLOWEST object — a
    # MAKESPAN, not bytes over a bandwidth. At 10 it was two rounds and 859s against a 900s
    # timeout. cpcommon/transfer/config.py holds the same pair and a test matches them.
    transfer_max_items_per_batch = 8
    transfer_map_max_concurrency = 20
  }

  # A TOP-LEVEL ASL field, not a resource argument. Without it a Standard workflow's ceiling
  # is ONE YEAR, so a wedged run never ends.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure — catchers do not cover top-level execution
  # failures, so the sender is told by the EventBridge TIMED_OUT rule the module creates from this ceiling.
  #
  # The arithmetic is SHARE_MAX_TRANSFER_BYTES, NOT SHARE_MAX_TOTAL_BYTES (the Map moves the
  # source once PER RECIPIENT), and the denominator is a MAKESPAN, not an aggregate
  # bandwidth. Each reading cost a review round. A TEST COMPUTES ALL OF IT. planes/table-share/README.md.
  ceiling = {
    seconds          = 10800
    notifier_verb    = "notify-failure"
    rule_description = "Notify the sender when a table-share execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/table-share/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      log_group_arn = "${local.control_plane_arn_prefix.lambda_logs}-table-share-*"
    },
  ))

  distributed_map = {
    manifest_prefix              = "table-share"
    can_stop                     = false
    child_execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-table-share-orchestrator:*"
  }
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
