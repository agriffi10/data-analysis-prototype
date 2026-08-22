# ── Control-plane IAM roles ─────────────────────────────────────────────────────────────────
# ONE shared execution role for every verb Lambda (the consolidated model every plane
# uses), plus the Step Function role and the Pipe role. Trust + permission policies are
# .tftpl templates rendered with templatefile() (no inline jsonencode IAM).
#
# THIS ROLE NOW HOLDS DeleteObject ACROSS BOTH DATA BUCKETS — the single most dangerous
# grant in this repo — and it arrives GRANTS-FIRST, together with the code that justifies
# it and the Denies that bound it. The two earlier specs deliberately shipped without it,
# so this widening is a review of its own rather than a line inside a larger change.
#
# WHAT IT DOES HOLD, AND WHY EACH ONE IS NOT AN EXCEPTION TO THAT:
#
#   - EmitNotifications. The failure path ships from day one and that verb enqueues a
#     notification, so a role without this cannot run this module's own first failure
#     path. Every plane passes the notifications queue in for exactly this verb.
#   - RegistryRead. Authorizing a SHARED space is a registry read, and without it every
#     shared-space source or destination fails AccessDenied while every personal one
#     works — a split that reads like a code bug and is not.
#   - SpaceLockReadWrite. The lock object, scoped to its own prefix.
#   - PlanReadWrite. The copy plan, scoped to its own prefix in the same bucket. The
#     expansion writes it and every verb after reads it back; without this the plane
#     cannot record what it is about to do.
#   - ReadSpaceObjects. The expansion lists a source folder and heads a selected file; the
#     guard heads every destination key; the deletion heads every source key to compare it
#     against the ETag the plan recorded. It is ALSO a hard requirement of a conditional
#     delete: AWS documents that a valued If-Match delete needs BOTH s3:DeleteObject AND
#     s3:GetObject, so narrowing this grant later would silently break every conditional
#     deletion rather than failing loudly.
#   - WriteSpaceObjects / DeleteSpaceObjects. What the transfer and the source deletion
#     actually do. ListMultipartUploadParts and AbortMultipartUpload are there because an
#     object over 5 GiB copies through UploadPartCopy, and an aborted upload that cannot be
#     cleaned up accrues storage the user never sees.
#   - ReadTimedOutExecutionInput. The ONE grant the timeout door needs, and it is on THIS
#     role rather than the state machine's because it is the notify-failure LAMBDA that
#     makes the call — invoked by EventBridge, outside any execution. It reads back the
#     input of a run whose event omitted it, which on this plane is the ordinary case for
#     a large selection: EventBridge caps an event at 256 KB and this plane's own cap
#     allows a request to approach it.
#
# NO COGNITO GRANT, and the absence is deliberate rather than pending. Token verification
# is offline against the pool's public JWKS — an HTTPS fetch, not an API call — and this
# plane looks nobody up: it authorizes the actor against a space, never against a user
# directory. The neighbouring planes carry AdminGetUser because they resolve a RECIPIENT;
# there is no recipient here.
#
# NoDataObjectWrite IS GONE, deliberately and by name. It was the blanket "this role writes
# nothing into a user's space" Deny, and the transfer is exactly what it forbade. Removing a
# Deny is the kind of edit that should be hard to do by accident, which is why the two specs
# before this one left it in place and said in this file that the transfer spec would take
# it out.
#
# WHAT REPLACES IT IS NARROWER BUT NOT WEAKER WHERE IT MATTERS: the portal's own folders are
# still unwritable and undeletable by this role, now stated as their own two Denies.
#
# THE PORTAL-MANAGED DENIES ARE ANY-DEPTH ON BOTH BUCKETS, AND THAT IS STRICTER THAN THE
# BROWSER'S OWN RULE IN ONE CASE. The browser refuses athenaresults/ root-anchored in a
# personal space (its policy is written against ${aws:PrincipalTag/username}, which pins it
# to one segment) and at any depth in a shared one. This role carries no principal tag, and
# an IAM Resource wildcard matches "/" — there is no way to say "exactly one path segment"
# — so the personal case cannot be expressed root-anchored here and the strict side is
# taken. The consequence is real and is handled rather than hidden: a personal folder
# holding a NESTED athenaresults/ is undeletable by this plane, so focommon/delete.py
# mirrors THIS POLICY rather than the browser's rule and refuses such an item per item,
# before anything is copied. Mirroring the browser instead would produce an AccessDenied
# part way through a batch, after the copy, with the source half gone.
#
# THE s3:if-match BUCKET-POLICY ENFORCEMENT IS DECLINED, and the reason is recorded here
# rather than left for someone to re-propose. The documented pattern —
# "Null": {"s3:if-match": "false"} — denies any delete that carries no condition header. It
# cannot be used because this plane has TWO delete paths with different conditionality on
# purpose: a move's deletion is conditional on the ETag the plan recorded, and a delete
# operation's is deliberately unconditional (there is no copy to protect, and an object
# modified since the expansion is still one the user asked to remove). A bucket-wide
# condition cannot express both, so enabling it would 403 every delete-operation deletion.
#
# THE MARKER DENY MATCHES A PATH SEGMENT, NOT A SUFFIX. `*/DO_NOT_DELETE.txt` and not
# `*DO_NOT_DELETE.txt`, which is the form the archive plane uses: the suffix form also matches
# `alice/reports/backupDO_NOT_DELETE.txt`, a perfectly ordinary user file. Every code rule on this
# plane matches the BASENAME exactly, so the suffix form would let such a key pass the pre-delete
# check, get copied, and then take an AccessDenied mid-batch — leaving the item reported as a
# duplicate with an orphan behind it. That is precisely the mid-batch denial the pre-check exists to
# prevent. Both bucket policies already use the segment form; this now agrees with them.
#
# NoLockDelete is a Deny, present from the first apply. The lock releases by OVERWRITING,
# never by deleting, so that "free" is a STATE of the object rather than its absence and a
# stolen lock stays detectable by compare-and-set. Writing the Deny now makes that an
# enforced property instead of a convention, and it costs nothing: no verb here deletes
# anything. It is scoped to the ADMIN bucket alone, so the data-bucket deletes a later
# spec adds are unaffected.
#
# NOTE FOR ANYONE ADDING A STATEMENT: IAM rejects a "//" comment key inside a statement,
# so rationale goes HERE, not in the .tftpl.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    execution_arn_wildcard  = local.execution_arn_wildcard
    log_group_arn           = local.file_ops_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    lock_prefix             = local.lock_prefix
    plan_prefix             = local.plan_prefix
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
  })
}

