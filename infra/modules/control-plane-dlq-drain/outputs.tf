# ── control-plane-dlq-drain outputs ───────────────────────────────

output "function_name" {
  description = "Name of the drain Lambda — the deploy-lambdas.yml matrix target."
  value       = module.drain.function_name
}

output "role_arn" {
  description = "ARN of the drain's execution role (four DLQ reads + one notifications send + logs, nothing else)."
  value       = aws_iam_role.drain.arn
}

output "drained_queue_names" {
  description = "The request DLQs this drain sweeps (queue name is the last segment of each ARN)."
  value       = [for arn in var.dlq_arns : split(":", arn)[5]]
}

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [module.drain.function_name]
}
