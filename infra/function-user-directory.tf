# The username directory: one scheduled function that lists the user-space bucket's workspace
# prefixes once a day and publishes them as _directory/usernames.json, which the browser reads to
# suggest usernames. Not a control plane — no queue, no state machine, no verbs. Its reasoning is
# in functions/user-directory/README.md.
#
# The bucket ARN and the logs queue are CONSTRUCTED STRINGS rather than module.data /
# module.observability outputs, so the policy renders at plan time. The builder writes into
# module.data's bucket only at runtime, so nothing at apply orders the two.

locals {
  user_directory_function_name = "${var.project_name}-${var.environment}-user-directory-build"

  # The reserved root prefix the document lives under. Kept in step with
  # build_directory.DIRECTORY_PREFIX — the builder writes here and the portal role reads here.
  user_directory_prefix = "_directory"
}

module "user_directory" {
  source = "./modules/scheduled-function"

  function_name = local.user_directory_function_name
  # NO `-role` suffix: the deploy grant scopes to role/${project_name}-*-user-directory-build
  # with no trailing wildcard, so a suffix is denied at CreateRole rather than caught at plan.
  role_name = "${var.project_name}-${var.environment}-user-directory-build"

  # This role holds NO s3:GetObject ANYWHERE. Check that before adding any grant — the
  # unconditioned ListBucket is accepted only because of it. functions/user-directory/README.md.
  role_policies = {
    "build" = templatefile("${path.root}/functions/user-directory/build.json.tftpl", {
      user_space_bucket_arn = "arn:aws:s3:::${local.user_space_bucket_name}"
      directory_prefix      = local.user_directory_prefix
      logs_queue_arn        = local.logs_queue_arn
      lambda_log_group_arn  = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.user_directory_function_name}"
    })
  }

  handler = "build_directory.handler"
  # The listing is delimited, so page count scales with USERS, not objects. This covers a
  # pathological directory rather than an ordinary one.
  timeout_seconds = 300
  memory_mb       = 512

  environment_variables = {
    # USER_SPACE_BUCKET is the only one this function reads; the rest are the cpcommon layer's
    # union. Do not remove one because the builder does not use it. test_build_directory.py
    # asserts this block against config.py's own declaration.
    USER_SPACE_BUCKET   = local.user_space_bucket_name
    SHARED_SPACE_BUCKET = local.shared_space_bucket_name
    ATHENA_WORKGROUP    = local.athena_workgroup_name
    ADMIN_BUCKET        = local.athena_admin_bucket_name
    # Deliberately NOT mirrored by a config._require: observability reads it with
    # os.environ.get, so losing it logs to stdout rather than crashing at cold start.
    LOGS_QUEUE_URL = local.logs_queue_url
    # Same source of truth as the feature-flag document's `environments` keys.
    ENV_NAME = var.environment
  }

  lambda_image_repository_url = module.lambda_image.repository_url
  lambda_image_tag            = var.lambda_image_tag

  # Rebuilt from scratch every run: a missed run costs staleness, never correctness. `-schedule`,
  # not `-sweep`: the deploy grant scopes to that rule name.
  rule_name               = "${local.user_directory_function_name}-schedule"
  rule_description        = "Rebuild the username directory from the user-space bucket's workspace prefixes, once a day."
  schedule_expression     = "rate(24 hours)"
  permission_statement_id = "AllowEventBridgeSchedule"

  # base grants the deploy role its user-directory perms. The write into the user-space bucket
  # happens only at RUNTIME, and this call names that bucket as a string, so nothing waits on
  # module.data.
  depends_on = [module.base]
}
