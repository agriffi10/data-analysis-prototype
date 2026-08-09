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

  # SPEC-157 FR-004's execution bound is NOT set here: `aws_sfn_state_machine` has no
  # `timeout_seconds` argument (tofu validate rejects it). A Standard machine's timeout is a
  # TOP-LEVEL field of the ASL document, so it is "TimeoutSeconds": 3600 in
  # state-machine.asl.json.tftpl, beside StartAt.
  #
  # Why it exists at all, and why 3600: a Standard execution may otherwise run for a YEAR,
  # which makes "this lock is stale" unjustifiable at any age — so the bound is a
  # PREREQUISITE of the refresh lock, not a tidy-up. Derived from the worst case: every Task
  # retries 3 times over 2/4/8-second intervals, so a state costs 4*timeout + 14 seconds. The
  # refresh path sums to ~2400 s (validate 74, acquire 74, load-definition 74, inspect-source
  # 254, infer-schema 494, diff-schema 74, apply-refresh 1214, release 74, notify 74) and the
  # CREATE path to ~2260 s, so this clears both and adding it cannot fail an ordinary create's
  # Athena polling. tbcommon/table_lock.py mirrors the number as MACHINE_TIMEOUT_SECONDS and
  # derives its steal threshold from it; test_table_lock_timeout.py holds the two equal and
  # recomputes the create-path budget, so raising a verb's timeout fails there rather than in
  # production.

  # An EXPLICIT per-function map, not a loop — so a new ASL state referencing a new
  # function needs its key added HERE or templatefile() fails at PLAN time. Easy to miss
  # precisely because lambda.tf, being for_each over the same map, does not.
  definition = templatefile("${path.module}/state-machine.asl.json.tftpl", {
    validate_authorize_function_arn    = aws_lambda_function.functions["validate-authorize"].arn
    check_table_absent_function_arn    = aws_lambda_function.functions["check-table-absent"].arn
    load_table_definition_function_arn = aws_lambda_function.functions["load-table-definition"].arn
    acquire_refresh_lock_function_arn  = aws_lambda_function.functions["acquire-refresh-lock"].arn
    release_refresh_lock_function_arn  = aws_lambda_function.functions["release-refresh-lock"].arn
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
