output "repository_url" {
  description = "Registry URI CI pushes the SPA image to, tagged by commit sha, and the task definition pulls from."
  value       = aws_ecr_repository.spa.repository_url
}

output "repository_arn" {
  description = "Repository ARN, which the task execution role's pull grant is scoped to."
  value       = aws_ecr_repository.spa.arn
}
