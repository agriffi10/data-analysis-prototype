# The file-send control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/file-send/.
#
# MessageGroupId is a SHA-256 HASH of "{bucket}/{sourceSpaceRoot}", NEVER the raw path: SQS
# caps a group id at 128 characters and an S3 key reaches 1024, so the raw form is a length
# failure that only appears for deeply-nested sources.
#
# content_based_deduplication is OFF: two byte-identical sends a user genuinely repeats must
# not be absorbed by a 5-minute window.
#
# ITS OWN QUEUE AND ITS OWN DLQ — the drain sweep it is registered with names the feature by
# the DLQ, so a dead-lettered send must never be reported as a share. planes/file-send/README.md.
#
# Standard, which Express doubly cannot be here: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVED WITH THE THING THAT MADE IT NECESSARY — the transfer
# added the Map, the manifest and the copy, so it added the timeout AND the EventBridge rule
# AND the deploy-role events: grant, because a timeout that cannot notify is a failure path
# satisfied on paper and silent in practice. The arithmetic sits beside the ceiling below. planes/file-send/README.md.

locals {
  # The verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/file-send-<suffix>/ directory and the deploy-lambdas.yml matrix name. Only the copy
  # runs inside the Distributed Map; the guard runs per recipient, the rest once per request.
  #
  # Every module name is plane-qualified so two planes' identically-named verbs cannot collide
  # on sys.modules under one `pytest lambdas/` process.
  file_send_functions = {
    # One registry read plus one Cognito call per recipient — network-bound and small.
    "validate-authorize" = { handler = "file_send_validate_authorize.handler", timeout = 15, memory = 256 }
    # Sized by holding the whole copy plan in memory, NOT by the listing.
    # test_the_worst_case_file_send_copy_plan_fits_in_the_verbs_memory READS THIS NUMBER and sizes
    # the plan against it. It refuses neither a modest raise of SEND_MAX_OBJECTS nor a halving of
    # this row — the plan sits about 4x inside — so re-derive the pair rather than expecting the
    # build to object. planes/file-send/README.md.
    "inspect-source" = { handler = "file_send_inspect_source.handler", timeout = 120, memory = 1024 }
    # ONE delimited listing per recipient, so the cost is bounded by what this SENDER has
    # previously sent to this RECIPIENT, not by the size of the send. A probe per selected item
    # could not answer the question correctly at all — fscommon/inbox.py. planes/file-send/README.md.
    "check-target-absent" = { handler = "file_send_check_target_absent.handler", timeout = 60, memory = 256 }
    # The two verbs either side of the Map, handling the same volume in opposite directions.
    # Memory is the CPU dial as much as the headroom.
    #
    # SEND_MAX_TRANSFER_ITEMS is what bounds the manifest, not the product of the source caps,
    # and test_the_worst_case_manifest_fits_in_the_verbs_memory reads THIS row back against it.
    # The bound has room — it does not fire until this drops below about 768 MB — so it is a
    # floor under a mistake, not a fence around a change. planes/file-send/README.md.
    "build-transfer-manifest"  = { handler = "file_send_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "file_send_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # 900s is COPY_TIMEOUT_SECONDS, the budget cpcommon/transfer/config.py divides by to size
    # MAX_ITEMS_PER_BATCH. test_every_plane_running_the_engine_deploys_the_timeout_it_divides_by
    # READS THIS ROW BACK, and moving it either way fails the build rather than silently
    # invalidating every makespan bound the engine reasons with. That guard derives its four
    # planes from the Terraform rather than naming one: THIS row was held by nothing, and a fifth
    # plane deploying the verb would have arrived unchecked and silent.
    "copy-objects" = { handler = "file_send_copy_objects.handler", timeout = 900, memory = 1024 }
    # The plane's only outcome producer. It must not be the reason a delivered send reports
    # failure.
    "notify" = { handler = "file_send_notify.handler", timeout = 60, memory = 256 }
    # 60s rather than 15s, because the EventBridge TIMED_OUT door does strictly more work than
    # the ASL one: a cold-start JWKS fetch and a JWT verify before the send. planes/file-send/README.md.
    "notify-failure" = { handler = "fs_notify_failure.handler", timeout = 60, memory = 256 }
  }
}

module "file_send" {
  source = "./modules/control-plane"

  name         = "file-send"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.file_send_functions

  environment_variables = {
    ADMIN_BUCKET         = local.athena_admin_bucket_name
    USER_SPACE_BUCKET    = local.user_space_bucket_name
    SHARED_SPACE_BUCKET  = local.shared_space_bucket_name
    COGNITO_USER_POOL_ID = module.auth.user_pool_id
    # Optional in fscommon.config — unset ⇒ emits are logged no-ops.
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

  definition_template = "${path.root}/planes/file-send/state-machine.asl.json.tftpl"
  definition_vars = {
    # Mirrored from cpcommon/transfer/config.py, where the two numbers are REASONED about.
    # Terraform cannot import Python, so a test asserts the rendered numbers still equal the
    # constants — two homes for one number is how a batch silently grows past its limit.
    transfer_max_items_per_batch = 8
    transfer_map_max_concurrency = 20
    # A local rather than an ASL literal BECAUSE THE TRANSFER-CAP TEST READS IT — the guard Map's
    # makespan is one of the terms in the machine's own timeout budget.
    guard_map_max_concurrency = 5
  }

  # A TOP-LEVEL ASL field, not a resource argument. Without it a Standard workflow's ceiling is
  # ONE YEAR, and this is the first version of this machine that CAN wedge.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure — the EventBridge TIMED_OUT rule does.
  #
  # The arithmetic is SEND_MAX_TRANSFER_BYTES (the RECIPIENT PRODUCT), not SEND_MAX_TOTAL_BYTES,
  # and the denominator is a MAKESPAN — 500 MB/s, not the ~4 GB/s multiplying the constants
  # suggests. test_the_whole_file_send_run_fits_the_machines_ceiling SUMS EVERY TERM of the run
  # and reads THIS ceiling and the serial verb timeouts back — the copy and per-child terms come
  # from the Python caps. It has room: raising SEND_MAX_TRANSFER_ITEMS or SEND_MAX_RECIPIENTS does
  # not reach it, and the verb timeouts have to roughly two-and-a-half x. Re-derive it when moving
  # a cap rather than expecting the build to refuse. planes/file-send/README.md.
  ceiling = {
    seconds          = 10800
    notifier_verb    = "notify-failure"
    rule_description = "Notify the sender when a file-send execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/file-send/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-file-send-orchestrator:*"
      log_group_arn          = "${local.control_plane_arn_prefix.lambda_logs}-file-send-*"
    },
  ))

  distributed_map = {
    manifest_prefix              = "file-send"
    can_stop                     = false
    child_execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-file-send-orchestrator:*"
  }
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
