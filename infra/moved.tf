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
# `network` and `spa` gained a count, so their state moves to instance [0]. The registry left `spa` for a module of its own, so it is not destroyed with the
# tier, and its two moves are more specific than the module move and win over it. Local plans over
# scratch state of the same shapes showed every resource moved and nothing added or destroyed.
# Keep them while any state may predate the switch.

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

# ── The control planes become calls to modules/control-plane (2026-11-12) ──────────────────
# Every plane keeps its module address, and every verb its `module.<plane>.module.functions[...]`
# address. What moves: each state machine to the module's one name, each TIMED_OUT trio to its
# indexed address, Bucket 5 into module.archive_vault, and shared spaces' storage, transfer reader
# and orchestrator role. Keep these until every state that predates them has applied them.

moved {
  from = module.shared_spaces.aws_sfn_state_machine.orchestrator
  to   = module.shared_spaces.aws_sfn_state_machine.this
}

moved {
  from = module.table_builder.aws_sfn_state_machine.table_builder
  to   = module.table_builder.aws_sfn_state_machine.this
}

moved {
  from = module.table_builder.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.table_builder.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.table_builder.aws_cloudwatch_event_target.execution_timed_out
  to   = module.table_builder.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.table_builder.aws_lambda_permission.execution_timed_out
  to   = module.table_builder.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.table_share.aws_sfn_state_machine.table_share
  to   = module.table_share.aws_sfn_state_machine.this
}

moved {
  from = module.table_share.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.table_share.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.table_share.aws_cloudwatch_event_target.execution_timed_out
  to   = module.table_share.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.table_share.aws_lambda_permission.execution_timed_out
  to   = module.table_share.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.data_quality.aws_sfn_state_machine.data_quality
  to   = module.data_quality.aws_sfn_state_machine.this
}

moved {
  from = module.file_send.aws_sfn_state_machine.file_send
  to   = module.file_send.aws_sfn_state_machine.this
}

moved {
  from = module.file_send.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.file_send.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.file_send.aws_cloudwatch_event_target.execution_timed_out
  to   = module.file_send.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.file_send.aws_lambda_permission.execution_timed_out
  to   = module.file_send.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.archive.aws_sfn_state_machine.archive
  to   = module.archive.aws_sfn_state_machine.this
}

moved {
  from = module.archive.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.archive.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.archive.aws_cloudwatch_event_target.execution_timed_out
  to   = module.archive.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.archive.aws_lambda_permission.execution_timed_out
  to   = module.archive.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.file_ops.aws_sfn_state_machine.file_ops
  to   = module.file_ops.aws_sfn_state_machine.this
}

moved {
  from = module.file_ops.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.file_ops.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.file_ops.aws_cloudwatch_event_target.execution_timed_out
  to   = module.file_ops.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.file_ops.aws_lambda_permission.execution_timed_out
  to   = module.file_ops.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.results_conversion.aws_sfn_state_machine.results_conversion
  to   = module.results_conversion.aws_sfn_state_machine.this
}

moved {
  from = module.results_conversion.aws_cloudwatch_event_rule.execution_timed_out
  to   = module.results_conversion.aws_cloudwatch_event_rule.execution_timed_out[0]
}

moved {
  from = module.results_conversion.aws_cloudwatch_event_target.execution_timed_out
  to   = module.results_conversion.aws_cloudwatch_event_target.execution_timed_out[0]
}

moved {
  from = module.results_conversion.aws_lambda_permission.execution_timed_out
  to   = module.results_conversion.aws_lambda_permission.execution_timed_out[0]
}

moved {
  from = module.archive.aws_s3_bucket.archive
  to   = module.archive_vault.aws_s3_bucket.archive
}

moved {
  from = module.archive.aws_s3_bucket_public_access_block.archive
  to   = module.archive_vault.aws_s3_bucket_public_access_block.archive
}

