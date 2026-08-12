# ── Control-plane IAM roles (SPEC-168) ───────────────────────────────────────
# ONE shared execution role for every verb Lambda (the consolidated model every plane has
# used since SPEC-062), plus the Step Function role and the Pipe role. Trust + permission
# policies are .tftpl templates rendered with templatefile() (no inline jsonencode IAM,
# per architecture.md).
#
# The execution policy grants exactly what the shipped verbs need: the registry read that
# authorizes a shared source, the notifications and logs queues, its own log group, and —
# since SPEC-169 — the source listing and read, the copy plan and manifest in the admin
# bucket, the receipt write, the archive vault, and the SOURCE DELETION.
#
# THE SOURCE DELETION IS THE STATEMENT TO READ TWICE, AND IT IS WHY THIS ROLE IS UNLIKE
# EVERY OTHER PLANE'S. Archiving is the only operation in this repo that deletes a user's
# data as a side effect of a copy. File-send and table-share each carry a blanket
# `Deny s3:DeleteObject` from their first apply and have that be an enforced property
# forever; this role cannot, so the property that replaces it is narrower and is written
# out rather than assumed:
#
#   * DeleteObject is granted on the two SPACE buckets only — never the admin bucket, and
#     never the archive bucket's own data by this statement;
#   * NeverDeletePortalManagedObjects then Denies it under `athenaresults/` (the portal
#     role's own results, which the bucket policy would refuse mid-batch anyway),
#     `user_settings/` (the notification inbox and connections cache), `archive/` (the
#     receipts THIS plane writes — archiving an archive) and on any `DO_NOT_DELETE.txt` at
#     any depth, because `*` matches `/` in an IAM resource;
#   * an explicit Deny beats every Allow, including a future one, which is the point of
#     writing it as a Deny rather than by narrowing the Allow.
#
# The IAM narrowing is the second line of defence and not the first. The first is the
# commit gate — the source is deleted only when every object has been confirmed copied —
# and the second is `arcommon.delete.assert_deletable`, which refuses the whole list
# BEFORE issuing anything, so a key the policy would refuse fails the run rather than
# stopping a deletion half way through.
#
# THE ARCHIVE BUCKET'S DeleteObject IS THE ROLLBACK'S, and it is the one grant that looks
# surprising on a vault. A partial copy is not an archive, so it is removed; without this
# the gate could refuse the deletion but not clean up after itself, and the residue would
# sit at the GLACIER 90-day minimum until the 7-year expiry. SPEC-171 uses the same grant
# to clear a restored archive.
#
# SPEC-171 ADDS TWO THINGS, AND THE SECOND IS A DELIBERATE WIDENING THAT MUST NOT ARRIVE
# SILENTLY IN A DIFF.
#
#   * s3:RestoreObject on the vault (ArchiveVaultRetrieve). It is a DISTINCT ACTION from
#     GetObject and PutObject — a role holding both still cannot initiate a retrieval, and
#     the failure would be an AccessDenied at the point of no return rather than at plan
#     time.
#   * s3:PutObject on the two SPACE buckets, unrestricted by prefix within the space root
#     (SpaceDataWrite, replacing SPEC-169's ReceiptWrite). SPEC-169 needed only `*/archive/*`
#     because the only thing it wrote into a user's space was a receipt. A RESTORE writes
#     wherever the data came from, which is anywhere in the space, so the narrow grant cannot
#     stand. The multipart pair joins it because an archived object may be up to
#     ARCHIVE_MAX_OBJECT_BYTES (10 GiB) and the copy-back part-copies above 5 GiB.
#
# NeverOverwritePortalManagedObjects is the narrowing that goes with that widening, and it
# is defence in depth rather than the rule itself. `athenaresults/` and `user_settings/` can
# never appear in an archive — RESERVED_SOURCE_ROOTS refuses them at archive time, and the
# destination guard's fail-closed 403-is-occupied rule refuses them again at restore time —
# so this Deny cannot refuse a legitimate restore. What it buys is that a plan which somehow
# named one of them could not overwrite the notification inbox or a user's query results. It
# deliberately does NOT cover `archive/`, which is where the receipt this plane writes lives.

# NOTE: the Deny above and NeverDeletePortalManagedObjects are two different verbs on two
# overlapping prefix sets, and the difference is the receipt: this plane may WRITE under
# `archive/` and may never DELETE there.
#
# NOTE FOR ANYONE ADDING A STATEMENT: IAM rejects a "//" comment key inside a statement
# ("Policy input list item 1 has invalid content" — verified with simulate_custom_policy),
# so rationale goes HERE, not in the .tftpl.
# states:DescribeExecution (SPEC-169 FR-003) is the ONE grant the timeout door needs, and
# it is on THIS role rather than the state machine's because it is the notify-failure
# LAMBDA that makes the call — invoked by EventBridge, outside any execution. It reads back
# the input of a run whose event omitted it, which on this plane is the ordinary case for a
# large archive: EventBridge caps an event at 256 KB and the Pipe record is allowed to
# approach 200 KB, so the archives most likely to time out are the ones nobody could
# otherwise be told about.

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

# ── Portal role — archive enqueue policy (SPEC-168 FR-007) ───────────────────
# THE BROWSER'S ONLY POSITIVE ARCHIVE PRIVILEGE: sqs:SendMessage to the request queue.
# It is granted NOTHING on the archive bucket — not GetObject, not ListBucket, nothing —
# and a rendered-policy test asserts the portal role has no statement of any kind naming
# that ARN. The browser's only relationship with that bucket is that it has none, and the
# only route to archived bytes is a restore request through this plane.
#
# A small inline policy on the shared portal role (SPEC-011), attached BY NAME like the
# file-send / table-builder / table-share / notifications modules (the role is created in
# module.data; the root module-level depends_on guarantees it exists first). The two
# `archive/` write DENIES that go with this live in the space buckets' own portal
# templates (modules/data, modules/shared-spaces) — beside the Allows they narrow, which
# is the honest home for them.
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

  # InvokeFunction on the verbs + log delivery, plus (SPEC-169) the Distributed Map's own
  # permissions — which belong HERE and not on the execution role: the state machine is
  # what calls StartExecution for each child and what reads the ItemReader object and
  # writes the ResultWriter export. Putting them on the Lambda role renders, applies and
  # unit-tests green, then fails on the first real archive with AccessDenied at the
  # ItemReader (SPEC-160 FR-006's finding, inherited here rather than rediscovered).
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
