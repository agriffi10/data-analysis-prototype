# No spa_origin or spa_host output — both are built at ROOT and passed DOWN. README.md.

output "ecr_repository_url" {
  description = "Registry the image is pushed to. The push is a later spec's; verification pushes the placeholder by hand."
  value       = aws_ecr_repository.spa.repository_url
}

output "ecs_cluster_name" {
  description = "Cluster name, for describe-services during verification and for the deploy that raises the service."
  value       = aws_ecs_cluster.spa.name
}

output "ecs_service_name" {
  description = "Service name, for describe-services and for the update-service the image deploy runs."
  value       = aws_ecs_service.spa.name
}

output "alb_dns_name" {
  description = "The load balancer's own name. Read back in verification to prove the alias record points at THIS balancer rather than at a stale one."
  value       = aws_lb.spa.dns_name
}

output "task_definition_family" {
  description = "Task-definition family the image deploy registers new revisions of."
  value       = aws_ecs_task_definition.spa.family
}
