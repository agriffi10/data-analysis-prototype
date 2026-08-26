# ── The placeholder API function ──────────────────────────────────────────────
# One function serves every route; the route table lives in the code. It performs no
# AWS call and resolves no identity, and its role says so — the grants below are the
# whole of its permissions, and a later spec adds what it needs when it needs it.
#
# NOT IN THE VPC, deliberately. The VPC exists for the container. Attaching this would
# need an interface endpoint per service the API later calls and would put ENI attachment
# on the cold-start path — and after the arc's provider swap the token-verification host
# is a third party with no AWS endpoint at all, so a function inside those subnets would
# stop verifying with no code change to blame.

locals {
  function_name = "${var.project_name}-${var.environment}-api"
}

# Placeholder package so the function is valid at create time. CI owns the real code.
# Without this the function cannot be created at all; without the ignore_changes below,
# every apply after the first REVERTS the deployed code back to this stub.
data "archive_file" "api_placeholder" {
  type        = "zip"
  output_path = "${path.module}/build/api-placeholder.zip"

  source {
    content  = "def handler(event, context):\n    raise Exception('api Lambda code not yet deployed by CI')\n"
    filename = "handler.py"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "api" {
  name               = "${local.function_name}-role"
  assume_role_policy = file("${path.module}/policies/api-trust-policy.json")
}

# Inline, not a customer-managed policy plus an attachment. The deploy role holds
# iam:PutRolePolicy on this role and holds neither iam:AttachRolePolicy nor a
# iam:CreatePolicy scoped anywhere this could use — so the managed shape is refused at
# apply, and the refusal reads as a missing permission rather than as a wrong shape.
resource "aws_iam_role_policy" "api" {
  name = "${local.function_name}-policy"
  role = aws_iam_role.api.id

  policy = templatefile("${path.module}/policies/api-execution-policy.json.tftpl", {
    log_group_arn  = aws_cloudwatch_log_group.api.arn
    logs_queue_arn = var.logs_queue_arn
  })
}

resource "aws_lambda_function" "api" {
  function_name = local.function_name
  role          = aws_iam_role.api.arn
  runtime       = "python3.12"
  handler       = "handler.handler"

  # One second under API Gateway's hard 30s integration ceiling, which is not raisable on
  # an HTTP API. Past it the caller gets a 504 while the invocation keeps running and
  # keeps billing, so the function should give up first and say so.
  timeout     = 29
  memory_size = 256

  filename         = data.archive_file.api_placeholder.output_path
  source_code_hash = data.archive_file.api_placeholder.output_base64sha256

  environment {
    variables = {
      COGNITO_USER_POOL_ID  = var.user_pool_id
      COGNITO_APP_CLIENT_ID = var.app_client_id
      ADMIN_BUCKET          = var.admin_bucket
      USER_SPACE_BUCKET     = var.user_space_bucket
      SHARED_SPACE_BUCKET   = var.shared_space_bucket
      ATHENA_WORKGROUP      = var.athena_workgroup
      LOGS_QUEUE_URL        = var.logs_queue_url
      ENV_NAME              = var.environment
    }
  }

  lifecycle {
    # CI owns the code AND the layer attachment. `layers` belongs in this list beside the
    # code: an apply landing after a deploy would otherwise strip the layer straight back
    # off, and the function would fail at cold start on an import that had been working.
    ignore_changes = [filename, source_code_hash, layers]
  }

  depends_on = [
    aws_iam_role_policy.api,
    aws_cloudwatch_log_group.api,
  ]
}