# ── Portal role — file-ops enqueue policy ─────────────────
# THE BROWSER'S ONLY FILE-OPS PRIVILEGE: sqs:SendMessage to the request queue. No
# cross-prefix S3 write is granted to any user, ever — that the browser cannot write into
# another user's prefix is the isolation model working, and is the entire reason this
# plane exists. A small inline policy on the shared portal role, attached BY NAME like
# every other plane's (the role is created in module.data; the root module-level
# depends_on guarantees it exists first). No Lambda invoke, no DLQ, no Step Function.
resource "aws_iam_role_policy" "portal_file_ops" {
  name = "file-ops-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-file-ops.json.tftpl", {
    request_queue_arn = aws_sqs_queue.requests.arn
  })
}

# ── Step Function role (orchestrates the verbs) ──────────────────────────────
resource "aws_iam_role" "sfn" {
  name               = local.sfn_role_name
  assume_role_policy = templatefile("${path.module}/policies/sfn-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "sfn" {
  name = "permissions"
  role = aws_iam_role.sfn.id

  # InvokeFunction on the verbs, the Distributed Map's own permissions, and log delivery.
  #
  # THE MAP'S GRANTS BELONG ON THIS ROLE AND NOT ON THE EXECUTION ROLE, and getting that
  # wrong is invisible until runtime: it is the STATE MACHINE that starts the child
  # executions and that reads the manifest through the ItemReader and writes the export
  # through the ResultWriter. Put them on the Lambda role instead and the module renders,
  # applies and unit-tests green, then AccessDenies at the ItemReader on the first real
  # transfer.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json           = jsonencode(local.file_ops_function_arns)
    sfn_log_group_arn            = local.sfn_log_group_arn
    state_machine_arn            = local.state_machine_arn
    child_execution_arn_wildcard = local.child_execution_arn_wildcard
    admin_bucket_arn             = local.admin_bucket_arn
    plan_prefix                  = local.plan_prefix
  })
}

# ── Pipe role (EventBridge Pipe) ─────────────────────────────────────────────
resource "aws_iam_role" "pipe" {
  name               = local.pipe_role_name
  assume_role_policy = templatefile("${path.module}/policies/pipe-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "pipe" {
  name = "pipe"
  role = aws_iam_role.pipe.id

  policy = templatefile("${path.module}/policies/pipe-permissions.json.tftpl", {
    queue_arn         = aws_sqs_queue.requests.arn
    state_machine_arn = local.state_machine_arn
  })
}
