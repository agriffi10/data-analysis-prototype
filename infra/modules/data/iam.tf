# ── Portal Role (shared, trust only) ─────────────────────────────────────────
# The single role every authenticated user's requests act as, assumed by the API on the caller's
# behalf. Isolation is the `username` principal tag the API stamps SERVER-SIDE from the verified
# claim, never asserted by the client. README.md.

# IAM propagation guard: CreateRole/PassRole on this name is granted in the same apply that
# creates the role.
resource "time_sleep" "wait_for_portal_role_perms" {
  create_duration = "30s"
}

# The API's door onto this role, and the only one. It assumes THE SAME ROLE with THE SAME TAGS
# from THE SAME CLAIMS the retired Identity Pool did, which is why no policy anywhere was
# rewritten when the pool went.
#
# BOTH sts:AssumeRole AND sts:TagSession are required, and either alone is a trap: the missing
# one renders, plans, applies and unit-tests green, then fails at runtime naming neither.
#
# STATE THE LIMIT HONESTLY: `sts:TagKeys` constrains which tag KEYS may appear. It does NOT
# constrain their VALUES, and IAM offers no way to. It is a CEILING and not a floor —
# ForAllValues:StringEquals is satisfied by a request carrying a subset of the listed keys, and
# equally by one carrying none at all, SO THIS CANNOT REQUIRE THAT `username` WAS STAMPED. The
# unspoofability argument rests entirely on where the value comes from: a claim of a
# signature-verified ID token. Not on this condition.
# The `Null` condition's value is the STRING "true"; a JSON boolean fails at apply. README.md.
resource "aws_iam_role" "portal" {
  name = var.portal_role_name

  # One statement: the API's execution role, assuming this role on a caller's behalf. The
  # Identity Pool's federated statement went with the pool.
  assume_role_policy = templatefile("${path.module}/policies/portal-role-trust.json.tftpl", {
    api_execution_role_arn = var.api_execution_role_arn

    # Same two variables the function's own environment carries, so the two key sets cannot
    # drift apart by transcription.
    session_tag_keys = jsonencode(concat(
      [var.principal_tag_key],
      [for k in range(1, var.max_shared_memberships + 1) : "shared_space_${k}"]
    ))
  })

  depends_on = [time_sleep.wait_for_portal_role_perms]
}

# ── Prefix-Scoped Permission Policy ───────
# Each session reaches only its own {username}/ prefix; a session WITHOUT the tag matches
# nothing and gets an implicit deny. The tag is escaped as $${aws:PrincipalTag/username} so
# templatefile() emits it literally.
#
# s3:ListBucketMultipartUploads is deliberately NOT granted — it does not support the
# s3:prefix condition key, so granting it would leak other users' in-progress upload keys.
#
# The _directory/ and _config/ statements grant a read and a listing scoped to those two
# prefixes, and NO write. The listing is what lets a missing document read as absent rather
# than denied; the API, not IAM, is what keeps both out of the file browser.
# The archive Deny includes AbortMultipartUpload ON PURPOSE, and THE UI MIRRORS IT — an IAM
# Deny with no UI counterpart is a bare AccessDenied for a rule this app authored. README.md.
resource "aws_iam_role_policy" "portal_permissions" {
  name = "user-space-access"
  role = aws_iam_role.portal.id

  policy = templatefile("${path.module}/policies/portal-role-permissions.json.tftpl", {
    bucket_arn = aws_s3_bucket.user_space.arn
  })
}
