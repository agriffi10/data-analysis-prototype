# One container-packaged Lambda. Every function in the fleet is a call to this module, running the
# same image with a different command. ../../info/... and README.md beside this file.

# Explicit so retention is managed: without the resource, Lambda creates one on first invoke at
# INFINITE retention, and checkov's CKV_AWS_66 cannot see a log group that is not declared.
resource "aws_cloudwatch_log_group" "this" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_function" "this" {
  function_name = var.function_name
  role          = var.role_arn
  description   = var.description

  package_type = "Image"
  image_uri    = "${var.image_repository_url}:${var.image_tag}"

  image_config {
    command = var.command
  }

  # NO `handler`, NO `runtime`, NO `filename`, NO `layers`.
  #
  # The first three are refused for an Image function — `filename` conflicts with `image_uri`
  # outright, and handler/runtime are Zip-only. `layers` is the one worth stating: a container
  # function has none, its imports are a property of the image, and leaving a stale
  # `ignore_changes = [layers]` behind would be a fossil that reads as meaningful.

  timeout                        = var.timeout_seconds
  memory_size                    = var.memory_mb
  architectures                  = var.architectures
  reserved_concurrent_executions = var.reserved_concurrency

  environment {
    variables = var.environment
  }

  dynamic "vpc_config" {
    for_each = var.vpc_config == null ? [] : [var.vpc_config]
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  lifecycle {
    # CI owns which image a function runs. `image_uri` is NOT ForceNew, so without this every
    # apply would drag the whole fleet back to whatever sha Terraform was last given — and
    # because Terraform will therefore never move a function forward either, CI has to call
    # update-function-code on every function on every deploy. A pipeline that builds an image and
    # never points anything at it leaves all 86 functions on the previous one, each still working,
    # and nothing goes red.
    ignore_changes = [image_uri]
  }

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.this]
}
