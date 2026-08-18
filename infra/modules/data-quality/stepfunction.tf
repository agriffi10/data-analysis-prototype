# ── Data-quality Step Function ─────────────────────────────
# Standard state machine — a linear pipeline AROUND AN ATHENA QUERY:
# validate-authorize → inspect-source → create-temp-tables → start-profile-query →
# [WaitForQuery → CheckQuery → Choice] → byte-scan → assemble-report →
# drop-temp-tables → RecordSuccess → Succeeded.
#
# STANDARD (not Express) is mandatory here, not a preference: a Standard execution runs
# for up to a year, which is what lets the query poll live in the state machine
# (state-machine.asl.json.tftpl, WaitForQuery) instead of inside a 900 s Lambda. It also
# keeps per-execution history for debugging a multi-step check.
#
# The per-step bodies are STUBS here (echo/pass-through) — later specs (SPEC-109→112,
# 114) wire each state to real logic. No later spec adds or renames a state; the
# canonical list is complete in the template.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction on
# the nine verbs + log delivery). Every verb Lambda runs under the ONE shared execution
# role.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "data_quality" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn  = aws_lambda_function.functions["validate-authorize"].arn
    inspect_source_function_arn      = aws_lambda_function.functions["inspect-source"].arn
    create_temp_tables_function_arn  = aws_lambda_function.functions["create-temp-tables"].arn
    start_profile_query_function_arn = aws_lambda_function.functions["start-profile-query"].arn
    check_query_function_arn         = aws_lambda_function.functions["check-query"].arn
    byte_scan_function_arn           = aws_lambda_function.functions["byte-scan"].arn
    assemble_report_function_arn     = aws_lambda_function.functions["assemble-report"].arn
    drop_temp_tables_function_arn    = aws_lambda_function.functions["drop-temp-tables"].arn
    notify_failure_function_arn      = aws_lambda_function.functions["notify-failure"].arn
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
