# ── Module composition ────────────────────────────────────────────────────────
# Infrastructure is grouped into bounded-context modules:
#   app  — SPA hosting: static assets bucket, CloudFront distribution, OAC
#   base — foundation: GitHub Actions OIDC provider and deployment role
#   auth — Cognito: User Pool, SPA app client, Hosted UI domain (SPEC-006)
# Future contexts get their own modules (e.g. data/ for the personal and shared
# S3 buckets) rather than growing resource-type files.

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
}

module "auth" {
  source = "./modules/auth"

  project_name          = var.project_name
  environment           = var.environment
  app_url               = var.app_url
  cognito_domain_prefix = var.cognito_domain_prefix
}
