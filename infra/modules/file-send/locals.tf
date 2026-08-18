# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy
# (the modules/base grant) scopes to the same {project}-*-file-send-*
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
  # Every plane uses one role rather than one per verb. Its permission policy
  # (execution.json.tftpl) grows with the arc: logs + notifications + the registry
  # read and Cognito check validate-authorize needs (164); the source listing lands
  # and the destination writes.
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
  # SEVEN VERBS: The front door, the source resolution, and the transfer's
  # guard, manifest, batch copy and attribution. Only the copy runs inside the
  # Distributed Map; the guard runs per recipient in an inline Map, and the other four
  # once per request.
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
    # Expands the selection and holds the whole copy plan in memory before
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
    # The per-recipient conflict guard. ONE delimited listing of the
    # recipient's inbox, paginated — so its cost is bounded by what this SENDER has
    # previously sent to this RECIPIENT, not by the size of the send. Even a sender
    # with 20,000 prior items is 20 round trips; the selection only ever costs a set
    # membership test per item. The obvious alternative, a probe per selected item,
    # would have been 400 round trips per recipient AND could not answer the question
    # correctly (see fscommon/inbox.py on S3's key ordering).
    "check-target-absent" = { handler = "file_send_check_target_absent.handler", timeout = 60, memory = 256 }
    # The two verbs either side of the Distributed Map, handling the same
    # volume in opposite directions: the manifest builder expands the copy plan into
    # one JSONL line per (recipient x object) and serialises it, and the collector
    # parses the Map Run's export, which carries every batch's input back again. Both
    # are JSON work over the transfer-item cap, so memory is the CPU dial as much as
    # the headroom — a 2048 MB function gets ~4x the CPU of a 512 MB one.
    #
    # 2048 MB IS AN ASSERTED NUMBER AT THIS STAGE, AND SAYING SO IS THE HONEST
    # VERSION. It is table-share's shipped sizing for the identical pair of verbs at a
    # 20,000-item cap. This plane has no transfer-item cap yet — the manifest is
    # (recipients x objects), so today's caps permit 50 x 20,000 = 1M items, which this
    # memory does NOT hold. SEND_MAX_TRANSFER_ITEMS carries a test that
    # READS THIS ROW and computes the cap against it, the way
    # test_the_worst_case_copy_plan_fits_in_the_verbs_memory already reads
    # inspect-source's. Until then the bound is prose, which is what the cap is for.
    "build-transfer-manifest"  = { handler = "file_send_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "file_send_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # One BATCH of transfer items per invocation, on cpcommon.transfer's
    # bounded worker pool. 900s is not a preference: it is COPY_TIMEOUT_SECONDS, the
    # budget cpcommon/transfer/config.py divides by to size MAX_ITEMS_PER_BATCH — and
    # test_the_copy_timeout_matches_this_planes_deployed_verb reads THIS row back, so
    # lowering it here fails the build rather than silently invalidating every makespan
    # bound the engine reasons with. (The pre-existing twin in cpcommon reads
    # table-share's locals only; one file, one plane.) No object bytes pass through the
    # function, so the memory buys CPU for the pool's threads and nothing else.
    "copy-objects" = { handler = "file_send_copy_objects.handler", timeout = 900, memory = 1024 }
    # The plane's only outcome producer: at most one registry read plus a
    # handful of SQS sends, bounded by SEND_MAX_RECIPIENTS. Sized like every other
    # notifier on the fleet — the work is network-bound and small, and it must not be
    # the reason a delivered send reports failure.
    "notify" = { handler = "file_send_notify.handler", timeout = 60, memory = 256 }
    # the notification of last resort: one decode + one SQS send, reached only
    # on a whole-request failure path.
    #
    # 60s rather than 15s, because of the second door that made 15s wrong. The
    # EventBridge TIMED_OUT rule (stepfunction.tf) invokes this same function with an
    # event of a different shape, and that path does strictly more work than the ASL
    # one: a cold-start JWKS fetch over the network plus a JWT verify before the send,
    # because the sender has to come from the token in the timed-out execution's own
    # input. 15s was sized for a decode and a send. Table-share's twin and the DLQ
    # drain, which do the same verify, are both at 60s.
    "notify-failure" = { handler = "fs_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything fscommon/config.py _require()s must live in the COMMON
  # env instead — the shared layer's import-time fail-fast runs for every verb, so a
  # verb missing any required var crashes at COLD START, where no test and no deploy
  # can see it.
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

  # Mirrored from cpcommon/transfer/config.py, which is where the two
  # numbers are REASONED about: MAX_ITEMS_PER_BATCH equals COPY_CONCURRENCY so a batch
  # is exactly one round of the worker pool, and MAP_MAX_CONCURRENCY bounds how much of
  # the account's Lambda concurrency one send may take. Terraform cannot import Python,
  # so the ASL carries literals fed from here and a test asserts the rendered numbers
  # still equal the constants — two homes for one number is how a batch silently grows
  # past the limit it was sized against.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # The guard Map's fan-out. Modest on purpose: each item is one delimited listing, and
  # this is the same 5 every other per-recipient Map in the fleet uses. Named as a local
  # rather than written into the ASL because the transfer-cap test reads it — the guard
  # Map's makespan is one of the terms in the machine's own timeout budget.
  guard_map_max_concurrency = 5

  # A TOP-LEVEL ASL field, not a resource argument and not a task field
  # — the same distinction the table-builder's lock settled. Without it a Standard
  # workflow's ceiling is Step Functions' own default of ONE YEAR, so a wedged run
  # simply never ends — and this is the first version of this machine that can wedge,
  # because it is the first with a Map, a manifest and a copy in it.
  #
  # It does NOT on its own reach NotifyFailure, and that trap is worth stating here
  # because the state sits right there in the machine looking like it would. AWS is
  # explicit that catchers cover Task, Parallel and Map states but NOT top-level
  # execution failures: this timeout terminates the run outright, so no state runs and
  # no Catch fires. The sender is told by the EventBridge TIMED_OUT rule in
  # stepfunction.tf, which is the documented remedy and is what actually discharges
  # "it just never came back" guarantee here.
  #
  # 3 hours, and the arithmetic is SEND_MAX_TRANSFER_BYTES (3 TiB) — the RECIPIENT
  # PRODUCT, not SEND_MAX_TOTAL_BYTES. Every manifest item is a full copy, so the Map
  # moves the source once per recipient; sized against the 1 TiB source cap alone this
  # number would be short by a factor of SEND_MAX_RECIPIENTS. The denominator is a
  # MAKESPAN, not an aggregate bandwidth: copy_batch gives one whole object to one
  # worker and copy_one part-copies serially, so the pessimistic rate is
  # transfer_map_max_concurrency x CONSERVATIVE_STREAM_BYTES_PER_SECOND = 500 MB/s, not
  # the ~4 GB/s the same constants suggest if you multiply them all together. Under that
  # rate 3 TiB is ~6,600s; the guard Map, the serial verbs and the per-child overhead of
  # 50,000 items in batches of 8 take the worst run to ~8,900s.
  # test_the_whole_run_fits_the_machines_ceiling COMPUTES every term of that from these
  # locals, so a cap or a verb timeout raised without re-deriving it fails the build.
  #
  # It is deliberately not longer. The timeout is how fast a wedged send becomes a
  # notification, so the margin is bought against the sender's silence, not for free.
  state_machine_timeout_seconds = 10800

  # The Distributed Map's OWN permissions belong to the STATE MACHINE
  # role: it is the state machine that calls StartExecution for each child and that
  # reads the ItemReader object and writes the ResultWriter export. Granting these to
  # the Lambda execution role renders, applies and unit-tests green, then fails on the
  # first real send with AccessDenied at the ItemReader,
  # inherited here rather than rediscovered.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
