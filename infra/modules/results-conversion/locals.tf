# ── Constructed names + ARNs ──────────────────────────────────────────────────
# Every ARN here is KNOWN AT PLAN TIME and this module plans standalone.
#
# ⚠ THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY: it matches
# "${project_name}-*-results-conversion-*", needing the literal "-results-conversion-" infix AND
# a trailing segment. A name built from the PYTHON PACKAGE — "dat-prod-rccommon" — matches
# nothing, and fails as an implicit deny in `Deploy Lambdas`, not as a plan error.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-results-conversion-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-results-conversion-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-results-conversion-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-results-conversion-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-results-conversion-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-results-conversion-sfn-role"

  # NO execution_role_arn LOCAL HERE, deliberately. Root constructs its own twin where a
  # bucket-policy allowlist needs one, and a second construction would be one more place to
  # drift — with the failure appearing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-results-conversion-execution-role"

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
    # derived rather than chosen. Memory and disk are Lambda's maxima because the Excel path
    # cannot stream — polars materialises the frame and xlsxwriter builds the whole workbook
    # beside it — and both feed the per-format size cap in rccommon.config, which a test
    # recomputes from these three numbers. Edit one here and that test goes red.
    "convert" = {
      handler = "rc_convert.handler", timeout = 600, memory = 10240, ephemeral = 10240
    }
    # One notification. Sized like notify-failure and for the same reason: the cold start of the
    # shared layer dominates, not the send.
    "notify" = { handler = "rc_notify.handler", timeout = 60, memory = 256 }
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything the shared layer needs belongs in the
  # COMMON env, or the verb crashes at COLD START where nothing can see it.
  results_conversion_verb_env = {}

  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"

  # The SHARED portal workgroup, as every Athena-reading plane scopes to it.
  athena_workgroup_arn = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"

  results_conversion_function_names = {
    for suffix, _ in local.results_conversion_functions :
    suffix => "${var.project_name}-${var.environment}-results-conversion-${suffix}"
  }

  # From the module's outputs, never rebuilt from a template: an ARN a policy CONSTRUCTS stays
  # known while the function it names is being replaced, so the policy plans no diff at all —
  # and this list is the SFN role's whole InvokeFunction grant.
  results_conversion_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard covers them.
  results_conversion_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-results-conversion-*"

  # A TOP-LEVEL ASL field. What it must clear is the sum of every Task's timeout times its
  # attempts along the longest path, plus the backoff between attempts, which a test computes
  # from the rows above and the template's own Retry blocks. Convert dominates it and retries
  # ONCE on TransientError alone rather than four times on the four Lambda service errors, for
  # a reason that is about correctness rather than arithmetic: a retry of an invocation that
  # already completed its conditional PutObject meets its own object and reports the user's
  # success as a name conflict.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure — the EventBridge TIMED_OUT rule does.
  state_machine_timeout_seconds = 3600

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
