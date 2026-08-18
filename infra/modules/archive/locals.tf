# ── Constructed names + ARNs ──────────────────────────────────────────────────────────────────────
# All resource names derive from {project_name}-{environment} so the deploy policy in
# modules/base scopes to the same
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

  # ONE shared execution role for every verb Lambda, matching every other plane. Its
  # permission policy (execution.json.tftpl) covers logs, notifications, the registry read
  # the front door needs, the source listing, the Glacier write, the source deletion and
  # the restore's reads.
  #
  # NO execution_role_arn LOCAL HERE. Root constructs its own twin for the user-space
  # bucket-policy allowlist and for this bucket's own policy, and a second
  # construction of the same string in this module would be one more place for it to
  # drift from the role that actually exists — with the failure appearing as a runtime
  # AccessDenied, not a plan error.
  execution_role_name = "${var.project_name}-${var.environment}-archive-execution-role"

  # The single-task verb Lambdas. Keyed by the function SUFFIX (= the
  # lambdas/archive-<suffix>/ subdir AND the deploy-lambdas.yml matrix name
  # "archive-<suffix>"); value = the handler + the task's real timeout/memory need
  # (a small validator is not a long parallel S3 copy — lambdas.md §4).
  #
  # SIXTEEN VERBS: the front door; the expansion, manifest, batch copy, collector,
  # rollback, deletion and two artifacts on the archive side; the archive lookup and
  # destination guard, restore manifest, retrieval, poll, vault sweep and receipt rewrite
  # on the restore side; and the notifier of last resort. TWO of them run inside a Distributed
  # Map — the batch copy and the batch retrieval — and everything else runs once per request.
  # The front door serves BOTH modes: the ASL's mode Choice sits downstream of it, so a second
  # restore-only validator would need the branch to happen before anything had parsed the body.
  #
  # THREE ASL STATES POINT AT update-receipt AND TWO POINT AT copy-objects AND
  # collect-transfer-results, so the state count is not the verb count. Both reuses are
  # deliberate: a restore records its progress on the archive's own receipt at three stages, and
  # the copy-back asks the copy's identical question in the opposite direction.
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
    # Expands the selection and holds the whole copy plan in memory
    # before writing it, which is the ONLY thing that sizes this row — not the listing,
    # which pages at 1000 keys and costs 20 round trips at ARCHIVE_MAX_OBJECTS.
    #
    # THE MEMORY IS THE CAP'S OTHER HALF, and arcommon/config.py says so from its side.
    # test_the_worst_case_copy_plan_fits_in_the_verbs_memory READS THIS NUMBER and
    # computes the plan against it, so raising ARCHIVE_MAX_OBJECTS without raising this
    # fails the build rather than the invocation.
    "inspect-source" = { handler = "archive_inspect_source.handler", timeout = 120, memory = 1024 }
    # The two verbs either side of the Distributed Map, handling
    # the same volume in opposite directions: the manifest builder expands the plan into
    # one JSONL line per object and serialises it, and the collector parses the Map Run's
    # export, which carries every batch's input back again. Both are JSON work over the
    # object cap, so memory is the CPU dial as much as the headroom — a 2048 MB function
    # gets ~4x the CPU of a 512 MB one.
    #
    # BOTH ROWS ARE READ BACK by test_the_worst_case_manifest_fits_in_the_verbs_
    # either_side_of_the_map, which computes the manifest against them. That test
    # arrived in review: until it did, this comment claimed a bound nothing held.
    "build-transfer-manifest"  = { handler = "archive_build_transfer_manifest.handler", timeout = 300, memory = 2048 }
    "collect-transfer-results" = { handler = "archive_collect_transfer_results.handler", timeout = 300, memory = 2048 }
    # One BATCH of transfer items per invocation, on cpcommon.transfer's
    # bounded worker pool. 900s is not a preference: it is COPY_TIMEOUT_SECONDS, the
    # budget cpcommon/transfer/config.py divides by to size MAX_ITEMS_PER_BATCH, and a
    # test reads THIS row back — so lowering it here fails the build rather than silently
    # invalidating every makespan bound the engine reasons with. No object bytes pass
    # through the function, so the memory buys CPU for the pool's threads and nothing else.
    "copy-objects" = { handler = "archive_copy_objects.handler", timeout = 900, memory = 1024 }
    # Lists the archive prefix and deletes what the partial copy left.
    # Bounded by ARCHIVE_MAX_OBJECTS the same way delete-source is: 20 listing pages and
    # 20 DeleteObjects calls, holding the key list in memory once.
    "rollback" = { handler = "archive_rollback.handler", timeout = 300, memory = 1024 }
    # Loads the copy plan and deletes its keys in batches of 1000, so it
    # holds the same list inspect-source built and is sized for it.
    "delete-source" = { handler = "archive_delete_source.handler", timeout = 300, memory = 1024 }
    # The two artifacts: one PutObject each, of a document assembled from
    # values already on the state. Neither reads the plan, so neither is sized by the caps.
    "write-manifest" = { handler = "archive_write_manifest.handler", timeout = 30, memory = 256 }
    "write-receipt"  = { handler = "archive_write_receipt.handler", timeout = 30, memory = 256 }
    # The restore arm, and both rows are sized by the SAME quantity the
    # archive arm's are — ARCHIVE_MAX_OBJECTS — because a restore handles exactly what its
    # archive held.
    #
    # inspect-archive is inspect-source's mirror: it lists (20 pages at the object cap, 20 round
    # trips) and holds the whole restore plan in memory to serialise it. Same memory for the same
    # reason, and the same test computes it.
    #
    # THE GUARD'S TIMEOUT IS THE FREE VARIABLE IN RESTORE_HEAD_CONCURRENCY'S ARITHMETIC, and
    # arcommon/config.py says so from its side. The pool cannot simply be widened to go faster:
    # boto3's S3 client takes botocore's default max_pool_connections of 10, so 8 workers is the
    # ceiling that actually holds and the TIME is what has to be bought. 20,000 destinations, 8 at
    # a time, at a pessimistic 100 ms each is ~250s.
    # test_the_guard_can_head_every_destination_inside_its_timeout READS THIS NUMBER, so lowering
    # it — or raising the object cap — fails the build rather than the invocation. The memory buys
    # CPU for the pool's threads and holds the plan; no object bytes pass through it.
    "inspect-archive"         = { handler = "archive_inspect_archive.handler", timeout = 120, memory = 1024 }
    "check-destination-clear" = { handler = "archive_check_destination_clear.handler", timeout = 600, memory = 1024 }
    # build-restore-manifest is build-transfer-manifest's twin and is sized by
    # the same quantity — the whole manifest expanded and serialised in memory, at the object cap
    # — so it takes the same row, and the SAME test computes it against this number.
    "build-restore-manifest" = { handler = "archive_build_restore_manifest.handler", timeout = 300, memory = 2048 }
    # One BATCH of RestoreObject calls per invocation, on the same bounded pool
    # the destination guard uses. Far cheaper than the copy verb beside it — a retrieval request
    # is a small synchronous call and no bytes move — so it needs neither 900s nor the memory.
    # MAX_ITEMS_PER_BATCH items, 8 at a time, at a pessimistic 200 ms each is under 1s; 60s is
    # the room a cold start and a retry storm need, not the work.
    "initiate-restore" = { handler = "archive_initiate_restore.handler", timeout = 60, memory = 512 }
    # THE POLL'S TIMEOUT IS THE GUARD'S ARITHMETIC, RE-USED RATHER THAN
    # RE-DERIVED, because it does the same work: HeadObject over the plan at
    # RESTORE_HEAD_CONCURRENCY, which botocore's connection pool holds at 8. A sweep that finds
    # every page complete heads ARCHIVE_MAX_OBJECTS (20,000) objects in one invocation — that is
    # the point of sweeping past the page rather than stopping at it, since one page per
    # five-minute Wait would add over an hour after a retrieval had already finished — so its
    # worst case is the guard's ~250s and it gets the guard's 600s.
    # test_the_poll_can_sweep_the_whole_plan_inside_its_timeout READS THIS NUMBER.
    "poll-restore" = { handler = "archive_poll_restore.handler", timeout = 600, memory = 1024 }
    # Lists the archive prefix and deletes what is under it — the rollback's
    # work exactly, on the same bound (20 listing pages and 20 DeleteObjects calls at the object
    # cap, holding the key list in memory once), so it takes the rollback's row.
    "delete-archived" = { handler = "archive_delete_archived.handler", timeout = 300, memory = 1024 }
    # One GetObject and one PutObject of a document assembled from values
    # already on the state, exactly like write-receipt beside it — invoked from THREE states,
    # which changes nothing about its sizing.
    "update-receipt" = { handler = "archive_update_receipt.handler", timeout = 30, memory = 256 }
    # The plane's only SUCCESS producer, invoked from THREE states — one per
    # outcome a failure table cannot carry. One message composed from values already on the
    # state and one SQS send, so it is the smallest verb here; the notify-failure row beside it
    # is larger only because its second door verifies a JWT first, which this one never does.
    "notify" = { handler = "archive_notify.handler", timeout = 30, memory = 256 }
    # The notification of last resort: one decode + one SQS send on the ASL door.
    #
    # 60s, not the 15s a decode and a send would need, because of the second door. The
    # EventBridge TIMED_OUT rule (stepfunction.tf) invokes this same function with an event
    # of a different shape, and that path does strictly more work than the ASL one: a
    # DescribeExecution read-back plus a cold-start JWKS fetch and a JWT verify before the
    # send, because the actor has to come from the token in the timed-out execution's own
    # input. 15s was sized for a decode and a send. File-send's twin and the DLQ drain,
    # which do the same verify, are both at 60s.
    "notify-failure" = { handler = "ar_notify_failure.handler", timeout = 60, memory = 256 }
  }

  # Per-verb extra env, merged over the common env (lambda.tf). RESERVED FOR OPTIONAL
  # action env only: everything cpcommon/config.py _require()s must live in the COMMON
  # env instead — a verb missing any required var crashes on first ACCESS, and for an
  # import-time read that is COLD START, where no test and no deploy can see it — which
  # is how a table-builder release once broke in production.
  archive_verb_env = {}

  # ARNs for the execution role's grants (constructed, known at plan). The three data
  # buckets: the two space buckets are read, written under `archive/` (the receipt) and —
  # uniquely on this plane — DELETED FROM, while the archive bucket is the vault itself.
  admin_bucket_arn        = "arn:aws:s3:::${var.admin_bucket_name}"
  user_space_bucket_arn   = "arn:aws:s3:::${var.user_space_bucket_name}"
  shared_space_bucket_arn = "arn:aws:s3:::${var.shared_space_bucket_name}"
  archive_bucket_arn      = "arn:aws:s3:::${var.archive_bucket_name}"

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

  # Mirrored from cpcommon/transfer/config.py, which is where the two
  # numbers are REASONED about: MAX_ITEMS_PER_BATCH equals COPY_CONCURRENCY so a batch is
  # exactly one round of the worker pool, and MAP_MAX_CONCURRENCY bounds how much of the
  # account's Lambda concurrency one archive may take. Terraform cannot import Python, so
  # the ASL carries literals fed from here and a test asserts the rendered numbers still
  # equal the constants — two homes for one number is how a batch silently grows past the
  # limit it was sized against.
  transfer_max_items_per_batch = 8
  transfer_map_max_concurrency = 20

  # A TOP-LEVEL ASL field, not a resource argument and not a task field
  # — the same distinction the table-builder's lock settled. Without it a Standard
  # workflow's ceiling is Step Functions' own default of ONE YEAR, so a wedged run simply
  # never ends — and this is the first version of this machine that can wedge, because it
  # is the first with a Map and a copy in it.
  #
  # IT DOES NOT ON ITS OWN REACH NotifyFailure. AWS is explicit that catchers cover Task,
  # Parallel and Map states but NOT top-level execution failures: this timeout terminates
  # the run outright, so no state runs and no Catch fires. The actor is told by the
  # EventBridge TIMED_OUT rule in stepfunction.tf, which is the documented remedy and is
  # what stops a wedged run from simply never coming back.
  #
  # 3 hours, and the arithmetic is ARCHIVE_MAX_BYTES over a MAKESPAN rate: copy_batch
  # gives one whole object to one worker and copy_one part-copies serially, so the
  # pessimistic rate is transfer_map_max_concurrency x
  # CONSERVATIVE_STREAM_BYTES_PER_SECOND = 500 MB/s, not the ~4 GB/s the same constants
  # suggest multiplied together. Under that rate 3 TiB is ~6,600s; the per-child overhead
  # of 20,000 items in batches of 8 and the seven serial verbs take the worst run to
  # ~8,100s. test_the_whole_run_fits_the_machines_ceiling COMPUTES every term of that from
  # these locals, so a cap or a verb timeout raised without re-deriving it fails the build.
  #
  # Unlike file-send there is no recipient product to multiply by: an archive has one
  # destination, so the source cap IS the transfer cap.
  #
  # 43,200 RATHER THAN 10,800, AND THE REASON IS THE STORAGE CLASS RATHER THAN THE DATA.
  # Three hours sizes the archive arm, whose long pole is a copy. The restore
  # arm's long pole is a WAIT: a GLACIER object is not readable, and the Standard retrieval tier
  # takes 3-5 hours to produce the temporary copy the copy-back reads — so the old ceiling would
  # have killed a healthy restore before S3 had finished with it. The restore's terms are the
  # retrieval budget (RESTORE_POLL_SECONDS x RESTORE_MAX_POLLS = 7 hours, deliberately above the
  # tier's own 5 because giving up early makes the user pay for a SECOND billed retrieval), the
  # poll's own work, the copy-back at the same makespan rate as the archive copy, both Maps'
  # per-child overhead and the serial verbs — ~35,500s in total.
  # test_the_whole_restore_fits_the_machines_ceiling COMPUTES every one of those from the
  # constants and reads this number back.
  #
  # IT IS ONE FIELD ON ONE MACHINE, so the ARCHIVE arm's backstop rises with it — a wedged
  # archive is now reported after twelve hours rather than three. That is the accepted cost of
  # the two arms sharing a machine (which they do because a restore is meaningless without the
  # archive that produced it); TimeoutSeconds is top-level ASL and cannot differ per branch. The
  # archive arm's own worst legal run is ~8,100s and still clears this by 5x.
  state_machine_timeout_seconds = 43200

  # Mirrored from arcommon/config.py's RESTORE_POLL_SECONDS, which is where it
  # is REASONED about — five minutes against a 3-5 hour retrieval is ~1% of the wait spent
  # asking. Terraform cannot import Python, so the ASL's Wait carries a literal fed from here and
  # a test asserts the rendered number still equals the constant, exactly as the transfer Map's
  # batch numbers are held together.
  #
  # THE ITERATION CAP IS DELIBERATELY NOT HERE. RESTORE_MAX_POLLS lives only in Python, because
  # poll-restore computes `exhausted` itself rather than the Choice comparing against a literal —
  # two homes for that number would only disagree on a restore that was already going badly.
  restore_poll_seconds = 300

  # The Distributed Map's OWN permissions belong to the STATE
  # MACHINE role: it is the state machine that calls StartExecution for each child and
  # that reads the ItemReader object and writes the ResultWriter export. Granting these to
  # the Lambda execution role renders, applies and unit-tests green, then fails on the
  # first real archive with AccessDenied at the ItemReader.
  # The same wildcard also scopes the DescribeExecution the timeout door needs, which IS
  # on the Lambda role because it is the notify-failure LAMBDA that makes that call.
  child_execution_arn_wildcard = "arn:aws:states:${var.aws_region}:${var.account_id}:execution:${local.state_machine_name}:*"

  sfn_log_group_name = "/aws/vendedlogs/states/${local.state_machine_name}"
  sfn_log_group_arn  = "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:${local.sfn_log_group_name}"
  state_machine_arn  = "arn:aws:states:${var.aws_region}:${var.account_id}:stateMachine:${local.state_machine_name}"
}
