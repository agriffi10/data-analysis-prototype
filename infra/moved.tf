# ── State migrations for the module refactor ─────────────────────────────────
# These map each resource's old root-level state address to its new module
# address so the refactor is a rename in state, NOT a destroy-and-recreate.
# Safe to delete once every workspace (local + CI) has applied at least once
# after the refactor.

moved {
  from = aws_s3_bucket.static_assets
  to   = module.app.aws_s3_bucket.static_assets
}

moved {
  from = aws_s3_bucket_public_access_block.static_assets
  to   = module.app.aws_s3_bucket_public_access_block.static_assets
}

moved {
  from = aws_s3_bucket_policy.static_assets
  to   = module.app.aws_s3_bucket_policy.static_assets
}

moved {
  from = aws_cloudfront_origin_access_control.static_assets
  to   = module.app.aws_cloudfront_origin_access_control.static_assets
}

moved {
  from = aws_cloudfront_distribution.portal
  to   = module.app.aws_cloudfront_distribution.portal
}

moved {
  from = aws_iam_openid_connect_provider.github_actions
  to   = module.base.aws_iam_openid_connect_provider.github_actions
}

moved {
  from = aws_iam_role.github_actions_deploy
  to   = module.base.aws_iam_role.github_actions_deploy
}

moved {
  from = aws_iam_role_policy.github_actions_deploy
  to   = module.base.aws_iam_role_policy.github_actions_deploy
}
