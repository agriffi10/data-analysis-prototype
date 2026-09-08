# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Every ARN here is KNOWN AT PLAN TIME and this module plans standalone.
#
# ⚠ THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY: it matches
# "${project_name}-*-file-ops-*", needing the literal "-file-ops-" infix AND a trailing
# segment. A name built from the PYTHON PACKAGE — "dat-prod-focommon" — matches nothing, and
# fails as an implicit deny in `Deploy Lambdas`, not as a plan error. README.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-file-ops-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-file-ops-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-file-ops-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-file-ops-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-file-ops-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-file-ops-sfn-role"

  # NO execution_role_arn LOCAL HERE, deliberately. Root constructs its own twin for the
  # bucket-policy allowlist, and a second construction would be one more place to drift — with
  # the failure appearing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-file-ops-execution-role"

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
  # and so cannot derive themselves. README.md.
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
    # NUMBERS BACK. Lowering either without lowering the cap fails the build. README.md.
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

  # RESERVED FOR OPTIONAL action env ONLY — anything focommon/config.py needs belongs in the
  # COMMON env, or the verb crashes at COLD START where nothing can see it.
  file_ops_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"

  file_ops_function_names = {
    for suffix, _ in local.file_ops_functions :
    suffix => "${var.project_name}-${var.environment}-file-ops-${suffix}"
  }

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  file_ops_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard covers them.
  file_ops_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-file-ops-*"

  # Mirrored from focommon/config.py; a test asserts the two agree, because two homes for one
  # prefix is a lock the verbs write and the policy does not permit.
  lock_prefix = "locks/file-ops"

  # Mirrored from focommon/config.py and again in the admin bucket's lifecycle rule; a test
  # holds all three equal. IT CANNOT MATCH `locks/file-ops/` — an S3 lifecycle prefix anchors
  # at the start of the key, and that is what keeps an expiry rule off the LOCK objects, whose
  # absence is what would make a lock "lost" rather than "free".
  plan_prefix = "file-ops"

  # Mirrored from focommon/config.py because ASL cannot import Python; a test holds the two
  # equal.
  #
  # THE ATTEMPT CAP IS DELIBERATELY NOT HERE. The interval is an ASL field and has to be; the
  # cap is the verb's own decision, and a second home for it is a number that can drift.
  lock_wait_seconds = 30

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
  # window on a SHARED space blocks everyone else. So the byte cap came down. README.md.
  state_machine_timeout_seconds = 10800

  # Mirrored from cpcommon/transfer/config.py; a test asserts the rendered numbers still equal
  # the constants the batch verb is bounded against.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # ⚠ The STATE MACHINE role makes these calls, not the execution role. Putting them on the
  # Lambda role renders, applies and unit-tests green before failing at the ItemReader.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}/*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  # The timeout door reads back the input of a run whose event omitted it. Scoped to this
  # machine's executions only.
  execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"
}
