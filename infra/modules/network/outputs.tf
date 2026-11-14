output "vpc_id" {
  description = "The VPC every platform resource lives in."
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "The subnets the load balancer is placed in, one per availability zone."
  value       = [for subnet in aws_subnet.public : subnet.id]
}

output "private_subnet_ids" {
  description = "The subnets the ECS tasks run in, one per availability zone. No default route reaches the internet from any of them."
  value       = [for subnet in aws_subnet.private : subnet.id]
}

output "private_route_table_ids" {
  description = "The route tables the S3 gateway endpoint is associated with. Exported so a live check can assert the endpoint's association set equals this."
  value       = [for table in aws_route_table.private : table.id]
}

output "task_security_group_id" {
  description = "The SPA container's security group. It holds no rules: every rule names a group from the module that creates the load balancer, and is declared there."
  value       = aws_security_group.task.id
}

output "vpc_endpoint_security_group_id" {
  description = "The interface endpoints' security group — the destination of the task's only egress allowance."
  value       = aws_security_group.endpoints.id
}

output "s3_prefix_list_id" {
  description = "The S3 gateway endpoint's managed prefix list. The task's egress to S3 must be allowed by PREFIX LIST, because a CIDR rule does not match gateway-endpoint traffic."
  value       = aws_vpc_endpoint.s3.prefix_list_id
}

output "dynamodb_prefix_list_id" {
  description = "The DynamoDB gateway endpoint's managed prefix list, which the task's egress to the session store is allowed by."
  value       = aws_vpc_endpoint.dynamodb.prefix_list_id
}
