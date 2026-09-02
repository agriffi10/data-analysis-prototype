# ── Outputs ──────────────────────────────────────────────────────────────────
# This module had none: nothing downstream needed a value from it until the fleet's
# membership became a Terraform output.

output "function_names" {
  description = "Every Lambda this module deploys, by deployed name. Aggregated at the root into `lambda_function_names`; the reasoning lives there rather than in fourteen copies of it."
  value       = [module.build.function_name]
}
