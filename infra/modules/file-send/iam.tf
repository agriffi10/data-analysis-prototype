# ── Control-plane IAM roles ─────────────────────────────────────────────────────────────────
# ONE shared execution role for every verb Lambda (the consolidated model every plane
# uses), plus the Step Function role and the Pipe role. Trust +
# permission policies are .tftpl templates rendered with templatefile() (no inline
# jsonencode IAM, per architecture.md).
#
# The execution policy grants exactly what the shipped verbs need and nothing this arc
# does not yet provision: the registry read that authorizes a shared source, the Cognito
# check that resolves a `user` recipient, the notifications queue, the logs queue, its
# own log group, the source listing and read, and the copy plan write.
#
# THE SOURCE GRANTS ARE BUCKET-WIDE, AND THE ISOLATION IS NOT IN THEM. A per-user
# condition is not expressible here: the sender is a runtime value from a verified token,
# not a principal tag on this role (the role IS the privileged path — that is the whole
# reason the plane exists). The isolation is fscommon.authz + fscommon.paths, applied
# before any listing and re-applied to every key the listing returns, which is why those
# two modules carry the heaviest tests on this plane. Same shape, same reasoning, as
# table-share's execution role.
#
# THE ONLY WRITE INTO A USER'S SPACE IS UNDER shared_files/. The
# copy needs PutObject plus the two multipart actions an object over S3's 5 GiB
# single-copy limit takes, and they are scoped to `*/shared_files/*` in both data
# buckets — so this role can write into an inbox and NOWHERE ELSE in anybody's prefix.
# It mirrors table-share's shipped `*/shared_tables/*` grant one for one, which is the
# point: two planes writing into user space under one pattern is reviewable, two
# patterns is not.
#
# AdminGetUser ALONE, deliberately: table-share's twin statement also carries
# cognito-idp:ListUsers, which nothing in this repo calls — every existence check in the
# fleet is admin_get_user, and FR-004 AC4 makes that a rule rather than a habit. ListUsers
# would let this role enumerate the whole pool (every username, email and attribute), and
# this is a role on the user-space bucket's principal allowlist. Copying it over would have
# widened the blast radius for no functionality.

# ── Shared Lambda execution role (uniform lambda trust) ──────────────────────
resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name = "permissions"
  role = aws_iam_role.execution.id

  # NoDataObjectDelete: a Deny, present from the first apply rather than
  # added alongside the copy. A SEND IS A COPY — it never deletes the sender's copy
  # (the spec's Out of Scope says so) and it never overwrites at the destination — so
  # nothing on this plane will ever need s3:DeleteObject. Writing the Deny now makes
  # that an enforced property instead of an intention, and costs nothing: no verb here
  # deletes anything today, so it cannot break an apply or a run. It is the same shape
  # table-share carries, and the reason it is worth carrying is that this role is on
  # the user-space bucket's principal allowlist — a bug in a later verb would be
  # deleting some other user's data.
  #
  # NOTE FOR ANYONE ADDING A STATEMENT: IAM rejects a "//" comment key inside a
  # statement ("Policy input list item 1 has invalid content" — verified with
  # simulate_custom_policy), so rationale goes HERE, not in the .tftpl.
  # states:DescribeExecution is the ONE grant the timeout door needs, and it
  # is on THIS role rather than the state machine's because it is the notify-failure LAMBDA that
  # makes the call — invoked by EventBridge, outside any execution. It reads back the input of a
  # run whose event omitted it, which on this plane is the ordinary case for a large send:
  # EventBridge caps an event at 256 KB and the Pipe record is allowed to approach 200 KB, so
  # without this the sends most likely to time out are the ones nobody can be told about.
  policy = templatefile("${path.module}/policies/execution.json.tftpl", {
    execution_arn_wildcard  = local.child_execution_arn_wildcard
    log_group_arn           = local.file_send_log_group_wildcard_arn
    admin_bucket_arn        = local.admin_bucket_arn
    user_space_bucket_arn   = local.user_space_bucket_arn
    shared_space_bucket_arn = local.shared_space_bucket_arn
    user_pool_arn           = local.user_pool_arn
    notifications_queue_arn = var.notifications_queue_arn
    logs_queue_arn          = var.logs_queue_arn
  })
}

# ── Portal role — file-send enqueue policy ─────────────────
# THE BROWSER'S ONLY FILE-SEND PRIVILEGE: sqs:SendMessage to the request queue. No
# cross-prefix S3 write is granted to any user, ever — that the browser cannot write
# into another user's prefix is the isolation model working, and is the entire reason
# this plane exists. A small inline policy on the shared portal role,
# attached BY NAME like the table-builder / table-share / notifications modules (the
# role is created in module.data; the root module-level depends_on guarantees it
# exists first). No Lambda invoke, no DLQ, no Step Function — just enqueue.
resource "aws_iam_role_policy" "portal_file_send" {
  name = "file-send-enqueue"
  role = var.portal_role_name

  policy = templatefile("${path.module}/policies/portal-role-file-send.json.tftpl", {
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

  # InvokeFunction on the verbs + log delivery, plus the Distributed Map's
  # own permissions — which belong HERE and not on the execution role (
  # FR-006): the state machine is what calls StartExecution for each child and what
  # reads the ItemReader object / writes the ResultWriter export. Putting them on the
  # Lambda role renders, applies and unit-tests green, then fails on the first real
  # send with AccessDenied at the ItemReader.
  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json           = jsonencode(local.file_send_function_arns)
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
