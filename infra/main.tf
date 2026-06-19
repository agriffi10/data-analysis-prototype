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

  # Analytics names (SPEC-032) computed once: the analytics module creates the
  # workgroup + admin bucket, and base's deploy policy is scoped to the admin
  # bucket ARN (constructed string -> no analytics->base cycle). Overridable via
  # the root workgroup_name / athena_admin_bucket_name variables (S3 names are
  # globally unique).
  athena_workgroup_name    = var.workgroup_name != "" ? var.workgroup_name : "${var.project_name}-prod-portal-wg"
  athena_admin_bucket_name = var.athena_admin_bucket_name != "" ? var.athena_admin_bucket_name : "${var.project_name}-prod-athena-admin"
  athena_admin_bucket_arn  = "arn:aws:s3:::${local.athena_admin_bucket_name}"

  # LF registration role ARN (SPEC-032), constructed cycle-free like the role ARNs
  # above (analytics creates it as "${project_name}-analytics-lf-registration-role").
  # Passed to the data module so the user-space bucket policy can EXCLUDE it from
  # the data-access Deny: Lake Formation assumes THIS role to vend creds for the
  # registered location, so when a user queries a Glue table the read happens as
  # this role — and without the exclusion the bucket policy's explicit Deny blocks
  # its s3:ListBucket/GetObject (an explicit resource-policy deny overrides the
  # role's own identity-policy allow). Apply ordering (data before analytics) means
  # the role may not exist on the first apply, so this MUST be a constructed string,
  # not module.analytics output.
  lf_registration_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-analytics-lf-registration-role"

  # Post-confirmation Lambda exec role ARN (SPEC-033), constructed the same
  # cycle-free way as the portal/deploy roles. The auth module creates this role as
  # "${project_name}-${environment}-post-confirmation-role"; analytics adds it as a
  # Lake Formation admin. It MUST be a constructed string (not module.auth's output)
  # so the value is KNOWN AT PLAN TIME: when it flowed through module.auth's output it
  # was unknown during the apply that creates the role, and an unknown inside the
  # compact() in the LF data-lake settings caused OpenTofu to silently drop the admin
  # change — the role never became an LF admin and provisioning grants failed. Apply
  # ordering (auth -> data -> analytics) still guarantees the role exists first.
  post_confirmation_exec_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.project_name}-${var.environment}-post-confirmation-role"
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
  athena_admin_bucket_arn     = local.athena_admin_bucket_arn
}

module "auth" {
  source = "./modules/auth"

  project_name          = var.project_name
  environment           = var.environment
  app_url               = var.app_url
  cognito_domain_prefix = var.cognito_domain_prefix

  # SPEC-033 post-confirmation Lambda inputs. account_id/region scope the exec
  # role's Glue ARNs; portal_role_arn (constructed, cycle-free) is the LF grant
  # target the Lambda receives via env var.
  aws_region      = var.aws_region
  account_id      = data.aws_caller_identity.current.account_id
  portal_role_arn = local.portal_role_arn

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

  # Excluded from the bucket-policy data-access Deny so Lake Formation (assuming
  # this role) can read the registered location when serving Athena queries.
  lf_registration_role_arn = local.lf_registration_role_arn

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

# Analytics foundation (SPEC-032): shared Athena workgroup + admin-only results
# bucket. Phase 1 is this additive infrastructure; Phase 2 adds Lake Formation
# bootstrap, hybrid-mode registration of the user-space bucket, and the portal
# role's Glue/Athena/LF policy (which will pull in module.data's bucket/role and
# the principal-tag key). Names are computed in locals above and passed in.
module "analytics" {
  source = "./modules/analytics"

  workgroup_name           = local.athena_workgroup_name
  athena_admin_bucket_name = local.athena_admin_bucket_name

  # Phase 2: Lake Formation + portal-role policy inputs. Names/ARNs are computed in
  # locals above (cycle-free constructed strings) so analytics consumes data/base
  # outputs only through these values, never creating a module cycle.
  project_name          = var.project_name
  aws_region            = var.aws_region
  account_id            = data.aws_caller_identity.current.account_id
  user_space_bucket_arn = "arn:aws:s3:::${local.user_space_bucket_name}"
  portal_role_name      = local.portal_role_name
  portal_role_arn       = local.portal_role_arn
  principal_tag_key     = var.principal_tag_key
  deploy_role_arn       = local.deploy_role_arn

  # SPEC-033: the post-confirmation Lambda's exec role, added as a Lake Formation
  # admin so it can issue per-database grants. Constructed string (see locals above)
  # — NOT module.auth's output — so it's known at plan time; otherwise the unknown
  # value broke the compact() in the LF admins list and the grant silently dropped.
  lambda_provisioner_role_arn = local.post_confirmation_exec_role_arn

  # Ordering: base grants the deploy role its Athena/Glue/LF/admin-bucket perms;
  # data creates the user-space bucket + portal role that analytics registers in LF
  # and attaches the analytics policy to. Force both to settle first.
  depends_on = [module.base, module.data]
}
