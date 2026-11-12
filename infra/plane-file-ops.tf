# The file-ops control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/file-ops/.
#
# MessageGroupId is a SHA-256 HASH of "{bucket}/{sourceSpaceRoot}", NEVER the raw path: SQS
# caps a group id at 128 characters and an S3 key reaches 1024.
#
# ⚠ ORDERED DELIVERY IS NOT SERIALIZED EXECUTION, and here that distinction is the difference
# between working and losing data — a delete removing objects a concurrent move has already
# relocated is silent, unrecoverable loss with versioning off. THE SERIALIZATION IS THE
# PER-SPACE LOCK; this group id buys ordering and throughput isolation and nothing else.
#
# content_based_deduplication is OFF. Its OWN queue and its OWN DLQ, registered with the drain
# sweep, which names the feature by the DLQ — a dead-lettered file operation must never be
# reported as a file send. planes/file-ops/README.md.
#
# Standard, which Express doubly cannot be: a Pipe cannot use REQUEST_RESPONSE against a
# Standard machine, and this plane's outcome is a notification rather than a response.
#
# THE TOP-LEVEL TimeoutSeconds SHIPS FROM THE FIRST VERSION, unlike the planes whose ceiling
# arrived with their transfer — this machine can wedge before it does any data work at all,
# because the waiting loop is in it from day one. The arithmetic sits beside the ceiling below. planes/file-ops/README.md.

locals {
  # The twelve verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/file-ops-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # ⚠ FIVE OF THEM HOLD THE PARSED PLAN, so their memory rows are INPUTS TO
  # FILE_OPS_MAX_OBJECTS rather than free choices — test_config_focommon takes the MINIMUM over
  # every plan-holding verb and reads these numbers back out of this file. ADDING A SIXTH
  # PLAN-HOLDER WITHOUT ADDING IT TO THAT SET would have the cap certify memory it never
  # checked, which is why that guard DERIVES the set from the verb sources and asserts it EQUAL
  # to the one the budget measures: a sixth fails the build rather than the invocation.
  # Every timeout here is read back by a test, but not all as the same kind of term: most are
  # added into the machine's ceiling, acquire-lock's feeds the LOCK GIVE-UP BOUND instead, and
  # copy-objects' is charged through the copy MAKESPAN rather than beside it — adding it there
  # too would bill the same seconds twice. ⚠ ADDING A THIRTEENTH VERB fails that test until the
  # row is charged to one budget or the other, because the ceiling's terms are not one per row
  # and so cannot derive themselves. planes/file-ops/README.md.
  #
  # Module names are plane-qualified so two planes' identically-named verbs cannot collide on
  # sys.modules under one `pytest lambdas/` process.
  file_ops_functions = {
    # THE TIMEOUT IS A TERM IN THE MACHINE'S CEILING, which a test recomputes. It is NOT an
    # input to the lock give-up bound — that is acquire-lock's row, and the two being equal is
    # what would have kept the confusion invisible.
    "validate-authorize" = { handler = "file_ops_validate_authorize.handler", timeout = 15, memory = 256 }
    # One conditional PutObject plus a read. ⚠ THIS TIMEOUT IS THE INPUT TO THE LOCK GIVE-UP
    # BOUND: a waiter's per-attempt cost is the Wait plus this Task's worst case under the retry
    # block, and the bound has to stay under the machine's ceiling. A test reads it back.
    "acquire-lock" = { handler = "file_ops_acquire_lock.handler", timeout = 15, memory = 256 }
    # Reached on every terminal path that TOOK THE LOCK, so it must not be the reason a
    # completed request reports failure. A validate failure refuses before the lock and releases
    # nothing, so at most one release runs — which is why its timeout is charged ONCE as a term
    # in the machine's ceiling rather than once per release state.
    "release-lock" = { handler = "file_ops_release_lock.handler", timeout = 15, memory = 256 }
    # THE MEMORY AND THE TIMEOUT ARE BOTH INPUTS TO A CAP: FILE_OPS_MAX_OBJECTS is the MINIMUM
    # of the plan this memory holds and the sweep the guard can do, and a test READS BOTH
    # NUMBERS BACK. Lowering either without lowering the cap fails the build. planes/file-ops/README.md.
    "inspect-source" = { handler = "file_ops_inspect_source.handler", timeout = 600, memory = 1024 }
    # Same memory as the expansion, because it loads the same plan back. The two rows move
    # together.
    "check-destinations" = { handler = "file_ops_check_destinations.handler", timeout = 600, memory = 1024 }
    # THE WORST OF THE FIVE PLAN-HOLDERS: it holds the parsed plan AND the joined manifest
    # body at once, because the transfer engine joins the whole payload before the PUT. Both
    # terms are charged in the cap's own test rather than assumed to fit.
    "build-transfer-manifest" = { handler = "file_ops_build_transfer_manifest.handler", timeout = 300, memory = 1024 }
    # No object bytes pass through it, so the memory is the runtime's floor. The timeout is
    # COPY_TIMEOUT_SECONDS, which the batch-size bound is computed against; a test holds the
    # two equal.
    "copy-objects" = { handler = "file_ops_copy_objects.handler", timeout = 900, memory = 512 }
    # Holds the parsed plan.
    "collect-transfer-results" = { handler = "file_ops_collect_transfer_results.handler", timeout = 300, memory = 1024 }
    # The only verb that deletes a user's own files, and it holds the parsed plan.
    # ITS TIMEOUT IS A TERM IN THE MACHINE'S CEILING — the joint budget subtracts what this
    # Task can actually spend, and test_config_focommon reads it back.
    "delete-source" = { handler = "file_ops_delete_source.handler", timeout = 600, memory = 1024 }
    # String work over a bounded outcome list plus one small read.
    "finalise-outcomes" = { handler = "file_ops_finalise_outcomes.handler", timeout = 60, memory = 256 }
    # ⚠ IT READS THE STATE AND NOTHING ELSE. Reaching for the plan would put it in the set
    # whose min() memory sizes FILE_OPS_MAX_OBJECTS, shrinking a cap that has nothing to do
    # with notifying — a test derives that set from the source to stop exactly that.
    "notify" = { handler = "file_ops_notify.handler", timeout = 60, memory = 256 }
    # 60s rather than 15s, because the EventBridge TIMED_OUT door does strictly more work than
    # the ASL one: a DescribeExecution to read the input back, then a cold-start JWKS fetch and
    # a JWT verify before the send.
    "notify-failure" = { handler = "fo_notify_failure.handler", timeout = 60, memory = 256 }
  }
}

