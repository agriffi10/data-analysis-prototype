# ── Two roles, and the second one holds nothing ───────────────────────────────
# The execution role is ECS's: it pulls the image and opens the log stream, before the
# container exists. The task role is the container's own AWS identity — and the SPA container
# makes no AWS call, so it has no policy at all. Merging them applies green forever, because
# nothing the container does would fail, and hands the running container the registry pull
# and log-write grants for no reason.

resource "aws_iam_role" "task" {
  name               = "${local.spa_name}-task-role"
  assume_role_policy = file("${path.module}/policies/task-trust-policy.json")

  tags = { Name = "${local.spa_name}-task-role" }
}

resource "aws_iam_role" "task_execution" {
  name               = "${local.spa_name}-task-execution-role"
  assume_role_policy = file("${path.module}/policies/task-trust-policy.json")

  tags = { Name = "${local.spa_name}-task-execution-role" }
}

# A SCOPED DOCUMENT, not AmazonECSTaskExecutionRolePolicy. The managed policy grants the three
# pull actions on every repository in the account and hides that breadth behind an attachment
# the rendered-plan IAM scan cannot read. Here the pull is scoped to this repository, the log
# write to this group, and the one genuinely unscopable action — ecr:GetAuthorizationToken
# takes no resource type at all — is left alone in its own statement where it is visible.
#
# Inline rather than a customer-managed policy plus an attachment, for the same reason the API
# function's role is inline: the deploy role holds iam:PutRolePolicy on these roles and holds
# neither iam:AttachRolePolicy nor a iam:CreatePolicy this could use.
resource "aws_iam_role_policy" "task_execution" {
  name = "${local.spa_name}-task-execution-policy"
  role = aws_iam_role.task_execution.id

  policy = templatefile("${path.module}/policies/task-execution-policy.json.tftpl", {
    repository_arn = aws_ecr_repository.spa.arn
    log_group_arn  = aws_cloudwatch_log_group.spa.arn
  })
}
