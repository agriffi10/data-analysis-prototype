# ── User-Space Bucket (Bucket 1) ─────────────────────────────────────────────
# Holds every user's files under their own username prefix ({username}/...) plus
# their future .config/connections.json. Private; per-user isolation is enforced
# by IAM principal tags on the shared portal role (SPEC-011/013), not by anything
# in this module.
#
# This module is storage only — the bucket and its hygiene config. The portal
# role, its prefix-scoped permission policy, and the bucket policy restricting
# access to that role all arrive in SPEC-011/013.

# IAM propagation guard. The module-level `depends_on = [module.base]` orders the
# API calls so the deploy-role policy (which grants S3 bucket management) is
# written before this module runs — but IAM is eventually consistent, so the
# deploy role using that grant to create the bucket in the same apply can race
# the propagation and hit a transient AccessDenied. This pause closes that window.
# It runs only on initial creation (no delay on later applies).
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "30s"
}

# RESERVED ROOT PREFIX (SPEC-146). This bucket has an invariant worth naming before breaking
# it: EVERY TOP-LEVEL PREFIX IS A USERNAME. `_directory/` is the one deliberate exception — it
# holds the daily username-directory document the browser reads for typeahead suggestions.
#
# It is safe for one specific, mechanical reason: `cpcommon.config.CATALOG_IDENTIFIER_RE`
# requires a leading LOWERCASE LETTER, so `_directory` can never BE a username. The name was
# chosen precisely because it cannot collide, which is also why the builder needs no special
# case to exclude its own output — the same regex that validates a username drops it.
#
# Adding a second exception here means re-checking that property for the new name.
resource "aws_s3_bucket" "user_space" {
  bucket = var.user_space_bucket_name

  # Wait out the IAM propagation window after the deploy policy settles.
  depends_on = [time_sleep.wait_for_deploy_policy]
}

# Block all public access — all four settings on.
resource "aws_s3_bucket_public_access_block" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Default server-side encryption with SSE-S3 (AES256).
resource "aws_s3_bucket_server_side_encryption_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Disable ACLs entirely — the bucket owner owns every object (BucketOwnerEnforced).
resource "aws_s3_bucket_ownership_controls" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning is intentionally OFF for the MVP — no version history or undo. This
# is a deliberate decision: overwrites and deletes are irreversible and the app
# guards them in the UI (see docs/architecture.md Known Constraints). Revisit if
# undo/version history is ever required.
resource "aws_s3_bucket_versioning" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Lifecycle — abort incomplete multipart uploads after 7 days (SPEC-016 FR-006).
# SPEC-016 uploads via the managed lib-storage Upload, which uses multipart above
# the 5 MiB part size. A browser killed mid-upload (or a future cancel) can leave
# in-progress parts that are billable but invisible; this rule sweeps them up.
# This is the first lifecycle rule on the bucket (SPEC-010 deferred them). The
# empty filter applies the rule to the whole bucket. The deploy role already holds
# s3:* on this bucket (modules/base S3UserSpaceBucketManage), so no deploy-role
# change is needed for s3:PutLifecycleConfiguration.
resource "aws_s3_bucket_lifecycle_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CORS — without this, browser SDK calls fail (matches docs/architecture.md).
# Origins always include local dev; the deployed app URL is added once known.
resource "aws_s3_bucket_cors_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = var.app_url != "" ? ["http://localhost:5173", var.app_url] : ["http://localhost:5173"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag", "x-amz-server-side-encryption", "x-amz-request-id", "x-amz-id-2"]
    max_age_seconds = 3000
  }
}

# ── Bucket Policy — defense in depth (SPEC-013 FR-002; deploy-role fix SPEC-016) ─
# Denies S3 *data* actions (object CRUD + ListBucket) to every principal except
# the portal role, the deploy role, and the account root (break-glass). This is
# belt-and-suspenders on top of the role's identity policy: even a misconfigured
# principal can't read or write user data. Bucket *configuration* actions
# (PutBucketPolicy, lifecycle, etc.) are intentionally NOT denied.
#
# The LF registration role MUST also be excluded (SPEC-032): Lake Formation
# assumes it to vend credentials for the registered user-space location, so when a
# user queries a Glue table the S3 read happens AS this role. An explicit Deny in a
# resource policy overrides the role's identity-policy Allow, so without the
# exclusion queries fail with "PERMISSION_DENIED ... s3:ListBucket ... explicit deny
# in a resource-based policy". It's a service role (not user-assumable), so
# excluding it doesn't widen user data access.
#
# The deploy role MUST be excluded: it runs `tofu plan`/`apply`, which calls
# HeadBucket (an s3:ListBucket action) to refresh the bucket. SPEC-013 omitted it,
# so once the policy was live the deploy role got 403 on HeadBucket, tofu refresh
# reported the bucket as "deleted", and every subsequent infra plan proposed a
# destructive recreate. Excluding the deploy role (which already holds s3:* on the
# bucket via its identity policy, and can rewrite any policy anyway) fixes the
# refresh without weakening the model. Human IAM admins remain denied data access.
# Uses aws:PrincipalArn rather than relying on absence of grants.
#
# The exclusion list uses the portal role's IAM ARN (arn:...:role/NAME), NOT the
# assumed-role session ARN: per AWS docs, aws:PrincipalArn for an assumed-role
# request (incl. Cognito AssumeRoleWithWebIdentity) resolves to the role's IAM
# ARN, and the docs say not to use the session ARN as a value here. So users
# (who assume this role via the Identity Pool) are correctly excluded from the
# Deny and can reach their own prefix.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_policy" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  policy = templatefile("${path.module}/policies/user-space-bucket-policy.json.tftpl", {
    bucket_arn                         = aws_s3_bucket.user_space.arn
    portal_role_arn                    = aws_iam_role.portal.arn
    deploy_role_arn                    = var.deploy_role_arn
    lf_registration_role_arn           = var.lf_registration_role_arn
    shared_space_orchestrator_role_arn = var.shared_space_orchestrator_role_arn
    notifications_writer_role_arn      = var.notifications_writer_role_arn
    table_builder_execution_role_arn   = var.table_builder_execution_role_arn
    table_share_execution_role_arn     = var.table_share_execution_role_arn
    data_quality_execution_role_arn    = var.data_quality_execution_role_arn
    file_send_execution_role_arn       = var.file_send_execution_role_arn
    archive_execution_role_arn         = var.archive_execution_role_arn
    user_directory_build_role_arn      = var.user_directory_build_role_arn
    account_id                         = data.aws_caller_identity.current.account_id
  })
}
