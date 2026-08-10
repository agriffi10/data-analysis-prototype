# ── Constructed names + ARNs (SPEC-088) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-088 PR1 grant) scopes to the same {project}-*-table-share-*
# patterns, and so cross-resource ARNs referenced inside IAM policy templates are
# KNOWN AT PLAN TIME (constructed strings, not resource attributes) — the
# architecture.md "unknown ARN in list" discipline. This module plans standalone.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-table-share-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-table-share-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-table-share-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-table-share-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-table-share-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-table-share-sfn-role"

  # ONE shared execution role for every verb Lambda (user decision, recorded in
  # docs/architecture.md (Control Planes -> Table Share) — mirrors the table-builder's post-SPEC-072
  # consolidated model; per-verb roles are NOT used). Its permission policy
  # (execution.json.tftpl) grows with the arc: logs (088) + registry/Cognito/Glue
  # reads (089) + source-bucket listing (090); the copy/create + LF-admin grants
  # land with SPEC-091/092. ARN is a constructed string (known at plan time) for
  # the later cycle-free LF-admin wiring from root (SPEC-092).
  execution_role_name = "${var.project_name}-${var.environment}-table-share-execution-role"
  execution_role_arn  = "arn:aws:iam::${var.account_id}:role/${var.project_name}-${var.environment}-table-share-execution-role"

  # The single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/table-share-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "table-share-<suffix>"); value = the handler + the task's real timeout/memory
  # need (a small validator ≠ a long parallel S3 copy — lambdas.md §4).
  # validate-authorize / inspect-source / build-transfer-manifest /
  # collect-transfer-results run once per request; check-target-absent and
  # create-table run per recipient in the guard and finish Maps; copy-objects runs
  # once per BATCH inside the Distributed Map (stepfunction.tf, SPEC-160).
  # Module names carry the table_share_ prefix so they can't collide with the
  # table-builder's identically-named verbs on sys.modules under one
  # `pytest lambdas/` process (the tbcommon-package lesson, applied to verb modules).
  table_share_functions = {
    "validate-authorize"  = { handler = "table_share_validate_authorize.handler", timeout = 15, memory = 256 }
    "inspect-source"      = { handler = "table_share_inspect_source.handler", timeout = 60, memory = 512 }
    "check-target-absent" = { handler = "table_share_check_target_absent.handler", timeout = 15, memory = 256 }
    "copy-objects"        = { handler = "table_share_copy_objects.handler", timeout = 900, memory = 1024 }
    "create-table"        = { handler = "table_share_create_table.handler", timeout = 300, memory = 512 }
    # SPEC-160. The two verbs either side of the Distributed Map. build-transfer-manifest reads
    # the copy plan and writes one JSONL line per (recipient x object) — S3-bound work whose
    # memory is about holding the expanded list, not about parallelism.
    # collect-transfer-results reads the Map Run's export.
    #
    # SPEC-161 raised both from 60s/512MB, because these two ARE the binding constraint on
    # SHARE_MAX_TRANSFER_ITEMS and the cap moved 1,000 -> 20,000. They handle the same volume in
    # opposite directions: at S3's worst-case 1024-byte keys a transfer item is ~2.3 KB, so
    # 20,000 items is a ~46 MB manifest to build and serialise, and the Map Run export carries
    # every batch's input back again. Parsing that at 512 MB is where it would have died first.
    # The memory is also the CPU dial — a 2048 MB function gets ~4x the CPU of a 512 MB one, and
    # this is JSON work, so it buys the timeout as much as the headroom.
    "build-transfer-manifest"  = { handler = "table_share_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "table_share_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # SPEC-152. The notification of last resort: one decode + one SQS send, reached only
    # on a whole-request failure path.
    #
    # SPEC-161 raised it 15s -> 60s. It gained a SECOND door (the EventBridge TIMED_OUT rule
    # in stepfunction.tf), and that path does strictly more work than the ASL one: a cold-start
    # JWKS fetch over the network plus a JWT verify before the send, because the sender has to
    # come from the token in the timed-out execution's own input. 15s was sized for a decode
    # and a send. The DLQ drain, which does the same verify, is at 60s for the same reason.
    "notify-failure" = { handler = "ts_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR
  # OPTIONAL action env only: everything tscommon/config.py _require()s must live
  # in the COMMON env instead — the shared layer's import-time fail-fast runs for
  # every verb, so a verb missing any required var crashes at cold start (the
  # table-builder production break, PR #196).
  table_share_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  athena_workgroup_arn    = "arn:aws:athena:${var.aws_region}:${var.account_id}:workgroup/${var.athena_workgroup}"
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  user_pool_arn           = "arn:aws:cognito-idp:${var.aws_region}:${var.account_id}:userpool/${var.user_pool_id}"
  glue_catalog_arn        = "arn:aws:glue:${var.aws_region}:${var.account_id}:catalog"
  glue_database_any       = "arn:aws:glue:${var.aws_region}:${var.account_id}:database/*"
  glue_table_any          = "arn:aws:glue:${var.aws_region}:${var.account_id}:table/*/*"

  table_share_function_names = {
    for suffix, _ in local.table_share_functions :
    suffix => "${var.project_name}-${var.environment}-table-share-${suffix}"
  }

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list and the Step Function tasks.
  table_share_function_arns = [
    for suffix, name in local.table_share_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  table_share_log_group_names = {
    for suffix, name in local.table_share_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-table-share-* wildcard (one statement
  # covering every function log group) rather than a per-verb ARN.
  table_share_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-table-share-*"

  # table-share-common (tscommon) Lambda layer — CI builds + publishes it
  # (deploy-lambdas.yml), exactly like table-builder-common: the layer artifact is
  # CI-owned, and every verb attaches it via update-function-configuration (TF
  # ignores the `layers` attribute). Named to match the deploy-role *-table-share-*
  # layer wildcard (modules/base). Referenced here for documentation/parity only.
  tscommon_layer_name = "${var.project_name}-${var.environment}-table-share-common"

  # SPEC-160 FR-002. The Distributed Map's two sizing numbers. Terraform cannot import Python,
  # so these are literals fed into the ASL — and cpcommon/transfer/config.py holds the same two
  # for the batch verb. A test asserts the pair still match, because two homes for one number is
  # how a batch quietly grows past the 256 KB child-input limit it was sized against.
  transfer_max_items_per_batch = 10
  transfer_map_max_concurrency = 20

  # SPEC-161 FR-003. A TOP-LEVEL ASL field, not a resource argument and not a task field —
  # the same distinction SPEC-157 settled for the table-builder. Without it a Standard
  # workflow's ceiling is Step Functions' own default of ONE YEAR, so a wedged run simply
  # never ends.
  #
  # It does NOT on its own reach NotifyFailure, and that trap is worth stating here because
  # the state sits right there in the machine looking like it would. AWS is explicit that
  # catchers cover Task, Parallel and Map states but NOT top-level execution failures: this
  # timeout terminates the run outright, so no state runs and no Catch fires. The sender is
  # told by the EventBridge TIMED_OUT rule in stepfunction.tf, which is the documented remedy
  # and is what actually discharges SPEC-152's "it just never came back" guarantee here.
  #
  # 3 hours, and the arithmetic is the FR-001 caps: at SHARE_MAX_TOTAL_BYTES = 1 TiB the copy
  # runs 160 concurrent server-side streams (transfer_map_max_concurrency x COPY_CONCURRENCY),
  # which is ~6 minutes at 20 MB/s per stream and ~22 at a pessimistic 5 MB/s. 10,800s is
  # roughly 8x that pessimistic worst case, with the guard and finish Maps' Athena creates
  # (bounded by SHARE_MAX_RECIPIENTS x create-table's 300s) far inside the remainder.
  #
  # It is deliberately not longer. The timeout is how fast a wedged share becomes a
  # notification, so the margin is bought against the sender's silence, not for free.
  state_machine_timeout_seconds = 10800

  # SPEC-160 FR-006. The Distributed Map's OWN permissions belong to the STATE MACHINE role: it
  # is the state machine that calls StartExecution for each child and that reads the ItemReader
  # object and writes the ResultWriter export. Granting these to the Lambda execution role
  # renders, applies and unit-tests green, then fails on the first real share with AccessDenied.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
