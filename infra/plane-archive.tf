# The archive control plane: one call to the control-plane module, and what only this plane
# carries. Its definition, execution policy and reasoning are in planes/archive/.
#
# An ARCHIVE keys on the SHA-256 of "{bucket}/{sourceSpaceRoot}" — a HASH, never the raw path.
# A RESTORE keys on the archive root instead. The API derives that key when it enqueues, so no
# caller chooses it; docs/testing/owed.md §2.2 spells it out for a hand-built request.
#
# ⚠ NEITHER KEY SERIALIZES EXECUTION. The Pipe starts the machine FIRE_AND_FORGET, so a group
# orders the STARTS, and two archives from one space or two restores of one archive can run at
# once. The commit gate is what keeps overlapping archives of DIFFERENT ids safe. Two restores of
# one archive still both run, and still both report — what is no longer at risk is the user's
# data: every restore manifest line is a conditional write, so a copy-back never lands on a file
# that was not there when it started. planes/archive/README.md says what each overlap does.
#
# content_based_deduplication is OFF; the explicit MessageDeduplicationId IS the archive's
# permanent identity, so a resend cannot open a second archive under a second uuid. Past the
# five-minute window it opens a second RUN under the same one, which the queue does not stop —
# and inspect-source claims the id with a create-only write before it writes anything else, so
# the second run refuses before it can reach the first run's archive. That claim, not this queue,
# is what closed this plane's one unrecoverable case.
#
# Its OWN queue and its OWN DLQ, registered with the drain sweep. planes/archive/README.md.
#
# Standard, TWO ARMS off one mode Choice, sharing a machine because a restore is meaningless
# without the archive that produced it.
#
# THE RESTORE'S SPLIT IS AT EXACTLY THE POINT WHERE SECONDS BECOME HOURS and a free check
# becomes a billed, uncancellable retrieval: inspect-archive and check-destination-clear sit
# BEFORE RestoreReady.
#
# THE TOP-LEVEL TimeoutSeconds ARRIVED WITH THE THING THAT MADE IT NECESSARY, and with it the
# EventBridge rule, notify-failure's second door and its raise to 60s — a timeout that cannot
# notify is a failure path satisfied on paper and silent in practice. The deploy-role `events:`
# grant shipped ONE PR AHEAD; the merge apply went red for exactly that ordering. planes/archive/README.md.

