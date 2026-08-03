# ── Table-share Step Function (SPEC-088 FR-001) ──────────────────────────────
# Standard state machine — validate-authorize → inspect-source once per request,
# then a Map over $.recipients running check-target-absent → copy-objects →
# create-table PER RECIPIENT with a per-item Catch (one recipient's failure never
# aborts its siblings — docs/architecture.md Control Planes -> Table Share). The per-step bodies
# are STUBS here (pass-through) — the real logic + the structured recorded-failure
# outcomes land in SPEC-089→092.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on the five verbs + log delivery); the verb Lambdas run under the ONE shared
# execution role. Standard (over Express) keeps per-execution history for debugging
# the multi-step share flow and allows long per-recipient copies.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "table_share" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn  = aws_lambda_function.functions["validate-authorize"].arn
    inspect_source_function_arn      = aws_lambda_function.functions["inspect-source"].arn
    check_target_absent_function_arn = aws_lambda_function.functions["check-target-absent"].arn
    copy_objects_function_arn        = aws_lambda_function.functions["copy-objects"].arn
    create_table_function_arn        = aws_lambda_function.functions["create-table"].arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.orchestrator.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  depends_on = [
    aws_iam_role_policy.sfn,
    aws_cloudwatch_log_group.orchestrator,
  ]
}
