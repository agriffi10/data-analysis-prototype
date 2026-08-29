# ── Control-plane IAM roles ───────────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role.
#
# ⚠ THIS ROLE HOLDS DeleteObject ACROSS BOTH DATA BUCKETS — the single most dangerous grant in
# this repo. Every grant it carries, and why none is an exception, is in README.md.
#
# ReadSpaceObjects is a HARD REQUIREMENT of a conditional delete: AWS documents that a valued
# If-Match delete needs BOTH s3:DeleteObject AND s3:GetObject, so narrowing it later would
# SILENTLY break every conditional deletion rather than failing loudly.
#
# NO COGNITO GRANT, and the absence is deliberate: verification is offline JWKS, and this plane
# authorizes the actor against a SPACE, never against a user directory. There is no recipient.
#
# NoDataObjectWrite IS GONE, deliberately and by name — the transfer is exactly what it forbade.
# What replaces it is narrower but not weaker where it matters.
#
# THE PORTAL-MANAGED DENIES ARE ANY-DEPTH, which is STRICTER than the browser's rule in the
# personal case, because this role carries no principal tag and an IAM wildcard matches "/".
# focommon/delete.py MIRRORS THIS POLICY, not the browser's, and refuses per item BEFORE
# anything is copied — mirroring the browser gives an AccessDenied mid-batch with the source
# half gone.
#
# THE MARKER DENY MATCHES A PATH SEGMENT, NOT A SUFFIX. The suffix form also matches
# `backupDO_NOT_DELETE.txt`, an ordinary user file, which would then be copied and then denied
# mid-batch.
#
# THE s3:if-match BUCKET-POLICY ENFORCEMENT IS DECLINED: this plane has TWO delete paths with
# different conditionality ON PURPOSE, and a bucket-wide condition would 403 one of them.
#
# NoLockDelete is a Deny from the first apply — the lock releases by OVERWRITING, so "free" is
# a STATE rather than an absence. Scoped to the ADMIN bucket alone.
#
# ⚠ IAM REJECTS A "//" COMMENT KEY INSIDE A STATEMENT, so rationale goes HERE. README.md.

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

# ── Step Function role (orchestrates the verbs) ──────────────────────────────
resource "aws_iam_role" "sfn" {
  name               = local.sfn_role_name
  assume_role_policy = templatefile("${path.module}/policies/sfn-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "sfn" {
  name = "permissions"
  role = aws_iam_role.sfn.id

  # ⚠ THE MAP'S GRANTS BELONG ON THIS ROLE AND NOT ON THE EXECUTION ROLE, and getting it wrong
  # is INVISIBLE UNTIL RUNTIME: the module renders, applies and unit-tests green, then
  # AccessDenies at the ItemReader on the first real transfer.
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