moved {
  from = module.archive.aws_s3_bucket_server_side_encryption_configuration.archive
  to   = module.archive_vault.aws_s3_bucket_server_side_encryption_configuration.archive
}

moved {
  from = module.archive.aws_s3_bucket_ownership_controls.archive
  to   = module.archive_vault.aws_s3_bucket_ownership_controls.archive
}

moved {
  from = module.archive.aws_s3_bucket_versioning.archive
  to   = module.archive_vault.aws_s3_bucket_versioning.archive
}

moved {
  from = module.archive.aws_s3_bucket_lifecycle_configuration.archive
  to   = module.archive_vault.aws_s3_bucket_lifecycle_configuration.archive
}

moved {
  from = module.archive.aws_s3_bucket_policy.archive
  to   = module.archive_vault.aws_s3_bucket_policy.archive
}

moved {
  from = module.shared_spaces.aws_iam_role.orchestrator
  to   = module.shared_spaces.aws_iam_role.execution
}

moved {
  from = module.shared_spaces.aws_iam_role_policy.orchestrator
  to   = module.shared_spaces.aws_iam_role_policy.execution
}

moved {
  from = module.shared_spaces.aws_s3_bucket.shared_space
  to   = module.shared_space_storage.aws_s3_bucket.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_public_access_block.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_public_access_block.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_server_side_encryption_configuration.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_server_side_encryption_configuration.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_ownership_controls.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_ownership_controls.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_versioning.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_versioning.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_lifecycle_configuration.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_lifecycle_configuration.shared_space
}

moved {
  from = module.shared_spaces.aws_s3_bucket_cors_configuration.shared_space
  to   = module.shared_space_storage.aws_s3_bucket_cors_configuration.shared_space
}

moved {
  from = module.shared_spaces.aws_lakeformation_resource.shared_space
  to   = module.shared_space_storage.aws_lakeformation_resource.shared_space
}

moved {
  from = module.shared_spaces.aws_iam_role.lf_registration
  to   = module.shared_space_storage.aws_iam_role.lf_registration
}

moved {
  from = module.shared_spaces.aws_iam_role_policy.lf_registration
  to   = module.shared_space_storage.aws_iam_role_policy.lf_registration
}

moved {
  from = module.shared_spaces.aws_lakeformation_permissions.portal_shared_location
  to   = module.shared_space_storage.aws_lakeformation_permissions.portal_shared_location
}

moved {
  from = module.shared_spaces.aws_lakeformation_permissions.control_plane_shared_location
  to   = module.shared_space_storage.aws_lakeformation_permissions.control_plane_shared_location
}

moved {
  from = module.shared_spaces.aws_iam_role_policy.portal_shared_space
  to   = module.shared_space_storage.aws_iam_role_policy.portal_shared_space
}

moved {
  from = module.shared_spaces.time_sleep.wait_for_deploy_policy
  to   = module.shared_space_storage.time_sleep.wait_for_deploy_policy
}

moved {
  from = module.shared_spaces.aws_iam_role.transfer_reader
  to   = module.shared_space_transfer_reader.aws_iam_role.this
}

moved {
  from = module.shared_spaces.aws_iam_role_policy.transfer_reader
  to   = module.shared_space_transfer_reader.aws_iam_role_policy.this["transfer-reader"]
}

moved {
  from = module.shared_spaces.module.transfer_reader
  to   = module.shared_space_transfer_reader.module.function
}

moved {
  from = module.shared_spaces.aws_cloudwatch_event_rule.transfer_schedule
  to   = module.shared_space_transfer_reader.aws_cloudwatch_event_rule.this
}

moved {
  from = module.shared_spaces.aws_cloudwatch_event_target.transfer_schedule
  to   = module.shared_space_transfer_reader.aws_cloudwatch_event_target.this
}

moved {
  from = module.shared_spaces.aws_lambda_permission.transfer_schedule
  to   = module.shared_space_transfer_reader.aws_lambda_permission.this
}
