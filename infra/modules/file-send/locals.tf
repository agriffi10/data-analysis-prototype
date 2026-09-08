# ── Constructed names + ARNs ────────────────────────────────────────────────
# Every ARN here is KNOWN AT PLAN TIME and this module plans standalone.
#
# ⚠ THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY: it matches
# "${project_name}-*-file-send-*", which needs the literal "-file-send-" infix AND a trailing
# segment. A name built from the PYTHON PACKAGE instead — "dat-prod-fscommon" — matches
# nothing, and fails as an implicit deny in `Deploy Lambdas`, not as a plan error. README.md.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-file-send-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-file-send-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-file-send-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-file-send-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-file-send-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-file-send-sfn-role"

  # NO execution_role_arn LOCAL HERE, deliberately. Root constructs its own twin for the
  # bucket-policy allowlist, and a second construction would be one more place to drift — with
  # the failure appearing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-file-send-execution-role"

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
    # build to object. README.md.
    "inspect-source" = { handler = "file_send_inspect_source.handler", timeout = 120, memory = 1024 }
    # ONE delimited listing per recipient, so the cost is bounded by what this SENDER has
    # previously sent to this RECIPIENT, not by the size of the send. A probe per selected item
    # could not answer the question correctly at all — fscommon/inbox.py. README.md.
    "check-target-absent" = { handler = "file_send_check_target_absent.handler", timeout = 60, memory = 256 }
    # The two verbs either side of the Map, handling the same volume in opposite directions.
    # Memory is the CPU dial as much as the headroom.
    #
    # SEND_MAX_TRANSFER_ITEMS is what bounds the manifest, not the product of the source caps,
    # and test_the_worst_case_manifest_fits_in_the_verbs_memory reads THIS row back against it.
    # The bound has room — it does not fire until this drops below about 768 MB — so it is a
    # floor under a mistake, not a fence around a change. README.md.
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
    # the ASL one: a cold-start JWKS fetch and a JWT verify before the send. README.md.
    "notify-failure" = { handler = "fs_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # RESERVED FOR OPTIONAL action env ONLY — anything fscommon/config.py requires belongs in the
  # COMMON env in lambda.tf, or the verb crashes at COLD START where nothing can see it.
  file_send_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  user_pool_arn           = "arn:aws:cognito-idp:${var.aws_region}:${var.account_id}:userpool/${var.user_pool_id}"

  file_send_function_names = {
    for suffix, _ in local.file_send_functions :
    suffix => "${var.project_name}-${var.environment}-file-send-${suffix}"
  }

  # From the module's outputs, never rebuilt from a template. The point is not tidiness: an ARN
  # a policy CONSTRUCTS stays known while the function it names is being replaced, so the policy
  # plans no diff at all — and this list is the SFN role's whole InvokeFunction grant.
  file_send_function_arns = [for function in module.functions : function.function_arn]

  # The shared role writes to EVERY verb's log group, so one wildcard statement covers them.
  file_send_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-file-send-*"

  # Mirrored from cpcommon/transfer/config.py, where the two numbers are REASONED about.
  # Terraform cannot import Python, so a test asserts the rendered numbers still equal the
  # constants — two homes for one number is how a batch silently grows past its limit.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # A local rather than an ASL literal BECAUSE THE TRANSFER-CAP TEST READS IT — the guard Map's
  # makespan is one of the terms in the machine's own timeout budget.
  guard_map_max_concurrency = 5

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
  # a cap rather than expecting the build to refuse. README.md.
  state_machine_timeout_seconds = 10800

  # ⚠ The Distributed Map's OWN permissions belong to the STATE MACHINE role, not the Lambda
  # execution role. README.md.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
