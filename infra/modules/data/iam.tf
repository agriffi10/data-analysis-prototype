# ── Portal Role (shared, trust only) ─────────────────────────────────────────
# The single IAM role every authenticated user assumes via the Identity Pool
# (SPEC-011). Trust ONLY — no permission policy is attached here; SPEC-013 adds
# the prefix-scoped S3 policy. Per-user isolation is enforced by the `username`
# principal tag the Identity Pool stamps server-side (auth module), evaluated by
# SPEC-013's policy via ${aws:PrincipalTag/username}. One role for all users.

# IAM propagation guard: this spec grants the deploy role iam:CreateRole/PassRole
# on this role name (modules/base) in the same apply that creates the role. Fresh
# time_sleep (created this apply) absorbs the propagation window — see the bucket
# guard in s3.tf for the full rationale.
resource "time_sleep" "wait_for_portal_role_perms" {
  create_duration = "30s"
}

resource "aws_iam_role" "portal" {
  name = var.portal_role_name

  # Trust the Identity Pool (not the User Pool directly): authenticated identities
  # from this pool may AssumeRoleWithWebIdentity and TagSession (the latter is
  # required for the principal tag mapping to take effect).
  assume_role_policy = templatefile("${path.module}/policies/portal-role-trust.json.tftpl", {
    identity_pool_id = var.identity_pool_id
  })

  depends_on = [time_sleep.wait_for_portal_role_perms]
}

# Bind the portal role as the Identity Pool's authenticated role. The pool ID is
# passed in from the auth module, keeping the dependency one-directional
# (data -> auth) with no cycle.
resource "aws_cognito_identity_pool_roles_attachment" "portal" {
  identity_pool_id = var.identity_pool_id

  roles = {
    authenticated = aws_iam_role.portal.arn
  }
}

# ── Prefix-Scoped Permission Policy (SPEC-013 FR-001, SPEC-016 FR-005) ───────
# Turns on real S3 access: each session may read/write/delete only under its own
# {username}/ prefix, where {username} is the `username` principal tag the Identity
# Pool stamps server-side (SPEC-011) — never asserted by the client. A session
# without the tag matches nothing, so it gets an implicit deny (no access). The
# tag variable is escaped as $${aws:PrincipalTag/username} in the template so
# templatefile() emits it literally instead of interpolating it.
#
# SPEC-016 added the multipart actions for lib-storage uploads:
#   s3:AbortMultipartUpload + s3:ListMultipartUploadParts (object-level, prefix-scoped).
# CreateMultipartUpload / UploadPart / CompleteMultipartUpload need NO separate
# action — they are authorized by the existing s3:PutObject grant.
# s3:ListBucketMultipartUploads is intentionally NOT granted: lib-storage never
# lists in-progress uploads (it tracks parts in memory), and that action does not
# support the s3:prefix condition key, so it cannot be scoped to the user's prefix
# — granting it bucket-wide would leak other users' in-progress upload keys.
#
# SPEC-146 added exactly ONE statement, ReadTheUsernameDirectory: s3:GetObject on
# ${bucket_arn}/_directory/*, and nothing else. Specifically NOT added:
#
#   * No ListBucket widening. UserPrefixList stays conditioned on the caller's own prefix, so
#     `_directory/` is INVISIBLE to the file browser's listing and the file browser therefore
#     needs no change. (The SPA's protectedFolders.ts lists gain `_directory` anyway — those
#     govern the user's own prefix, so the addition is defensive, not load-bearing.)
#   * No PutObject and no DeleteObject under _directory/. A user can read the directory and
#     cannot write to it; the daily builder is the only writer.
#
# The disclosure this creates is intended and accepted, not incidental: the document is
# readable by EVERY authenticated portal user. A username is already the S3 prefix, the
# principal tag and the Glue database name (SPEC-033), it is already visible on every
# shared-space roster (SPEC-075), and a prefix-search feature discloses the set by
# construction. Recorded in docs/decisions.md rather than left implicit here.
#
# SPEC-162 added the SECOND such statement, ReadTheFeatureFlags: s3:GetObject on
# ${bucket_arn}/_config/*, published by .github/workflows/deploy-config.yml. It is the same
# shape as the directory's, for the same reasons, with the same two omissions — no ListBucket
# widening (so `_config/` is invisible to the file browser) and no write of any kind (the
# deploy role is the only writer). The document is advisory in the strongest sense: a feature
# flag is PRESENTATION, never authorization, so turning one off revokes no grant here or
# anywhere else. A reader who treats it as a security boundary has misread it.
#
# The bucket choice is deliberate and is the whole reason this statement is one line: this
# bucket already has a CORS configuration, its host is already in the enforcing CSP
# connect-src, and the portal role is already on the bucket policy's principal allowlist. The
# admin bucket has none of the three. `lambdas/test_feature_flags_config.py` asserts all three
# rather than assuming them, because a broken read here falls back silently to all-on.
#
# ── ArchiveReceiptsAreNotUserWritable (SPEC-168 FR-006) ──────────────────────
# A Deny on PutObject/DeleteObject/AbortMultipartUpload under the user's own `archive/`
# prefix. The receipt is written by the archive execution role and must not be editable,
# forgeable or deletable by the browser: a user who can rewrite a receipt can misreport
# what was archived, to themselves and to anyone they show it to.
#
# It lives HERE, beside the Allow it narrows, rather than in the analytics template where
# the two existing personal denies happen to sit. GetObject and ListBucket are untouched —
# the user can browse the archive folder and download a receipt, which is the whole point
# of the receipt being a plain text file. Denying a WRITE action does not perturb listing.
#
# s3:AbortMultipartUpload IS INCLUDED ON PURPOSE, and it is the part that reads as
# redundant and is not. A Deny on PutObject alone already blocks a multipart upload
# (every part is authorized as PutObject), so nothing can be written either way — but with
# abort left out, a half-started upload cannot be TIDIED, and its orphaned parts sit there
# billed and invisible to every listing until the bucket's abort-incomplete rule catches
# them.
#
# THE UI MIRROR IS OWED AND LANDS IN SPEC-172. An IAM Deny with no UI counterpart produces
# a bare AccessDenied for a rule this application itself authored — exactly what
# `isUndeletableRootFolder` exists to prevent for `athenaresults/`. Nothing gates Upload or
# New folder on the current PREFIX today, so SPEC-172 builds the app's first prefix-based
# write gate for it.
resource "aws_iam_role_policy" "portal_permissions" {
  name = "user-space-access"
  role = aws_iam_role.portal.id

  policy = templatefile("${path.module}/policies/portal-role-permissions.json.tftpl", {
    bucket_arn = aws_s3_bucket.user_space.arn
  })
}
