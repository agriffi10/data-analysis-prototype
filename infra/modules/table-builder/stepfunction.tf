# ── Table-builder Step Function ────────────────────────────
# Standard, TWO branches over one shared spine. Each Task retries only transient Lambda
# SERVICE errors; a shared Catch routes any failure to the terminal Fail state.
# Standard over Express keeps per-execution history. README.md.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "table_builder" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  # The execution bound is NOT settable here — aws_sfn_state_machine has no
  # `timeout_seconds` and tofu validate rejects it. It is a TOP-LEVEL ASL field, so
  # "TimeoutSeconds": 3600 lives in the template beside StartAt. It is a PREREQUISITE of the
  # refresh lock rather than tidy-up, and test_table_lock_timeout.py recomputes it. README.md.

  # An EXPLICIT per-function map, NOT a loop — a new ASL state referencing a new function
  # needs its key added HERE or templatefile() fails at PLAN. Easy to miss precisely because
  # lambda.tf, being for_each over the same map, does not.
  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn    = module.functions["validate-authorize"].function_arn
    check_table_absent_function_arn    = module.functions["check-table-absent"].function_arn
    load_table_definition_function_arn = module.functions["load-table-definition"].function_arn
    acquire_refresh_lock_function_arn  = module.functions["acquire-refresh-lock"].function_arn
    release_refresh_lock_function_arn  = module.functions["release-refresh-lock"].function_arn
    inspect_source_function_arn        = module.functions["inspect-source"].function_arn
    infer_schema_function_arn          = module.functions["infer-schema"].function_arn
    diff_schema_function_arn           = module.functions["diff-schema"].function_arn
    apply_refresh_function_arn         = module.functions["apply-refresh"].function_arn
    execute_ddl_function_arn           = module.functions["execute-ddl"].function_arn
    notify_failure_function_arn        = module.functions["notify-failure"].function_arn
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
