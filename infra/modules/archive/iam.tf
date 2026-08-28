# ── Control-plane IAM roles ───────────────────────────────────────────────────
# One shared execution role, the Step Function role and the Pipe role.
#
# ⚠ THE SOURCE DELETION IS THE STATEMENT TO READ TWICE, AND IT IS WHY THIS ROLE IS UNLIKE
# EVERY OTHER PLANE'S. Every other plane carries a blanket Deny s3:DeleteObject forever; this
# one cannot, so the narrower property is written out instead: DeleteObject on the two SPACE
# buckets only, then NeverDeletePortalManagedObjects Denies it under athenaresults/,
# user_settings/, archive/ and any DO_NOT_DELETE.txt at any depth. AN EXPLICIT DENY BEATS EVERY
# ALLOW, INCLUDING A FUTURE ONE — which is why it is a Deny and not a narrowed Allow.
#
# THE IAM NARROWING IS THE SECOND LINE OF DEFENCE, NOT THE FIRST. The first is the commit gate;
# the second is arcommon.delete.assert_deletable, which refuses the WHOLE list before issuing
# anything, so a key the policy would refuse fails the run rather than stopping half way.
#
# The archive bucket's own DeleteObject is THE ROLLBACK'S — a partial copy is not an archive,
# and without this the residue sits at the GLACIER 90-day minimum until the 7-year expiry.
#
# THE RESTORE'S TWO ADDITIONS MUST NOT ARRIVE SILENTLY IN A DIFF: s3:RestoreObject is a
# DISTINCT ACTION (a role holding Get and Put still cannot retrieve, and the failure would land
# at the point of no return), and s3:PutObject widened from */archive/* to the whole space root
# because a restore writes wherever the data came from.
#
# NeverOverwritePortalManagedObjects is the narrowing that goes with that widening, and it
# ALSO covers _config/ and _directory/, WHICH ARE AT THE BUCKET ROOT — a */x/* pattern cannot
# match a key with one segment before the folder, so the feature-flag document and the username
# directory were outside a statement whose name claims to cover portal-managed state.
#
# The two Denies are different VERBS on overlapping prefixes, and the difference is the
# receipt: this plane may WRITE under archive/ and may never DELETE there.
#
# ⚠ IAM REJECTS A "//" COMMENT KEY INSIDE A STATEMENT ("Policy input list item 1 has invalid
# content", verified with simulate_custom_policy), so rationale goes HERE, never in the .tftpl.
#
# states:DescribeExecution is on THIS role because it is the notify-failure LAMBDA that calls it,
# invoked by EventBridge outside any execution. It reads back the input of a run whose event
# omitted it, which on this plane is the ordinary case for a large archive: EventBridge caps an
# event at 256 KB and the Pipe record may approach 200 KB, so the archives most likely to time out
# are the ones nobody could otherwise be told about. README.md.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    log_group_arn           = local.archive_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    archive_bucket_arn      = local.archive_bucket_arn
    execution_arn_wildcard  = local.child_execution_arn_wildcard
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
  })
}

# ── Portal role — archive enqueue policy ───────────────────
# The browser's ONLY positive privilege here: sqs:SendMessage. IT IS GRANTED NOTHING ON THE
# ARCHIVE BUCKET — not GetObject, not ListBucket, nothing — and a rendered-policy test asserts
# the portal role has no statement of any kind naming that ARN. The only route to archived
# bytes is a restore through this plane.
#
# The two `archive/` write DENIES that go with this live in the space buckets' own portal
# templates, beside the Allows they narrow. README.md.
resource "aws_iam_role_policy" "portal_archive" {
  name = "archive-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-archive.json.tftpl", {
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

  # ⚠ THE MAP'S GRANTS BELONG HERE AND NOT ON THE EXECUTION ROLE. Putting them on the Lambda
  # role renders, applies and unit-tests green, then fails on the first real archive with
  # AccessDenied at the ItemReader.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json           = jsonencode(local.archive_function_arns)
    sfn_log_group_arn            = local.sfn_log_group_arn
    state_machine_arn            = local.state_machine_arn
    child_execution_arn_wildcard = local.child_execution_arn_wildcard
    admin_bucket_arn             = local.admin_bucket_arn
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
