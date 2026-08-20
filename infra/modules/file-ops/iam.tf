# ── Control-plane IAM roles ─────────────────────────────────────────────────────────────────
# ONE shared execution role for every verb Lambda (the consolidated model every plane
# uses), plus the Step Function role and the Pipe role. Trust + permission policies are
# .tftpl templates rendered with templatefile() (no inline jsonencode IAM).
#
# THIS ROLE HOLDS NO GRANT ON EITHER DATA BUCKET, AND THAT IS THE POINT AT THIS STAGE.
# It will eventually hold DeleteObject across the user-space bucket — the single most
# dangerous grant in this repo — and it does not get it here. The machine lists nothing,
# copies nothing and deletes nothing, so a grant would be unreviewable privilege sitting
# in production ahead of the code that justifies it. A test asserts the rendered policy
# names no data bucket, so it cannot arrive early and unnoticed.
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
#   - ReadSpaceObjects. THE FIRST GRANT THIS ROLE HOLDS ON USER DATA, and it is READ
#     ONLY. The expansion lists a source folder and heads a selected file; the guard heads
#     every destination key. Both are reads, and neither has any other producer — a
#     listing is where the object list comes from, and the ETag it carries is what lets a
#     later deletion be conditional. The write and delete grants a transfer needs are still
#     absent, and NoDataObjectWrite below makes that a rule rather than a gap.
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
# NoDataObjectWrite is the second Deny, and it exists because "read only" asserted by the
# ABSENCE of an Allow is not a rule — it is a state a later statement reverses silently. The
# machine plans and guards; it writes nothing into either space bucket and deletes nothing
# from them. The spec that adds the transfer removes this Deny deliberately, which is a
# review a widened Allow would never have had.
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

  # InvokeFunction on the verbs + log delivery, and NOTHING ELSE. The neighbouring planes
  # also carry the Distributed Map's own permissions on this role — StartExecution for the
  # children, and the ItemReader/ResultWriter S3 access — because it is the state machine
  # that makes those calls. There is no Map here yet, so those statements are absent; the
  # spec that adds the transfer adds them, on THIS role rather than the Lambda one.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json = jsonencode(local.file_ops_function_arns)
    sfn_log_group_arn  = local.sfn_log_group_arn
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
