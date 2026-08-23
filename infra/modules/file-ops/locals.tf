# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy (the
# modules/base grant) scopes to the same {project}-*-file-ops-* patterns, and so
# cross-resource ARNs referenced inside IAM policy templates are KNOWN AT PLAN TIME
# (constructed strings, not resource attributes) — the architecture.md "unknown ARN in
# list" discipline. This module plans standalone.
#
# THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY: it matches
# "${project_name}-*-file-ops-*", which requires the literal "-file-ops-" infix AND a
# trailing segment. A name built from the PYTHON package instead of the plane —
# "dat-prod-focommon" for the layer — matches nothing, and the failure surfaces as an
# implicit deny in `Deploy Lambdas`, not as a plan error.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-file-ops-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-file-ops-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-file-ops-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-file-ops-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-file-ops-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-file-ops-sfn-role"

  # ONE shared execution role for every verb Lambda, matching every plane. Its permission
  # policy (execution.json.tftpl) grows with the arc: logs, the logs queue, the
  # notifications queue, the registry read that authorizes a shared space, the lock prefix
  # in the admin bucket, and the execution read the timeout door needs.
  #
  # NO execution_role_arn LOCAL HERE. Root constructs its own twin for the user-space
  # bucket-policy allowlist, and a second construction of the same string in this module
  # would be one more place for it to drift from the role that actually exists — with the
  # failure appearing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-file-ops-execution-role"

  # The single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/file-ops-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "file-ops-<suffix>"); value = the handler + the task's real timeout/memory need.
  #
  # TWELVE VERBS. The front door, the lock's two halves, the notification of last resort,
  # the two that decide WHAT and WHETHER, the five that make it happen — the manifest, the
  # Map's batch copier, the attribution, the source deletion and the terminals — and the one
  # that finally tells the user, after the lock is already free.
  #
  # THREE OF THE FIVE HOLD THE PARSED PLAN, and their memory rows are therefore INPUTS TO
  # FILE_OPS_MAX_OBJECTS rather than free choices — test_config_focommon takes the MINIMUM
  # over every plan-holding verb and reads these numbers back out of this file. Adding a
  # sixth plan-holder without adding it to that set would have the cap certify memory it
  # never checked.
  #
  # Every module name is plane-qualified so two planes' identically-named verbs cannot
  # collide on sys.modules under one `pytest lambdas/` process. The qualifier is the FULL
  # name for a verb and the SHORT prefix for notify-failure — file_ops_validate_authorize.py
  # beside fo_notify_failure.py — which is the fleet-wide convention every plane follows.
  file_ops_functions = {
    # Parses the request, verifies the token, authorizes BOTH sides, enforces containment
    # and the protected-location rules, and emits the outcome list. Its work is one
    # registry read plus string work per item — network-bound and small.
    #
    # THE TIMEOUT IS AN INPUT TO THE LOCK BUDGET, not a free choice: the give-up bound is
    # computed from the acquire verb's worst-case state cost, and a test recomputes it from
    # these rows. Raising one without re-deriving fails the build.
    "validate-authorize" = { handler = "file_ops_validate_authorize.handler", timeout = 15, memory = 256 }
    # One conditional PutObject against the admin bucket, plus a read. Sized like the
    # table-builder's identical verb.
    "acquire-lock" = { handler = "file_ops_acquire_lock.handler", timeout = 15, memory = 256 }
    # One conditional PutObject that frees the lock. Reached on every terminal path the
    # graph can walk, so it must not be the reason a completed request reports failure.
    "release-lock" = { handler = "file_ops_release_lock.handler", timeout = 15, memory = 256 }
    # Expands every selected item, derives every destination and writes the plan. Its cost
    # is a HeadObject per selected FILE and a listing page per thousand objects, and it
    # holds the whole plan in memory to serialise it.
    #
    # THE MEMORY AND THE TIMEOUT ARE BOTH INPUTS TO A CAP, not free choices:
    # FILE_OPS_MAX_OBJECTS is the MINIMUM of the plan this memory can hold and the sweep
    # the guard below can do, and a test READS BOTH NUMBERS BACK from this file. Lowering
    # either without lowering the cap fails the build rather than the invocation.
    "inspect-source" = { handler = "file_ops_inspect_source.handler", timeout = 600, memory = 1024 }
    # Heads every derived destination key, eight at a time. Same memory as the expansion
    # because it loads the same plan back, and the two rows move together.
    "check-destinations" = { handler = "file_ops_check_destinations.handler", timeout = 600, memory = 1024 }
    # Writes one JSONL line per object of every cleared item, and refuses an item whose
    # source it may not delete BEFORE anything is copied.
    #
    # THE WORST OF THE THREE PLAN-HOLDERS FOR MEMORY: it holds the parsed plan AND the
    # joined manifest body at once, because cpcommon.transfer.manifest builds the whole
    # payload with "\n".join(...).encode() before the PUT. Both terms are charged in the
    # cap's own test rather than assumed to fit.
    "build-transfer-manifest" = { handler = "file_ops_build_transfer_manifest.handler", timeout = 300, memory = 1024 }
    # The Distributed Map's batch copier. No object bytes pass through it — every copy is
    # server-side — so its memory is the runtime's floor rather than a function of the
    # data. The timeout is cpcommon.transfer.config's COPY_TIMEOUT_SECONDS, which the
    # batch-size bound is computed against; a test holds the two equal.
    "copy-objects" = { handler = "file_ops_copy_objects.handler", timeout = 900, memory = 512 }
    # Reads the Map Run's export, attributes every failed object to its item and decides
    # which items may have their source removed. Holds the parsed plan.
    "collect-transfer-results" = { handler = "file_ops_collect_transfer_results.handler", timeout = 300, memory = 1024 }
    # The only verb that deletes a user's own files. Holds the parsed plan; its cost is a
    # HEAD sweep over every source key plus one DeleteObjects per thousand keys per item.
    #
    # ITS TIMEOUT IS A TERM IN THE MACHINE'S CEILING, not a free choice: the joint budget
    # subtracts what this Task can actually spend, and test_config_focommon reads it back.
    "delete-source" = { handler = "file_ops_delete_source.handler", timeout = 600, memory = 1024 }
    # Turns every gate verdict into a terminal and shapes the summary. String work over a
    # bounded outcome list plus one small read.
    "finalise-outcomes" = { handler = "file_ops_finalise_outcomes.handler", timeout = 60, memory = 256 }
    # The plane's outcome producer: string work over the bounded outcome list plus one SQS
    # send. It reads the STATE and nothing else — reaching for the plan would put it in the
    # set whose min() memory sizes FILE_OPS_MAX_OBJECTS, shrinking a cap that has nothing to
    # do with notifying, and a test derives that set from the source to stop exactly that.
    #
    # Its timeout is a term in the machine's ceiling like every other serial verb's, and
    # test_config_focommon reads it back from here.
    "notify" = { handler = "file_ops_notify.handler", timeout = 60, memory = 256 }
    # The notification of last resort: one decode + one SQS send, reached only on a
    # whole-request failure path.
    #
    # 60s rather than 15s, because of the SECOND door. The EventBridge TIMED_OUT rule
    # (stepfunction.tf) invokes this same function with an event of a different shape, and
    # that path does strictly more work than the ASL one: a DescribeExecution call to read
    # the input back, then a cold-start JWKS fetch and a JWT verify before the send.
    "notify-failure" = { handler = "fo_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything focommon/config.py needs must live in the COMMON env
  # instead — a shared layer's import runs for every verb, so a verb missing any required
  # var crashes at COLD START, where no test and no deploy can see it.
  file_ops_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"

  file_ops_function_names = {
    for suffix, _ in local.file_ops_functions :
    suffix => "${var.project_name}-${var.environment}-file-ops-${suffix}"
  }

  file_ops_function_arns = [
    for suffix, name in local.file_ops_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  file_ops_log_group_names = {
    for suffix, name in local.file_ops_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes logs
  # to the /aws/lambda/{project}-{env}-file-ops-* wildcard rather than a per-verb ARN.
  file_ops_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-file-ops-*"

  # file-ops-common (focommon) Lambda layer — CI builds + publishes it
  # (deploy-lambdas.yml), exactly like every other domain layer: the artifact is CI-owned,
  # and every verb attaches it via update-function-configuration (TF ignores the `layers`
  # attribute). NAMED AFTER THE PLANE, NOT THE PACKAGE, so it matches the deploy-role
  # *-file-ops-* layer wildcard. Referenced here for documentation/parity only.
  focommon_layer_name = "${var.project_name}-${var.environment}-file-ops-common"

  # The lock prefix in the admin bucket. Mirrored from focommon/config.py, which is where
  # it is reasoned about; a test asserts the two agree, because two homes for one prefix is
  # a lock the verbs write and the policy does not permit.
  lock_prefix = "locks/file-ops"

  # The copy-plan prefix in the admin bucket. Mirrored from focommon/config.py, which is
  # where it is reasoned about, and again in the admin bucket's own lifecycle rule; a test
  # holds all three equal. It cannot match `locks/file-ops/` — an S3 lifecycle prefix
  # anchors at the start of the key — which is what keeps an expiry rule off the lock
  # objects, whose absence is what makes a lock "free" rather than lost.
  plan_prefix = "file-ops"

  # The ASL `Wait` between re-acquire attempts, in seconds. Mirrored from
  # focommon/config.py because ASL cannot import Python; a test holds the two equal.
  #
  # THE ATTEMPT CAP IS DELIBERATELY NOT HERE. LOCK_MAX_ATTEMPTS lives only in Python: the
  # interval is an ASL field and has to be here, but the cap is the verb's own decision and
  # a second home for it is a number that can drift. The archive plane's poll loop records
  # the same split for the same reason.
  lock_wait_seconds = 30

  # A TOP-LEVEL ASL field, not a resource argument and not a task field. Without it a
  # Standard workflow's ceiling is Step Functions' own default of ONE YEAR, so a wedged run
  # simply never ends — and this machine can wedge from its first version, because the
  # waiter loop is in it from day one.
  #
  # It does NOT on its own reach NotifyFailure, and that trap is worth stating here because
  # the state sits right there in the machine looking like it would. AWS is explicit that
  # catchers cover Task, Parallel and Map states but NOT top-level execution failures: this
  # timeout terminates the run outright, so no state runs and no Catch fires. The actor is
  # told by the EventBridge TIMED_OUT rule in stepfunction.tf.
  #
  # NO LONGER PROVISIONAL. The transfer and the deletion exist now, so the ceiling is
  # derived rather than borrowed: test_config_focommon computes the JOINT budget — the lock
  # give-up, plus TWO guard sweeps, plus every serial verb timeout above, plus the copy's
  # makespan at FILE_OPS_MAX_TOTAL_BYTES, plus the deletion — and asserts it fits here.
  #
  # THE CAP MOVED, NOT THE CEILING, and that was a decision rather than an accident. At the
  # 3 TiB the byte cap started at, the joint budget came to ~12,700s against this 10,800s.
  # Raising the ceiling instead would have raised STALE_LOCK_SECONDS with it — that
  # threshold must exceed the ceiling or a running execution's lock gets stolen — and a
  # longer stale window on a SHARED space blocks everyone else who works in it, not just
  # the person whose run wedged. So FILE_OPS_MAX_TOTAL_BYTES came down to 2 TiB.
  state_machine_timeout_seconds = 10800

  # The Distributed Map's shape, mirrored from cpcommon/transfer/config.py because ASL
  # cannot import Python; a test asserts the rendered numbers still equal the constants the
  # batch verb is bounded against. Two homes for one number is how a batch silently grows
  # past the limit it was sized for.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # The Map's child executions, which the STATE MACHINE role must be able to start and
  # describe. Not the execution role: it is the state machine that makes those calls, and
  # putting them on the Lambda role renders, applies and unit-tests green before failing at
  # the ItemReader with AccessDenied.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}/*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  # The timeout door reads the input of a run whose EventBridge event omitted it, so it
  # needs to name that run's execution. Scoped to this machine's executions only.
  execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"
}
