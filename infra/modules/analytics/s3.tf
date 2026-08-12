# ── Admin-Only Athena Results Bucket (SPEC-032 FR-003) ───────────────────────
# The Athena workgroup's default/fallback output location and a future admin/audit
# store. NO end-user access: the portal role is never granted anything on this
# bucket (FR-006 grants the role only the user-space {username}/athenaresults/
# prefix). Reserved for future admin/audit roles, which are out of scope here.
#
# User-facing query results and history do NOT live here — they go to
# {username}/athenaresults/ in the user-space bucket (SPEC-010), readable by the
# user and delete-protected (FR-006). This bucket only ever receives a write when a
# query omits an explicit OutputLocation (it shouldn't), keeping that data out of
# any user-readable location.
#
# Hygiene mirrors the user-space bucket (data/s3.tf): all public access blocked,
# SSE-S3, BucketOwnerEnforced, versioning off (MVP). Created by the deploy role,
# which holds s3:* on this ARN (modules/base S3AthenaAdminBucketManage, FR-007);
# the time_sleep guard in athena.tf covers both this bucket and the workgroup.

resource "aws_s3_bucket" "athena_admin" {
  bucket = var.athena_admin_bucket_name

  depends_on = [time_sleep.wait_for_deploy_policy]
}

resource "aws_s3_bucket_public_access_block" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Versioning OFF for the MVP (matches the user-space bucket).
resource "aws_s3_bucket_versioning" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Expire admin/fallback output after the retention window. (The user-facing
# athenaresults/ prefix in the user-space bucket has NO expiry — kept indefinitely
# per the SPEC-032 Open Questions decision; this lifecycle applies only here.)
#
# Scoped to the fallback-results/ prefix (SPEC-050 FR-002): the workgroup's fallback
# OutputLocation now writes under fallback-results/ (athena.tf), and the SPEC-050
# shared-spaces/ control-object registry also lives in this bucket. S3 lifecycle
# rules can only INCLUDE a prefix (there is no exclude), so the rule targets only the
# transient fallback output by prefix — registry objects under shared-spaces/ are
# never matched and are retained indefinitely.
#
# SPEC-127 FR-009: `logs/` gets NO rule here — the structured logs are retained indefinitely
# (user decision, 2026-07-22). The cost, stated plainly so it is read here rather than
# discovered on a bill: unbounded growth, with no ceiling and no decision point.
#
# What makes that safe is structural, not conventional: every rule below that can EXPIRE
# something carries a prefix filter, so none of them can match `logs/` by accident. S3 lifecycle
# rules can only INCLUDE a prefix, never exclude one — so an expiring rule added later with an
# empty filter would silently begin deleting the logs. The
# `admin_lifecycle_rules_are_prefix_scoped` check below pins that.
resource "aws_s3_bucket_lifecycle_configuration" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  rule {
    id     = "expire-admin-results"
    status = "Enabled"

    filter {
      prefix = "fallback-results/"
    }

    expiration {
      days = var.admin_results_retention_days
    }
  }

  # The table-share copy plan (the object list inspect-source hands to copy-objects, moved
  # off the Step Functions state because it pushed the Map's payload to 95% of the 256 KB
  # limit). It is EXECUTION-SCOPED — read once, minutes after it is written — so nothing
  # needs it long-term; the retention that remains is purely so an operator can inspect the
  # plan of a failed share. Reuses the same retention as the fallback results rather than
  # introducing a second knob: both are transient control-plane objects in this bucket, and
  # neither matches shared-spaces/, which is the registry and is retained indefinitely.
  rule {
    id     = "expire-table-share-copy-plans"
    status = "Enabled"

    filter {
      prefix = "table-share/"
    }

    expiration {
      days = var.admin_results_retention_days
    }
  }

  # The file-send copy plan (SPEC-165) — the expanded object list inspect-source hands to
  # SPEC-166's manifest builder. Same reasoning as the table-share rule above and the same
  # retention: execution-scoped, read minutes after it is written, kept only so an operator
  # can inspect the plan of a failed send. It is a SEPARATE rule rather than a widened
  # filter because S3 lifecycle takes one prefix per rule, and a prefix broad enough to
  # cover both (`""`) would match `logs/`, which SPEC-127 FR-009 retains indefinitely.
  rule {
    id     = "expire-file-send-copy-plans"
    status = "Enabled"

    filter {
      prefix = "file-send/"
    }

    expiration {
      days = var.admin_results_retention_days
    }
  }

  # The archive copy plan, transfer manifest and Map Run results (SPEC-169) — the expanded
  # object list inspect-source hands to the manifest builder, and the export the collector
  # reads back. Same reasoning as the table-share and file-send rules above and the same
  # retention: execution-scoped, read minutes after it is written, kept only so an operator can
  # inspect the plan of a failed archive.
  #
  # IT IS A SEPARATE RULE FOR THE SAME REASON THE OTHER TWO ARE: S3 lifecycle takes one prefix
  # per rule, and a prefix broad enough to cover all three ("") would match `logs/`, which
  # SPEC-127 FR-009 retains indefinitely. The `archive/` prefix here is the ADMIN bucket's
  # control-plane scratch space and has nothing to do with the `archive/` folder in a user's own
  # space (which holds receipts and is never expired) or with the archive BUCKET (7 years).
  # Three unrelated things named `archive/`, in three buckets, is worth stating once.
  rule {
    id     = "expire-archive-copy-plans"
    status = "Enabled"

    filter {
      prefix = "archive/"
    }

    expiration {
      days = var.admin_results_retention_days
    }
  }

  # Bucket-wide, and deliberately UNFILTERED (CKV_AWS_300). An abandoned multipart upload
  # leaves orphaned parts that are billed and invisible to every listing, anywhere in the
  # bucket — so scoping this to the prefixes we happen to know about today would leave a new
  # prefix silently unprotected.
  #
  # Unfiltered is safe here in a way an expiration rule would NOT be: this rule carries no
  # `expiration`, and abort-incomplete-multipart-upload can only discard the PARTS of an upload
  # that never completed. It cannot delete an object, so it cannot reach `logs/`, which
  # SPEC-127 FR-009 retains indefinitely. The check below now pins exactly that distinction.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# No CORS: this bucket is never read by the browser. User-facing result downloads
# read from the user-space {username}/athenaresults/ prefix instead (SPEC-034).

# SPEC-127 FR-009 — pins the invariant the logs/ retention decision rests on.
#
# `check` surfaces this as a PLAN WARNING, not a hard failure: OpenTofu has no native way to
# fail on it without restructuring the lifecycle resource to render its rules from a local via
# `dynamic`, which is more risk than this is worth on a working retention config. A warning in
# the plan output is enough — the failure mode it guards against (someone adds an unfiltered
# rule and silently starts expiring the logs) is a code-review moment, and this puts the
# evidence in the diff's own plan comment.
check "admin_lifecycle_rules_are_prefix_scoped" {
  assert {
    # Scoped to rules that can DELETE something. The guard exists because an unfiltered
    # expiring rule would reach logs/; a rule with no expiration cannot delete an object at
    # all, so requiring a prefix on it bought nothing and blocked the bucket-wide
    # abort-incomplete-multipart-upload rule above (CKV_AWS_300). Narrowed deliberately, and
    # an unfiltered EXPIRING rule still fails exactly as before.
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.athena_admin.rule :
      try(one(r.filter).prefix, "") != ""
      if length(r.expiration) > 0 || length(r.noncurrent_version_expiration) > 0
    ])
    error_message = "Every admin-bucket lifecycle rule that EXPIRES objects must carry a non-empty filter.prefix. An unfiltered expiring rule matches logs/ too, which SPEC-127 FR-009 retains indefinitely — S3 lifecycle can include a prefix but never exclude one. (A rule with no expiration, e.g. abort-incomplete-multipart-upload, is exempt: it cannot delete an object.)"
  }
}
