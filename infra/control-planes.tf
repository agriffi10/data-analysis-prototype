# What every control plane's execution policy may name, as constructed strings so each policy is
# known at plan. Each plane's own file (plane-<slug>.tf) adds what only it reads.
locals {
  control_plane_policy_arns = {
    admin_bucket_arn        = local.athena_admin_bucket_arn
    user_space_bucket_arn   = "arn:aws:s3:::${local.user_space_bucket_name}"
    shared_space_bucket_arn = local.shared_space_bucket_arn
    athena_workgroup_arn    = "arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${local.athena_workgroup_name}"
    glue_catalog_arn        = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog"
    glue_database_any       = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/*"
    glue_table_any          = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/*/*"
    user_pool_arn           = "arn:aws:cognito-idp:${var.aws_region}:${data.aws_caller_identity.current.account_id}:userpool/${module.auth.user_pool_id}"
    notifications_queue_arn = local.notifications_queue_arn
    logs_queue_arn          = module.observability.logs_queue_arn
  }

  control_plane_arn_prefix = {
    lambda_logs = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.project_name}-${var.environment}"
    executions  = "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:execution:${var.project_name}-${var.environment}"
  }
}
