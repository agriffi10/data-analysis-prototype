# Three roles, three jobs: the Pipe only starts an execution, the Step Functions role invokes the
# verbs, and the execution role is what the verbs run as. No enqueue grant lives here; the API's
# role holds the one that writes this queue.

resource "aws_iam_role" "execution" {
  name               = local.execution_role_name
  assume_role_policy = templatefile("${path.module}/policies/lambda-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "execution" {
  name   = var.execution_policy_name
  role   = aws_iam_role.execution.id
  policy = var.execution_policy
}

resource "aws_iam_role" "sfn" {
  name               = local.sfn_role_name
  assume_role_policy = templatefile("${path.module}/policies/sfn-trust.json.tftpl", {})
}

resource "aws_iam_role_policy" "sfn" {
  name = "permissions"
  role = aws_iam_role.sfn.id

  policy = templatefile("${path.module}/policies/sfn-permissions.json.tftpl", {
    function_arns_json           = jsonencode(local.constructed_function_arns)
    sfn_log_group_arn            = local.sfn_log_group_arn
    state_machine_arn            = local.state_machine_arn
    admin_bucket_arn             = var.admin_bucket_arn
    distributed_map              = var.distributed_map != null
    manifest_prefix              = try(var.distributed_map.manifest_prefix, "")
    child_execution_arn_wildcard = try(var.distributed_map.child_execution_arn_wildcard, "")
    child_execution_actions_json = (
      try(var.distributed_map.can_stop, false)
      ? jsonencode(["states:DescribeExecution", "states:StopExecution"])
      : jsonencode("states:DescribeExecution")
    )
  })
}

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
