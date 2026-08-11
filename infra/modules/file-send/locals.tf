# ── Constructed names + ARNs (SPEC-164) ──────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (modules/base, the SPEC-164 PR1 grant) scopes to the same {project}-*-file-send-*
# patterns, and so cross-resource ARNs referenced inside IAM policy templates are
# KNOWN AT PLAN TIME (constructed strings, not resource attributes) — the
# architecture.md "unknown ARN in list" discipline. This module plans standalone.
#
# THE NAME PATTERN IS A CONTRACT WITH THE DEPLOY POLICY, and it has a trap worth
# stating once: that policy matches "${project_name}-*-file-send-*", which requires
# the literal "-file-send-" infix AND a trailing segment. Every name below satisfies
# it. A name built from the PYTHON package instead of the plane — "dat-prod-fscommon"
# for the layer, say — matches nothing, and the failure surfaces as an implicit deny
# in `Deploy Lambdas`, not as a plan error.

locals {
  requests_queue_name = "${var.project_name}-${var.environment}-file-send-requests.fifo"
  dlq_name            = "${var.project_name}-${var.environment}-file-send-requests-dlq.fifo"
  pipe_name           = "${var.project_name}-${var.environment}-file-send-pipe"
  pipe_role_name      = "${var.project_name}-${var.environment}-file-send-pipe-role"
  state_machine_name  = "${var.project_name}-${var.environment}-file-send-orchestrator"
  sfn_role_name       = "${var.project_name}-${var.environment}-file-send-sfn-role"

  # ONE shared execution role for every verb Lambda, matching every plane since
  # SPEC-062 consolidated the per-verb roles away. Its permission policy
  # (execution.json.tftpl) grows with the arc: logs + notifications + the registry
  # read and Cognito check validate-authorize needs (164); the source listing lands
  # with SPEC-165 and the destination writes with SPEC-166.
  #
  # NO execution_role_arn LOCAL HERE. Root constructs its own twin for the user-space
  # bucket-policy allowlist (FR-006), and a second construction of the same string in
  # this module would be one more place for it to drift from the role that actually
  # exists — with the failure appearing as a runtime AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-file-send-execution-role"

  # The single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/file-send-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "file-send-<suffix>"); value = the handler + the task's real timeout/memory need
  # (a small validator is not a long parallel S3 copy — lambdas.md §4).
  #
  # THREE VERBS AT THIS STAGE: SPEC-164's front door plus SPEC-165's source
  # resolution. The per-recipient guard, the Distributed-Map copy and the real
  # terminals are SPEC-166.
  #
  # Every module name is plane-qualified so two planes' identically-named verbs cannot
  # collide on sys.modules under one `pytest lambdas/` process (the tbcommon-package
  # lesson, applied to verb modules). The qualifier is the FULL name for a verb and the
  # SHORT prefix for notify-failure — file_send_validate_authorize.py beside
  # fs_notify_failure.py — which is not an inconsistency: it is the fleet-wide
  # convention every plane already follows (ts_/tb_/dq_/ss_notify_failure).
  file_send_functions = {
    # Parses the request, verifies the token, authorizes the source and annotates
    # recipients. Its work is one registry read plus one Cognito call per recipient —
    # network-bound and small, so the table-share validator's sizing holds here.
    "validate-authorize" = { handler = "file_send_validate_authorize.handler", timeout = 15, memory = 256 }
    # SPEC-165. Expands the selection and holds the whole copy plan in memory before
    # writing it, which is the ONLY thing that sizes this row — not the listing, which
    # pages at 1000 keys and costs 20 round trips at SEND_MAX_OBJECTS.
    #
    # THE MEMORY IS THE CAP'S OTHER HALF, and fscommon/config.py says so from its side:
    # each plan entry carries the absolute source key, the relative key and the owning
    # item name, so at S3's worst-case 1024-byte keys 20,000 objects serialise to ~48 MB
    # with the in-memory list of dicts several times that again.
    # test_the_worst_case_copy_plan_fits_in_the_verbs_memory READS THIS NUMBER and
    # computes the plan against it, so raising SEND_MAX_OBJECTS without raising this
    # fails the build rather than the invocation.
    "inspect-source" = { handler = "file_send_inspect_source.handler", timeout = 120, memory = 1024 }
    # SPEC-152's notification of last resort: one decode + one SQS send, reached only
    # on a whole-request failure path.
    #
    # 15s is sized for exactly that. Table-share's twin runs at 60s because SPEC-161
    # gave it a SECOND door (an EventBridge TIMED_OUT rule) whose path does a
    # cold-start JWKS fetch and a JWT verify before the send. This machine has no
    # TimeoutSeconds and no rule, so this door does strictly less work. SPEC-166 adds
    # the long copy, the timeout and the rule — and must raise this with them.
    "notify-failure" = { handler = "fs_notify_failure.handler", timeout = 15, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything fscommon/config.py _require()s must live in the COMMON
  # env instead — the shared layer's import-time fail-fast runs for every verb, so a
  # verb missing any required var crashes at COLD START, where no test and no deploy
  # can see it (the table-builder production break, PR #196).
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

  # Constructed function ARNs (known at plan time) — fed to the SFN role's
  # InvokeFunction list.
  file_send_function_arns = [
    for suffix, name in local.file_send_function_names :
    "arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${name}"
  ]

  file_send_log_group_names = {
    for suffix, name in local.file_send_function_names :
    suffix => "/aws/lambda/${name}"
  }

  # The shared execution role writes to EVERY verb's log group, so its policy scopes
  # logs to the /aws/lambda/{project}-{env}-file-send-* wildcard (one statement
  # covering every function log group) rather than a per-verb ARN.
  file_send_log_group_wildcard_arn = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}-file-send-*"

  # file-send-common (fscommon) Lambda layer — CI builds + publishes it
  # (deploy-lambdas.yml), exactly like table-share-common: the layer artifact is
  # CI-owned, and every verb attaches it via update-function-configuration (TF
  # ignores the `layers` attribute). NAMED AFTER THE PLANE, NOT THE PACKAGE, so it
  # matches the deploy-role *-file-send-* layer wildcard (modules/base) — see the
  # header note. Referenced here for documentation/parity only.
  fscommon_layer_name = "${var.project_name}-${var.environment}-file-send-common"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
