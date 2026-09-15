# ── User-Space Bucket (Bucket 1) ─────────────────────────────────────────────
# Every user's files under their own username prefix. Isolation is IAM principal tags on the
# shared portal role, not anything in this file. README.md.

# IAM propagation guard, on initial creation only: the deploy role can race its own
# module.base grant and hit a transient AccessDenied.
resource "time_sleep" "wait_for_deploy_policy" {
  create_duration = "30s"
}

# EVERY TOP-LEVEL PREFIX IS A USERNAME, apart from two deliberate exceptions: `_directory/`
# (the username directory) and `_config/` (the feature-flag document). Both are safe because
# CATALOG_IDENTIFIER_RE requires a leading lowercase letter, so neither can ever BE a username.
# ADDING A THIRD MEANS RE-CHECKING THAT PROPERTY AGAINST THE REGEX, NOT AGAINST THIS LIST.
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

# Intentionally OFF: overwrites and deletes are irreversible and guarded only in the UI.
# This is what makes a failure between a copy and a delete unrecoverable. README.md.
resource "aws_s3_bucket_versioning" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  versioning_configuration {
    status = "Disabled"
  }
}

# A browser killed mid-upload leaves in-progress parts that are billable but invisible to
# every listing.
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

# Without this every presigned GET and PUT the browser redeems fails preflight. Origins are
# ADDITIVE — narrowing to one origin makes the other a rollback nobody can exercise.
resource "aws_s3_bucket_cors_configuration" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  cors_rule {
    allowed_methods = ["GET", "PUT"]
    # `localhost` stays, and NOT because of the dev-unauth path: a developer running `npm run dev`
    # against a deployed API still redeems presigned URLs from it.
    #
    # ONE ORIGIN NOW. The CloudFront entry was the rollback and went with the distribution.
    #
    # GET AND PUT ARE THE WHOLE PRESIGNED SURFACE the browser redeems: a presigned GET to
    # download, and a presigned PUT to upload over XMLHttpRequest. HEAD (objectExists,
    # getObjectMetadata, every collision pre-check), DELETE and multipart POST were the
    # browser's own SDK calls and are API routes now. A stale-but-working CORS rule is
    # invisible, so their absence is asserted rather than assumed.
    #
    # `allowed_headers` and `max_age_seconds` are deliberately UNCHANGED: the header set a
    # presigned PUT carries depends on what the signer signed, and a missing entry fails the
    # PREFLIGHT, which the browser reports as a generic network error naming nothing.
    allowed_origins = compact(["http://localhost:5173", var.spa_origin])
    allowed_headers = ["*"]
    # ETag alone. The other three were removed against a grep over apps/portal/src returning
    # ZERO readers of each — a named absent reader, not tidiness. ETag is kept WITHOUT such a
    # grep and deliberately: an exposed header nobody reads costs nothing, while a missing one
    # fails as an opaque browser error at the first upload.
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
}

# ── Bucket Policy — the hand-maintained allowlist ─────────────────────────
#
# ⚠ AN EXPLICIT RESOURCE-POLICY DENY BEATS AN IDENTITY-POLICY ALLOW. A role holding a correct
# identity grant and missing from this list is denied AT RUNTIME, with nothing in the plan to
# warn it — and it reads as a code bug, because the shared-space bucket has no policy so every
# SHARED-space path succeeds while every PERSONAL one fails.
#
# ADD A ROLE HERE IN THE SAME PR THAT CREATES IT, not with the first verb that needs it. The
# LF registration role and the DEPLOY role are both mandatory exclusions — omitting the latter
# makes `tofu refresh` report the bucket deleted and plan a destructive recreate.
#
# Every entry is the role's IAM ARN, NEVER the assumed-role session ARN. README.md.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_policy" "user_space" {
  bucket = aws_s3_bucket.user_space.id

  policy = templatefile("${path.module}/policies/user-space-bucket-policy.json.tftpl", {
    bucket_arn                            = aws_s3_bucket.user_space.arn
    portal_role_arn                       = aws_iam_role.portal.arn
    deploy_role_arn                       = var.deploy_role_arn
    lf_registration_role_arn              = var.lf_registration_role_arn
    shared_space_orchestrator_role_arn    = var.shared_space_orchestrator_role_arn
    notifications_writer_role_arn         = var.notifications_writer_role_arn
    table_builder_execution_role_arn      = var.table_builder_execution_role_arn
    table_share_execution_role_arn        = var.table_share_execution_role_arn
    data_quality_execution_role_arn       = var.data_quality_execution_role_arn
    file_send_execution_role_arn          = var.file_send_execution_role_arn
    archive_execution_role_arn            = var.archive_execution_role_arn
    file_ops_execution_role_arn           = var.file_ops_execution_role_arn
    results_conversion_execution_role_arn = var.results_conversion_execution_role_arn
    user_directory_build_role_arn         = var.user_directory_build_role_arn
    account_id                            = data.aws_caller_identity.current.account_id
  })
}
