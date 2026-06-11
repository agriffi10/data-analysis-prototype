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
locals {
  user_space_bucket_name = var.user_space_bucket_name != "" ? var.user_space_bucket_name : "${var.project_name}-prod-user-space"
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

  # Constructed (not module.data output) so base has no dependency on data.
  user_space_bucket_arn = "arn:aws:s3:::${local.user_space_bucket_name}"
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

  # Same ordering as auth: the deploy role grants itself the S3 bucket-management
  # permissions (modules/base policy). Force that grant to settle before the
  # user-space bucket is created, or a first apply can hit AccessDenied.
  depends_on = [module.base]
}
