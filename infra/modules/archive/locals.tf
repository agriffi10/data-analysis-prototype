# ── Constructed names + ARNs (SPEC-168) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-168 deploy_archive grant) scopes to the same
# {project}-*-archive-* patterns, and so cross-resource ARNs referenced inside IAM
# policy templates are KNOWN AT PLAN TIME (constructed strings, not resource
# attributes) — the architecture.md "unknown ARN in list" discipline. This module
# plans standalone.
#
# THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY, and it has a trap worth
# stating once: that policy matches "${project_name}-*-archive-*", which requires the
# literal "-archive-" infix AND a trailing segment. Every name below satisfies it. A
# name built from the PYTHON package instead of the plane — "dat-prod-arcommon" for
# the layer, say — matches nothing, and the failure surfaces as an implicit deny in
# `Deploy Lambdas`, not as a plan error.
#
# THE BUCKET IS THE ONE EXCEPTION AND IT IS DELIBERATE. "{project}-prod-archive" has
# no trailing segment, so it does NOT match "-archive-*" — it is granted by its own
# exact-name statement in the deploy policy, exactly as the other four buckets are.
# S3 bucket names are globally unique, so it takes a root variable override too.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-archive-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-archive-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-archive-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-archive-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-archive-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-archive-sfn-role"

  # ONE shared execution role for every verb Lambda, matching every plane since
  # SPEC-062 consolidated the per-verb roles away. Its permission policy
  # (execution.json.tftpl) grows with the arc: logs + notifications + the registry read
  # validate-authorize needs (168); the source listing, the Glacier write and the source
  # deletion land with SPEC-169, and the restore reads with SPEC-170/171.
  #
  # NO execution_role_arn LOCAL HERE. Root constructs its own twin for the user-space
  # bucket-policy allowlist (FR-007) and for this bucket's own policy, and a second
  # construction of the same string in this module would be one more place for it to
  # drift from the role that actually exists — with the failure appearing as a runtime
  # AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-archive-execution-role"

  # The single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/archive-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "archive-<suffix>"); value = the handler + the task's real timeout/memory need
  # (a small validator is not a long parallel S3 copy — lambdas.md §4).
  #
  # TWO VERBS AT THIS STAGE: SPEC-168's front door and SPEC-152's notifier of last
  # resort. The expansion, the Glacier transfer, the commit gate and the receipt are
  # SPEC-169's; the restore verbs are SPEC-170/171's.
  #
  # Every module name is plane-qualified so two planes' identically-named verbs cannot
  # collide on sys.modules under one `pytest lambdas/` process. The qualifier is the
  # FULL name for a verb and the SHORT prefix for notify-failure —
  # archive_validate_authorize.py beside ar_notify_failure.py — which is not an
  # inconsistency: it is the fleet-wide convention every plane already follows
  # (fs_/ts_/tb_/dq_/ss_notify_failure).
  archive_functions = {
    # Parses the request, verifies the token, authorizes the source space, checks every
    # selected item is inside it and is not portal-managed, and resolves the archive
    # prefix. Its work is at most one registry read — network-bound and small, so the
    # file-send validator's sizing holds here.
    "validate-authorize" = { handler = "archive_validate_authorize.handler", timeout = 15, memory = 256 }
    # SPEC-152's notification of last resort: one decode + one SQS send, reached only on
    # a whole-request failure path.
    #
    # 15s IS CORRECT ONLY WHILE THIS MACHINE CANNOT WEDGE. File-send's twin runs at 60s
    # because its EventBridge timeout door does a cold-start JWKS fetch and a JWT verify
    # before the send. This machine has no TimeoutSeconds and no second door, because it
    # validates and stops. SPEC-169 adds the Map and the copy, and must raise this WITH
    # the door it adds.
    "notify-failure" = { handler = "ar_notify_failure.handler", timeout = 15, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything cpcommon/config.py _require()s must live in the COMMON
  # env instead — a verb missing any required var crashes on first ACCESS, and for an
  # import-time read that is COLD START, where no test and no deploy can see it (the
  # table-builder production break, PR #196).
  archive_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan).
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"

  archive_function_names = {
    for suffix, _ in local.archive_functions :
    suffix => "${var.project_name}-${var.environment}-archive-${suffix}"
  }

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list.
  archive_function_arns = [
    for suffix, name in local.archive_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  archive_log_group_names = {
    for suffix, name in local.archive_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-archive-* wildcard (one statement covering
  # every function log group) rather than a per-verb ARN.
  archive_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-archive-*"

  # archive-common (arcommon) Lambda layer — CI builds + publishes it
  # (deploy-lambdas.yml), exactly like file-send-common: the layer artifact is CI-owned,
  # and every verb attaches it via update-function-configuration (TF ignores the
  # `layers` attribute). NAMED AFTER THE PLANE, NOT THE PACKAGE, so it matches the
  # deploy-role *-archive-* layer wildcard (modules/base). Referenced here for
  # documentation/parity only.
  arcommon_layer_name = "${var.project_name}-${var.environment}-archive-common"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"

  archive_bucket_arn = "arn:aws:s3:::${var.archive_bucket_name}"
}
