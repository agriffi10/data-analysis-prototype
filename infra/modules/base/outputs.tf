output "github_actions_role_arn" {
  description = "IAM role ARN assumed by the GitHub Actions deployment workflows."
  value       = aws_iam_role.github_actions_deploy.arn
}
