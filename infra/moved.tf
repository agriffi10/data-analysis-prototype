# ── State migrations for the module refactor ─────────────────────────────────
# These map each resource's old root-level state address to its new module
# address so the refactor is a rename in state, NOT a destroy-and-recreate.
# Safe to delete once every workspace (local + CI) has applied at least once
# after the refactor.

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

# ── The web tier's off switch ─────────────────────────────────────────────────
# `network` and `spa` gained a count, so their state moves to instance [0], and so does the SPA's
# certificate and its validation; the registry left `spa` for a module of its own, so it is not
# destroyed with the tier. The certificate's validation records keep their domain-name keys. The two resource moves are more
# specific than the module move and win over it, which a local plan over scratch state of the
# same shape showed: every resource moved, nothing added or destroyed. Keep them while any state
# may predate the switch.

moved {
  from = module.network
  to   = module.network[0]
}

moved {
  from = module.spa
  to   = module.spa[0]
}

moved {
  from = module.spa.aws_ecr_repository.spa
  to   = module.spa_image.aws_ecr_repository.spa
}

moved {
  from = module.spa.aws_ecr_lifecycle_policy.spa
  to   = module.spa_image.aws_ecr_lifecycle_policy.spa
}

moved {
  from = aws_acm_certificate.spa
  to   = aws_acm_certificate.spa[0]
}

moved {
  from = aws_acm_certificate_validation.spa
  to   = aws_acm_certificate_validation.spa[0]
}
