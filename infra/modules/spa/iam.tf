# ── Two roles, and each holds only its own work ───────────────────────────────
# Execution is ECS's (pull, log stream and the client secret, before the container exists); task
# is the container's own identity, and its one AWS call is the session store. MERGING THEM
# APPLIES GREEN FOREVER and hands the running container the pull, log-write and secret-read
# grants for no reason. README.md.

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
    repository_arn              = var.repository_arn
    log_group_arn               = local.log_group_arn
    client_secret_parameter_arn = var.client_secret_parameter_arn
  })
}

# The session store: item actions on the one table, and the key's use only as DynamoDB makes it
# for that table. key/* because the key's id is random and the key is created in the same apply as
# this document, which the plan-time IAM scan must be able to read; the two conditions are what
# bind it to this table. INLINE, for the reason the execution policy is.
resource "aws_iam_role_policy" "task_session" {
  name = "${local.spa_name}-task-session-policy"
  role = aws_iam_role.task.id

  policy = templatefile("${path.module}/policies/task-session-policy.json.tftpl", {
    aws_region         = var.aws_region
    account_id         = var.account_id
    session_table_arn  = var.session_table_arn
    session_table_name = var.session_environment["SESSION_TABLE_NAME"]
  })
}
