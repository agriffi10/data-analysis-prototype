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

# ── The standalone functions became building-block calls ─────────────────────
# The user-directory build, the DLQ drain and the log sweep are calls to scheduled-function (the
# sweep leaving module.observability for module.observability_sweep); notifications and feedback
# are calls to queue-consumer at their old addresses, whose queues keep their resource names and
# need no move. Keep these while any state may predate them.

moved {
  from = module.user_directory.aws_iam_role.build
  to   = module.user_directory.aws_iam_role.this
}

moved {
  from = module.user_directory.aws_iam_role_policy.build
  to   = module.user_directory.aws_iam_role_policy.this["build"]
}

moved {
  from = module.user_directory.module.build
  to   = module.user_directory.module.function
}

moved {
  from = module.user_directory.aws_cloudwatch_event_rule.schedule
  to   = module.user_directory.aws_cloudwatch_event_rule.this
}

moved {
  from = module.user_directory.aws_cloudwatch_event_target.schedule
  to   = module.user_directory.aws_cloudwatch_event_target.this
}

moved {
  from = module.user_directory.aws_lambda_permission.schedule
  to   = module.user_directory.aws_lambda_permission.this
}

moved {
  from = module.control_plane_dlq_drain.aws_iam_role.drain
  to   = module.control_plane_dlq_drain.aws_iam_role.this
}

moved {
  from = module.control_plane_dlq_drain.aws_iam_role_policy.drain
  to   = module.control_plane_dlq_drain.aws_iam_role_policy.this["drain"]
}

moved {
  from = module.control_plane_dlq_drain.module.drain
  to   = module.control_plane_dlq_drain.module.function
}

moved {
  from = module.control_plane_dlq_drain.aws_cloudwatch_event_rule.sweep
  to   = module.control_plane_dlq_drain.aws_cloudwatch_event_rule.this
}

moved {
  from = module.control_plane_dlq_drain.aws_cloudwatch_event_target.sweep
  to   = module.control_plane_dlq_drain.aws_cloudwatch_event_target.this
}

moved {
  from = module.control_plane_dlq_drain.aws_lambda_permission.sweep
  to   = module.control_plane_dlq_drain.aws_lambda_permission.this
}

moved {
  from = module.observability.aws_iam_role.sweep
  to   = module.observability_sweep.aws_iam_role.this
}

moved {
  from = module.observability.aws_iam_role_policy.sweep
  to   = module.observability_sweep.aws_iam_role_policy.this["sweep"]
}

moved {
  from = module.observability.aws_iam_role_policy.sweep_producer
  to   = module.observability_sweep.aws_iam_role_policy.this["logs-producer"]
}

moved {
  from = module.observability.module.sweep
  to   = module.observability_sweep.module.function
}

moved {
  from = module.observability.aws_cloudwatch_event_rule.sweep
  to   = module.observability_sweep.aws_cloudwatch_event_rule.this
}

moved {
  from = module.observability.aws_cloudwatch_event_target.sweep
  to   = module.observability_sweep.aws_cloudwatch_event_target.this
}

moved {
  from = module.observability.aws_lambda_permission.sweep
  to   = module.observability_sweep.aws_lambda_permission.this
}

moved {
  from = module.notifications.aws_iam_role.writer
  to   = module.notifications.aws_iam_role.this
}

moved {
  from = module.notifications.aws_iam_role_policy.writer
  to   = module.notifications.aws_iam_role_policy.this
}

moved {
  from = module.notifications.module.writer
  to   = module.notifications.module.function
}

moved {
  from = module.notifications.aws_lambda_event_source_mapping.writer
  to   = module.notifications.aws_lambda_event_source_mapping.this
}

moved {
  from = module.feedback.aws_iam_role.writer
  to   = module.feedback.aws_iam_role.this
}

moved {
  from = module.feedback.aws_iam_role_policy.writer
  to   = module.feedback.aws_iam_role_policy.this
}

moved {
  from = module.feedback.module.writer
  to   = module.feedback.module.function
}

moved {
  from = module.feedback.aws_lambda_event_source_mapping.writer
  to   = module.feedback.aws_lambda_event_source_mapping.this
}

# ── The control planes' deploy grants are one map ──────────────────────────────
# Eight per-plane policies and their attachments became one `for_each` over the map in
# modules/base/iam.tf, and the archive's propagation guard became the guard for every plane.
# Keep them while any state may predate the change.

moved {
  from = module.base.aws_iam_policy.deploy_archive
  to   = module.base.aws_iam_policy.control_plane["archive"]
}

moved {
  from = module.base.aws_iam_policy.deploy_data_quality
  to   = module.base.aws_iam_policy.control_plane["data-quality"]
}

moved {
  from = module.base.aws_iam_policy.deploy_file_ops
  to   = module.base.aws_iam_policy.control_plane["file-ops"]
}

moved {
  from = module.base.aws_iam_policy.deploy_file_send
  to   = module.base.aws_iam_policy.control_plane["file-send"]
}

moved {
  from = module.base.aws_iam_policy.deploy_results_conversion
  to   = module.base.aws_iam_policy.control_plane["results-conversion"]
}

moved {
  from = module.base.aws_iam_policy.deploy_shared_spaces
  to   = module.base.aws_iam_policy.control_plane["shared-space"]
}

moved {
  from = module.base.aws_iam_policy.deploy_table_builder
  to   = module.base.aws_iam_policy.control_plane["table-builder"]
}

moved {
  from = module.base.aws_iam_policy.deploy_table_share
  to   = module.base.aws_iam_policy.control_plane["table-share"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_archive
  to   = module.base.aws_iam_role_policy_attachment.control_plane["archive"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_data_quality
  to   = module.base.aws_iam_role_policy_attachment.control_plane["data-quality"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_file_ops
  to   = module.base.aws_iam_role_policy_attachment.control_plane["file-ops"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_file_send
  to   = module.base.aws_iam_role_policy_attachment.control_plane["file-send"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_results_conversion
  to   = module.base.aws_iam_role_policy_attachment.control_plane["results-conversion"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_shared_spaces
  to   = module.base.aws_iam_role_policy_attachment.control_plane["shared-space"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_table_builder
  to   = module.base.aws_iam_role_policy_attachment.control_plane["table-builder"]
}

moved {
  from = module.base.aws_iam_role_policy_attachment.deploy_table_share
  to   = module.base.aws_iam_role_policy_attachment.control_plane["table-share"]
}

moved {
  from = module.base.time_sleep.wait_for_archive_grant
  to   = module.base.time_sleep.wait_for_plane_grants
}
