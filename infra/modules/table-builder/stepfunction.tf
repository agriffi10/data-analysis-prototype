# ── Table-builder Step Function (SPEC-066 FR-001) ────────────────────────────
# Standard state machine — TWO branches over one shared spine since SPEC-143:
# validate-authorize → {check-table-absent | load-table-definition} → inspect-source →
# infer-schema → {execute-ddl → Succeed | the refresh tail}. Each Task retries only transient Lambda
# SERVICE errors; a shared Catch routes any failure to the terminal Fail state. The
# per-step bodies are STUBS here (echo/pass-through) — the real logic + the structured
# recorded-failure outcome land in SPEC-067→070.
#
# The state machine runs under its OWN role (iam.tf, sfn-permissions: InvokeFunction
# on every verb + log delivery). Each verb Lambda runs under its OWN per-verb
# role. Standard (over Express) keeps per-execution history for debugging the
# multi-step provisioning flow.

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = local.sfn_log_group_name
  retention_in_days = 14
}

resource "aws_sfn_state_machine" "table_builder" {
  name     = local.state_machine_name
  role_arn = aws_iam_role.sfn.arn
  type     = "STANDARD"

  # An EXPLICIT per-function map, not a loop — so a new ASL state referencing a new
  # function needs its key added HERE or templatefile() fails at PLAN time. Easy to miss
  # precisely because lambda.tf, being for_each over the same map, does not.
  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn    = aws_lambda_function.functions["validate-authorize"].arn
    check_table_absent_function_arn    = aws_lambda_function.functions["check-table-absent"].arn
    load_table_definition_function_arn = aws_lambda_function.functions["load-table-definition"].arn
    inspect_source_function_arn        = aws_lambda_function.functions["inspect-source"].arn
    infer_schema_function_arn          = aws_lambda_function.functions["infer-schema"].arn
    diff_schema_function_arn           = aws_lambda_function.functions["diff-schema"].arn
    apply_refresh_function_arn         = aws_lambda_function.functions["apply-refresh"].arn
    execute_ddl_function_arn           = aws_lambda_function.functions["execute-ddl"].arn
    notify_failure_function_arn        = aws_lambda_function.functions["notify-failure"].arn
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
