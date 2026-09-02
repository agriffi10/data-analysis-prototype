# ── Data-quality Step Function ─────────────────────────────
# A linear pipeline AROUND AN ATHENA QUERY.
#
# STANDARD (not Express) IS MANDATORY, not a preference: a Standard execution runs for up to a
# year, which is what lets the query poll live in the state machine rather than inside a 900 s
# Lambda. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "data_quality" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn  = module.functions["validate-authorize"].function_arn
    inspect_source_function_arn      = module.functions["inspect-source"].function_arn
    create_temp_tables_function_arn  = module.functions["create-temp-tables"].function_arn
    start_profile_query_function_arn = module.functions["start-profile-query"].function_arn
    check_query_function_arn         = module.functions["check-query"].function_arn
    byte_scan_function_arn           = module.functions["byte-scan"].function_arn
    assemble_report_function_arn     = module.functions["assemble-report"].function_arn
    drop_temp_tables_function_arn    = module.functions["drop-temp-tables"].function_arn
    notify_failure_function_arn      = module.functions["notify-failure"].function_arn
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
