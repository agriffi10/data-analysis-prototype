# One function that runs on a schedule: its role, the function, and the EventBridge rule, target
# and permission that start it. README.md.

resource "aws_iam_role" "this" {
  name               = var.role_name
  assume_role_policy = coalesce(var.trust_policy, templatefile("${path.module}/policies/lambda-trust.json.tftpl", {}))
}

resource "aws_iam_role_policy" "this" {
  for_each = var.role_policies

  name   = each.key
  role   = aws_iam_role.this.id
  policy = each.value
}

module "function" {
  source = "../docker-lambda"

  function_name        = var.function_name
  role_arn             = aws_iam_role.this.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  command = [var.handler]

  timeout_seconds = var.timeout_seconds
  memory_mb       = var.memory_mb

  environment = var.environment_variables

  depends_on = [aws_iam_role_policy.this]
}

resource "aws_cloudwatch_event_rule" "this" {
  name                = var.rule_name
  description         = var.rule_description
  schedule_expression = var.schedule_expression
}

resource "aws_cloudwatch_event_target" "this" {
  rule = aws_cloudwatch_event_rule.this.name
  arn  = module.function.function_arn
}

# Bound to the function's ARN, never its name: a name is known at plan and lets a replacement
# function take the permission while the plan shows no diff.
resource "aws_lambda_permission" "this" {
  statement_id  = var.permission_statement_id
  action        = "lambda:InvokeFunction"
  function_name = module.function.function_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.this.arn
}
