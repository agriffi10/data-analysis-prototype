output "repository_url" {
  description = "Registry URI CI pushes the Lambda image to, tagged by commit sha."
  value       = aws_ecr_repository.lambda.repository_url
}

output "repository_name" {
  description = "Repository name, which is what describe-repositories is asked for by name."
  value       = aws_ecr_repository.lambda.name
}

output "repository_arn" {
  description = "Repository ARN, for a consumer that has to grant against it."
  value       = aws_ecr_repository.lambda.arn
}