locals {
  # The sixteen verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/archive-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # THE STATE COUNT IS NOT THE VERB COUNT: three ASL states point at update-receipt and two at
  # copy-objects and collect-transfer-results. Both reuses are deliberate, and THE ASL SEEDS
  # WHICH STAGE — the verb never infers it from what is lying on the state. The front door
  # serves BOTH modes, because the mode Choice sits downstream of it.
  #
  # Module names are plane-qualified so two planes' identically-named verbs cannot collide on
  # sys.modules under one `pytest lambdas/` process. planes/archive/README.md.
  archive_functions = {
    # One registry read at most — network-bound and small.
    "validate-authorize" = { handler = "archive_validate_authorize.handler", timeout = 15, memory = 256 }
    # Sized by holding the whole copy plan in memory, NOT by the listing.
    # test_the_worst_case_archive_copy_plan_fits_in_the_verbs_memory READS THIS NUMBER and sizes
    # the worst-case plan against it, so LOWERING it fails the build. It does not bound a raise of
    # ARCHIVE_MAX_OBJECTS — the plan sits 5x inside this figure — and what refuses one is the
    # restore arm's timeout guards, from about 24,000 objects up. planes/archive/README.md.
    "inspect-source" = { handler = "archive_inspect_source.handler", timeout = 120, memory = 1024 }
    # The two verbs either side of the Map, handling the same volume in opposite directions.
    # Memory is the CPU dial as much as the headroom, and BOTH ROWS ARE READ BACK by
    # test_the_worst_case_manifest_fits_in_the_verbs_either_side_of_the_map — a test that
    # arrived in REVIEW: until it did, this comment claimed a bound nothing held.
    "build-transfer-manifest"  = { handler = "archive_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "archive_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # 900s is COPY_TIMEOUT_SECONDS, the budget cpcommon/transfer/config.py divides by to size
    # MAX_ITEMS_PER_BATCH, and a test reads THIS row back. No object bytes pass through it.
    "copy-objects" = { handler = "archive_copy_objects.handler", timeout = 900, memory = 1024 }
    # Bounded by ARCHIVE_MAX_OBJECTS the same way delete-source is.
    "rollback" = { handler = "archive_rollback.handler", timeout = 300, memory = 1024 }
    # Holds the same list inspect-source built and is sized for it. Heads every original before
    # deleting, to keep one rewritten since the plan — the guard's work over the same plan, so the
    # guard's 600s; test_delete_source_can_head_every_original_inside_its_timeout READS THIS NUMBER.
    "delete-source" = { handler = "archive_delete_source.handler", timeout = 600, memory = 1024 }
    # One PutObject each, from values already on the state. Neither reads the plan, so
    # neither is sized by the caps.
    "write-manifest" = { handler = "archive_write_manifest.handler", timeout = 30, memory = 256 }
    "write-receipt"  = { handler = "archive_write_receipt.handler", timeout = 30, memory = 256 }
    # The restore arm, sized by the SAME quantity as the archive arm — a restore handles
    # exactly what its archive held.
    #
    # ⚠ THE GUARD'S TIMEOUT IS THE FREE VARIABLE IN RESTORE_HEAD_CONCURRENCY'S ARITHMETIC. The
    # pool CANNOT simply be widened to go faster: boto3 takes botocore's default
    # max_pool_connections of 10, so 8 workers is the ceiling that holds and the TIME is what
    # has to be bought. test_the_guard_can_head_every_destination_inside_its_timeout READS THIS
    # NUMBER, so lowering it — or raising the object cap — fails the build. planes/archive/README.md.
    "inspect-archive"         = { handler = "archive_inspect_archive.handler", timeout = 120, memory = 1024 }
    "check-destination-clear" = { handler = "archive_check_destination_clear.handler", timeout = 600, memory = 1024 }
    # build-transfer-manifest's twin, sized by the same quantity and computed by the same test.
    "build-restore-manifest" = { handler = "archive_build_restore_manifest.handler", timeout = 300, memory = 2048 }
    # Far cheaper than the copy verb beside it — a retrieval request is a small synchronous
    # call and no bytes move. 60s is the room a cold start and a retry storm need, not the work.
    "initiate-restore" = { handler = "archive_initiate_restore.handler", timeout = 60, memory = 512 }
    # THE POLL'S TIMEOUT IS THE GUARD'S ARITHMETIC, RE-USED RATHER THAN RE-DERIVED — it does
    # the same HeadObject work. A sweep that finds every page complete heads the whole cap in
    # ONE invocation, which is the point of sweeping past the page: one page per five-minute
    # Wait would add over an hour after a retrieval had already finished.
    # test_the_poll_can_sweep_the_whole_plan_inside_its_timeout READS THIS NUMBER.
    "poll-restore" = { handler = "archive_poll_restore.handler", timeout = 600, memory = 1024 }
    # The rollback's work exactly, on the same bound, so it takes the rollback's row.
    "delete-archived" = { handler = "archive_delete_archived.handler", timeout = 300, memory = 1024 }
    # One GetObject and one PutObject from values already on the state. Invoked from THREE
    # states, which changes nothing about its sizing.
    "update-receipt" = { handler = "archive_update_receipt.handler", timeout = 30, memory = 256 }
    # The plane's only SUCCESS producer, invoked from THREE states — one per outcome a failure
    # table cannot carry. The smallest verb here.
    "notify" = { handler = "archive_notify.handler", timeout = 30, memory = 256 }
    # 60s, not 15s, because the EventBridge TIMED_OUT door does strictly more work than the
    # ASL one: a DescribeExecution read-back plus a cold-start JWKS fetch and a JWT verify
    # before the send. planes/archive/README.md.
    "notify-failure" = { handler = "ar_notify_failure.handler", timeout = 60, memory = 256 }
  }
}

module "archive" {
  source = "./modules/control-plane"

  name         = "archive"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  account_id   = data.aws_caller_identity.current.account_id

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  functions = local.archive_functions

  environment_variables = {
    ADMIN_BUCKET        = local.athena_admin_bucket_name
    USER_SPACE_BUCKET   = local.user_space_bucket_name
    SHARED_SPACE_BUCKET = local.shared_space_bucket_name
    ARCHIVE_BUCKET      = local.archive_bucket_name
    # Optional in cpcommon.config — unset means emits are logged no-ops.
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

  definition_template = "${path.root}/planes/archive/state-machine.asl.json.tftpl"
  definition_vars = {
    # Mirrored from cpcommon/transfer/config.py, where the two numbers are REASONED about.
    # Terraform cannot import Python, so a test asserts the rendered numbers still equal the
    # constants — two homes for one number is how a batch silently grows past its limit.
    transfer_max_items_per_batch = 8
    transfer_map_max_concurrency = 20
    # Mirrored from arcommon/config.py's RESTORE_POLL_SECONDS; a test holds the two equal. Five
    # minutes against a 3-5 hour retrieval is ~1% of the wait spent asking.
    #
    # THE ITERATION CAP IS DELIBERATELY NOT HERE. RESTORE_MAX_POLLS lives only in Python, because
    # poll-restore computes `exhausted` itself — two homes for that number would only disagree on
    # a restore that was already going badly.
    restore_poll_seconds = 300
  }

  # A TOP-LEVEL ASL field, not a resource argument. Without it a Standard workflow's ceiling
  # is ONE YEAR. IT DOES NOT ON ITS OWN REACH NotifyFailure — the EventBridge TIMED_OUT rule
  # does.
  #
  # ⚠ 43,200 RATHER THAN 10,800, AND THE REASON IS THE STORAGE CLASS RATHER THAN THE DATA. The
  # archive arm's long pole is a copy (~8,100s); THE RESTORE ARM'S IS A WAIT — a GLACIER object
  # is not readable and Standard retrieval takes 3-5 hours, so the old ceiling would have
  # killed a HEALTHY restore before S3 had finished with it. The retrieval budget is
  # deliberately 7 hours, above the tier's own 5, because giving up early makes the user pay
  # for a SECOND billed retrieval.
  #
  # IT IS ONE FIELD ON ONE MACHINE, so the archive arm's backstop rises with it — TimeoutSeconds
  # is top-level ASL and CANNOT differ per branch. Two tests compute every term. planes/archive/README.md.
  ceiling = {
    seconds          = 43200
    notifier_verb    = "notify-failure"
    rule_description = "Notify the actor when an archive execution is stopped by the state machine's own timeout."
  }

  execution_policy = templatefile("${path.root}/planes/archive/execution.json.tftpl", merge(
    local.control_plane_policy_arns,
    {
      log_group_arn          = "${local.control_plane_arn_prefix.lambda_logs}-archive-*"
      archive_bucket_arn     = "arn:aws:s3:::${local.archive_bucket_name}"
      execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-archive-orchestrator:*"
    },
  ))

  distributed_map = {
    manifest_prefix              = "archive"
    can_stop                     = true
    child_execution_arn_wildcard = "${local.control_plane_arn_prefix.executions}-archive-orchestrator:*"
  }
  admin_bucket_arn = local.athena_admin_bucket_arn

  depends_on = [module.base]
}

# Bucket 5, the GLACIER vault. Outside the plane's module because it is not part of the machine,
# and the one place in the stack where a mistake is unrecoverable.
module "archive_vault" {
  source = "./modules/archive-vault"

  archive_bucket_name = local.archive_bucket_name
  deploy_role_arn     = local.deploy_role_arn
  execution_role_arn  = local.archive_execution_role_arn
  account_id          = data.aws_caller_identity.current.account_id

  depends_on = [module.base]
}