module "file_ops" {
  source = "./modules/control-plane"

  name         = "file-ops"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.file_ops_functions

  environment_variables = {
    ADMIN_BUCKET        = local.athena_admin_bucket_name
    USER_SPACE_BUCKET   = local.user_space_bucket_name
    SHARED_SPACE_BUCKET = local.shared_space_bucket_name
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

  definition_template = "${path.root}/planes/file-ops/state-machine.asl.json.tftpl"
  definition_vars = {
    # Mirrored from cpcommon/transfer/config.py; a test asserts the rendered numbers still equal
    # the constants the batch verb is bounded against.
    transfer_max_items_per_batch = 8
    transfer_map_max_concurrency = 20
    # Mirrored from focommon/config.py because ASL cannot import Python; a test holds the two
    # equal.
    #
    # THE ATTEMPT CAP IS DELIBERATELY NOT HERE. The interval is an ASL field and has to be; the
    # cap is the verb's own decision, and a second home for it is a number that can drift.
    lock_wait_seconds = 30
  }

  # A TOP-LEVEL ASL field, not a resource argument. IT SHIPS FROM THE FIRST VERSION because
  # the waiting loop is in this machine from day one — a request whose lock is held by
  # something that never finishes would otherwise Wait/re-acquire for a YEAR.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure — the EventBridge TIMED_OUT rule does.
  #
  # test_config_focommon computes the JOINT budget against focommon.config's mirror of THIS
  # number, and holds the two equal in a second test — so the budget does fit what is deployed
  # here, but by two assertions rather than one, and deleting either breaks the chain. It also
  # reads this number directly for the stale-lock threshold. THE CAP MOVED, NOT
  # THE CEILING: raising the ceiling would raise STALE_LOCK_SECONDS with it (that threshold
  # must exceed the ceiling or a running execution's lock gets stolen), and a longer stale
  # window on a SHARED space blocks everyone else. So the byte cap came down. planes/file-ops/README.md.
  ceiling = {
    seconds          = 10800
    notifier_verb    = "notify-failure"
    rule_description = "Notify the actor when a file-operations execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/file-ops/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-file-ops-orchestrator:*"
      log_group_arn          = "${local.control_plane_arn_prefix.lambda_logs}-file-ops-*"
      lock_prefix            = "locks/file-ops"
      plan_prefix            = "file-ops"
    },
  ))

  distributed_map = {
    manifest_prefix              = "file-ops"
    can_stop                     = true
    child_execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-file-ops-orchestrator/*"
  }
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}
