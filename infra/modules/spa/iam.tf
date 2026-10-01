# ── Two roles, and the second one holds nothing ───────────────────────────────
# Execution is ECS's (pull + log stream, before the container exists); task is the container's
# own identity, and the SPA makes no AWS call. MERGING THEM APPLIES GREEN FOREVER and hands the
# running container the pull and log-write grants for no reason. README.md.

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

# A SCOPED DOCUMENT, not AmazonECSTaskExecutionRolePolicy — the managed policy grants the pull
# actions on EVERY repository in the account, behind an attachment the rendered-plan IAM scan
# cannot read. ecr:GetAuthorizationToken sits alone in its own statement because it takes no
# resource type. INLINE, because the deploy role holds no usable AttachRolePolicy. README.md.
resource "aws_iam_role_policy" "task_execution" {
  name = "${local.spa_name}-task-execution-policy"
  role = aws_iam_role.task_execution.id

  policy = templatefile("${path.module}/policies/task-execution-policy.json.tftpl", {
    repository_arn = var.repository_arn
    log_group_arn  = aws_cloudwatch_log_group.spa.arn
  })
}
