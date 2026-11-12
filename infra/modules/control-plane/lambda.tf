# Every verb is a call to the fleet's one container module. Terraform owns the function, CI owns
# which image it runs.
module "functions" {
  source   = "../docker-lambda"
  for_each = var.functions

  function_name        = local.function_names[each.key]
  role_arn             = aws_iam_role.execution.arn
  image_repository_url = var.lambda_image_repository_url
  image_tag            = var.lambda_image_tag

  command = [each.value.handler]

  timeout_seconds      = each.value.timeout
  memory_mb            = each.value.memory
  ephemeral_storage_mb = each.value.ephemeral_storage_mb

  environment = merge(var.environment_variables, each.value.environment)

  depends_on = [aws_iam_role_policy.execution]
}
