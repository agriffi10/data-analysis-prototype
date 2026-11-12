# The results-conversion control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/results-conversion/.
#
# MessageGroupId is the actor's USERNAME, so one user's conversions are STARTED in order while
# different users start independently. The runs still overlap; pipe.tf says why that is harmless
# here. MessageDeduplicationId is the request id, so a browser
# retry of one submit is one execution — content_based_deduplication is OFF on both queues.
#
# Its OWN queue and its OWN DLQ, registered with the drain sweep, which names the feature by
# the DLQ — a dead-lettered conversion must never be reported as a file operation.
#
# Standard, which Express doubly cannot be: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds SHIPS FROM THE FIRST VERSION with its TIMED_OUT rule below —
# catchers do not cover top-level execution failures, so a ceiling without the rule is a
# silent failure mode rather than a bounded one. The arithmetic is in locals.tf.

locals {
  # The verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/results-conversion-<suffix>/ directory. Module names are plane-qualified so two
  # planes' identically-named verbs cannot collide on sys.modules under one `pytest lambdas/`.
  #
  # Every row here is a term in the machine's ceiling: a test sums timeout × attempts along
  # the path and asserts the ceiling clears it.
  results_conversion_functions = {
    # One registry read and one GetQueryExecution — network-bound and small.
    "validate-authorize" = { handler = "rc_validate_authorize.handler", timeout = 15, memory = 256 }
    # One GetQueryResults for the metadata and one HeadObject. No row is read, so no byte of
    # the result set passes through it and the memory is the runtime's floor.
    "describe-results" = { handler = "rc_describe_results.handler", timeout = 60, memory = 256 }
    # 60s rather than 15s: the EventBridge TIMED_OUT door parses the forwarded record and
    # cold-starts the shared layer before the send.
    "notify-failure" = { handler = "rc_notify_failure.handler", timeout = 60, memory = 256 }
    # THE ONLY FUNCTION IN THIS PLANE THAT READS BYTES, and the only one whose numbers are
    # derived rather than chosen. Both feed the per-format size cap in rccommon.config, which a
    # test recomputes from these three numbers — edit one here and that test goes red.
    #
    # ⚠ 3008 IS THIS ACCOUNT'S MEMORY CEILING, NOT LAMBDA'S. Lambda documents 10240, and
    # CreateFunction refused it: "'MemorySize' value failed to satisfy constraint: Member must
    # have value less than or equal to 3008" — the un-raised quota, which nothing local can see.
    # `tofu validate` passed, the module's range check passed, the plan was green, and the APPLY
    # is what knew. Raising it is an AWS support request; until then Excel is capped at the cell
    # count rccommon.config derives from it, because that path cannot stream and its peak memory
    # is spent per cell rather than per byte of input.
    #
    # Ephemeral asks 2048 of a documented 10240 because no function in this account has ever run
    # above the 512 default, so the larger figure is unproven here too.
    "convert" = {
      handler = "rc_convert.handler", timeout = 600, memory = 3008, ephemeral_storage_mb = 2048
    }
    # One notification. Sized like notify-failure and for the same reason: the cold start of the
    # shared layer dominates, not the send.
    "notify" = { handler = "rc_notify.handler", timeout = 60, memory = 256 }
  }
}

module "results_conversion" {
  source = "./modules/control-plane"

  name         = "results-conversion"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.results_conversion_functions

  environment_variables = {
    ADMIN_BUCKET        = local.athena_admin_bucket_name
    USER_SPACE_BUCKET   = local.user_space_bucket_name
    SHARED_SPACE_BUCKET = local.shared_space_bucket_name
    ATHENA_WORKGROUP    = local.athena_workgroup_name
    # Optional — unset means every emit is a logged no-op.
    NOTIFICATIONS_QUEUE_URL = local.notifications_queue_url
    # Deliberately NOT mirrored by a required-config read, so a verb missing it logs
    # to stdout rather than crashing the plane at cold start.
    LOGS_QUEUE_URL = module.observability.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }

  content_based_deduplication     = false
  dlq_content_based_deduplication = false
  dlq_max_receive_count           = 3

  definition_template = "${path.root}/planes/results-conversion/state-machine.asl.json.tftpl"

  ceiling = {
    seconds          = 3600
    notifier_verb    = "notify-failure"
    rule_description = "Notify the actor when a results-conversion execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/results-conversion/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      log_group_arn = "${local.control_plane_arn_prefix.lambda_logs}-results-conversion-*"
    },
  ))
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
