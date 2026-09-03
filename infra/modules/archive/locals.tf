# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Every ARN here is KNOWN AT PLAN TIME and this module plans standalone.
#
# ⚠ THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY: it matches
# "${project_name}-*-archive-*", needing the literal "-archive-" infix AND a trailing segment.
# "dat-prod-arcommon" matches nothing, and fails as an implicit deny in `Deploy Lambdas`.
#
# THE BUCKET IS THE ONE EXCEPTION, DELIBERATELY: "{project}-prod-archive" has no trailing
# segment, so it is granted by its own exact-name statement like the other buckets. README.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-archive-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-archive-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-archive-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-archive-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-archive-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-archive-sfn-role"

  # NO execution_role_arn LOCAL HERE, deliberately. Root constructs its own twin for BOTH the
  # user-space bucket-policy allowlist and this bucket's own policy, and a second construction
  # would be one more place to drift — failing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-archive-execution-role"

  # The sixteen verb Lambdas, keyed by the function SUFFIX, which is also the
  # lambdas/archive-<suffix>/ directory and the deploy-lambdas.yml matrix name.
  #
  # THE STATE COUNT IS NOT THE VERB COUNT: three ASL states point at update-receipt and two at
  # copy-objects and collect-transfer-results. Both reuses are deliberate, and THE ASL SEEDS
  # WHICH STAGE — the verb never infers it from what is lying on the state. The front door
  # serves BOTH modes, because the mode Choice sits downstream of it.
  #
  # Module names are plane-qualified so two planes' identically-named verbs cannot collide on
  # sys.modules under one `pytest lambdas/` process. README.md.
  archive_functions = {
    # One registry read at most — network-bound and small.
    "validate-authorize" = { handler = "archive_validate_authorize.handler", timeout = 15, memory = 256 }
    # Sized by holding the whole copy plan in memory, NOT by the listing.
    # test_the_worst_case_copy_plan_fits_in_the_verbs_memory READS THIS NUMBER, so raising
    # ARCHIVE_MAX_OBJECTS without raising it fails the build. README.md.
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
    # Holds the same list inspect-source built and is sized for it.
    "delete-source" = { handler = "archive_delete_source.handler", timeout = 300, memory = 1024 }
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
    # NUMBER, so lowering it — or raising the object cap — fails the build. README.md.
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
    # before the send. README.md.
    "notify-failure" = { handler = "ar_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything cpcommon/config.py requires belongs in
  # the COMMON env, which is how a table-builder release once broke in production.
  archive_verb_env = {}

  # The two space buckets are read, written under `archive/`, and — UNIQUELY ON THIS PLANE —
  # DELETED FROM. The archive bucket is the vault itself.
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  archive_bucket_arn      = "arn:aws:s3:::${var.archive_bucket_name}"

  archive_function_names = {
    for suffix, _ in local.archive_functions :
    suffix => "${var.project_name}-${var.environment}-archive-${suffix}"
  }

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  archive_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard covers them.
  archive_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-archive-*"

  # Mirrored from cpcommon/transfer/config.py, where the two numbers are REASONED about.
  # Terraform cannot import Python, so a test asserts the rendered numbers still equal the
  # constants — two homes for one number is how a batch silently grows past its limit.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

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
  # is top-level ASL and CANNOT differ per branch. Two tests compute every term. README.md.
  state_machine_timeout_seconds = 43200

  # Mirrored from arcommon/config.py's RESTORE_POLL_SECONDS; a test holds the two equal. Five
  # minutes against a 3-5 hour retrieval is ~1% of the wait spent asking.
  #
  # THE ITERATION CAP IS DELIBERATELY NOT HERE. RESTORE_MAX_POLLS lives only in Python, because
  # poll-restore computes `exhausted` itself — two homes for that number would only disagree on
  # a restore that was already going badly.
  restore_poll_seconds = 300

  # ⚠ The Distributed Map's OWN permissions belong to the STATE MACHINE role. Granting them to
  # the Lambda execution role renders, applies and unit-tests green, then fails at the
  # ItemReader. The same wildcard scopes the DescribeExecution the timeout door needs, which IS
  # on the Lambda role because it is the notify-failure LAMBDA that calls it.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
