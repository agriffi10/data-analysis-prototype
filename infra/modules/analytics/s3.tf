# ── Admin-Only Athena Results Bucket ───────────────────────
# The workgroup's default/fallback output location. NO END-USER ACCESS: the portal role is
# never granted anything here. User-facing results live at {username}/athenaresults/ in the
# user-space bucket; this one only ever receives a write when a query omits an explicit
# OutputLocation. README.md.

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

# Versioning OFF, matching every other bucket.
resource "aws_s3_bucket_versioning" "athena_admin" {
  bucket = aws_s3_bucket.athena_admin.id

  versioning_configuration {
    status = "Disabled"
  }
}

# ⚠ `logs/` IS RETAINED INDEFINITELY (user decision, 2026-07-22), and the cost is unbounded
# growth with no ceiling and no decision point.
#
# What makes that safe is STRUCTURAL: every rule below that can EXPIRE something carries a
# prefix filter. S3 LIFECYCLE RULES CAN ONLY INCLUDE A PREFIX, NEVER EXCLUDE ONE, so an
# expiring rule added later with an empty filter would silently begin deleting the logs. The
# `admin_lifecycle_rules_are_prefix_scoped` check pins that. README.md.
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

  # The table-share copy plan. Execution-scoped — read minutes after it is written — so the
  # retention is purely so an operator can inspect the plan of a failed share.
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

  # The file-send copy plan. A SEPARATE rule rather than a widened filter because S3 lifecycle
  # takes ONE PREFIX PER RULE, and a prefix broad enough to cover both ("") would match logs/.
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

  # The archive copy plan, manifest and Map Run results. A separate rule for the same reason.
  #
  # ⚠ `archive/` HERE IS THE ADMIN BUCKET'S CONTROL-PLANE SCRATCH SPACE. It has nothing to do
  # with the `archive/` folder in a user's own space (receipts, never expired) or with the
  # archive BUCKET (7 years). Three unrelated things named `archive/`, in three buckets.
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

  # The file-ops copy plan.
  #
  # ⚠ THE PREFIX CANNOT REACH THIS PLANE'S LOCKS: an S3 lifecycle prefix anchors at the START
  # of the key, so `file-ops/` does not match `locks/file-ops/`. It MUST NOT — that lock is
  # released by OVERWRITING, so an expiry rule reaching it would turn a released lock into a
  # missing one and break the compare-and-set that detects a steal.
  rule {
    id     = "expire-file-ops-plans"
    status = "Enabled"

    filter {
      prefix = "file-ops/"
    }

    expiration {
      days = var.admin_results_retention_days
    }
  }

  # The load balancer's access logs — NOT execution-scoped, and with their own knob: these are
  # the only record of a request that never reached a task.
  #
  # The prefix arrives as a VARIABLE from root, which is also where the module pointing the
  # balancer at it reads the same value — two literals could disagree, and the symptom would be
  # logs that never expire.
  rule {
    id     = "expire-alb-access-logs"
    status = "Enabled"

    filter {
      prefix = "${var.alb_access_log_prefix}/"
    }

    expiration {
      days = var.alb_access_log_retention_days
    }
  }

  # Bucket-wide and deliberately UNFILTERED (CKV_AWS_300) — orphaned parts can appear
  # anywhere, so scoping to today's prefixes would leave a new one unprotected.
  #
  # Unfiltered is safe here in a way an EXPIRATION rule would not be: this carries no
  # `expiration` and can only discard the PARTS of an upload that never completed, so it
  # cannot reach logs/. The check below pins exactly that distinction.
  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# No CORS: the browser never reads this bucket.

# Pins the invariant the logs/ retention decision rests on.
#
# A PLAN WARNING, not a hard failure: OpenTofu cannot fail on this without restructuring the
# lifecycle resource to render its rules via `dynamic`, which is more risk than it is worth on
# a working retention config. The failure mode it guards is a code-review moment. README.md.
check "admin_lifecycle_rules_are_prefix_scoped" {
  assert {
    # Scoped to rules that can DELETE something: a rule with no expiration cannot delete an
    # object at all, so requiring a prefix on it bought nothing and blocked the bucket-wide
    # CKV_AWS_300 rule. An unfiltered EXPIRING rule still fails exactly as before.
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.athena_admin.rule :
      try(one(r.filter).prefix, "") != ""
      if length(r.expiration) > 0 || length(r.noncurrent_version_expiration) > 0
    ])
    error_message = "Every admin-bucket lifecycle rule that EXPIRES objects must carry a non-empty filter.prefix. An unfiltered expiring rule matches logs/ too, which is retained indefinitely — S3 lifecycle can include a prefix but never exclude one. (A rule with no expiration, e.g. abort-incomplete-multipart-upload, is exempt: it cannot delete an object.)"
  }
}
