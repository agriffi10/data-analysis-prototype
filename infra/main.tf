# ── Module composition ────────────────────────────────────────────────────────
# Infrastructure is grouped into bounded-context modules:
#   app  — SPA hosting: static assets bucket, CloudFront distribution, OAC
#   base — foundation: GitHub Actions OIDC provider and deployment role
#   auth — Cognito: User Pool, SPA app client, Hosted UI domain (SPEC-006)
#   data — user-space S3 bucket (Bucket 1) + CORS/encryption (SPEC-010)
# Future contexts get their own modules rather than growing resource-type files.

# The user-space bucket name is computed once here and shared two ways: the data
# module creates the bucket with it, and the base module's deploy policy is scoped
# to its ARN — passed as a constructed string to avoid a data→base dependency
# cycle (the deploy role must be able to manage a bucket the data module creates).
data "aws_caller_identity" "current" {}

locals {
  user_space_bucket_name = var.user_space_bucket_name != "" ? var.user_space_bucket_name : "${var.project_name}-prod-user-space"

  # Portal role name computed once and shared like the bucket name: the data
  # module creates the role, and base's deploy policy is scoped to its ARN
  # (constructed string -> no data->base cycle).
  portal_role_name = var.portal_role_name != "" ? var.portal_role_name : "${var.project_name}-portal-user-role"
  portal_role_arn  = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${local.portal_role_name}"

  # Deploy role ARN, constructed the same cycle-free way (base creates the role as
  # "${project_name}-deploy-role"). Passed to the data module so the user-space
  # bucket policy can EXCLUDE the deploy role from its data-access Deny — without
  # this the deploy role can't HeadBucket (s3:ListBucket), tofu refresh sees the
  # bucket as "deleted", and every infra plan proposes a destructive recreate.
  deploy_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-deploy-role"

  # Lambda artifacts bucket name computed once and shared the same cycle-free way:
  # the lambda-artifacts module creates the bucket, and base's deploy policy is
  # scoped to its ARN (constructed string -> no lambda-artifacts->base cycle).
  lambda_artifacts_bucket_name = "${var.project_name}-lambda-artifacts-${data.aws_caller_identity.current.account_id}"
  lambda_artifacts_bucket_arn  = "arn:aws:s3:::${local.lambda_artifacts_bucket_name}"
}

module "app" {
  source = "./modules/app"

  project_name = var.project_name
}

module "base" {
  source = "./modules/base"

  project_name      = var.project_name
  github_repo       = var.github_repo
  state_bucket      = var.state_bucket
  state_lock_table  = var.state_lock_table
  aws_region        = var.aws_region
  static_bucket_arn = module.app.static_assets_bucket_arn

  # Constructed (not module.data outputs) so base has no dependency on data.
  user_space_bucket_arn       = "arn:aws:s3:::${local.user_space_bucket_name}"
  portal_role_arn             = local.portal_role_arn
  lambda_artifacts_bucket_arn = local.lambda_artifacts_bucket_arn
}

module "auth" {
  source = "./modules/auth"

  project_name          = var.project_name
  environment           = var.environment
  app_url               = var.app_url
  cognito_domain_prefix = var.cognito_domain_prefix

  # The deploy role grants itself the cognito-idp permissions (modules/base
  # policies). Without this ordering, Tofu's parallel apply can call
  # CreateUserPool before that grant takes effect, failing with AccessDenied.
  # Force the base policy to settle before any Cognito resource is created.
  depends_on = [module.base]
}

module "data" {
  source = "./modules/data"

  project_name           = var.project_name
  app_url                = var.app_url
  user_space_bucket_name = local.user_space_bucket_name
  portal_role_name       = local.portal_role_name
  deploy_role_arn        = local.deploy_role_arn

  # Identity Pool ID from auth — used as the portal role's trust audience and the
  # pool's authenticated-role binding. Dependency stays one-directional: data -> auth.
  identity_pool_id = module.auth.identity_pool_id

  # Same ordering as auth: the deploy role grants itself the S3 + IAM-role
  # permissions (modules/base policy). Force that grant to settle before the
  # bucket/role are created, or a first apply can hit AccessDenied.
  depends_on = [module.base]
}

module "lambda_artifacts" {
  source = "./modules/lambda-artifacts"

  bucket_name = local.lambda_artifacts_bucket_name

  # Same ordering as auth/data: the deploy role grants itself this bucket's
  # management (modules/base policy). Force that grant to settle before the
  # bucket is created, or a first apply can hit AccessDenied.
  depends_on = [module.base]
}
