variable "project_name" {
  description = "Project name prefix for all resource names."
  type        = string
}

variable "environment" {
  description = "Environment segment (prod)."
  type        = string
}

variable "aws_region" {
  description = "AWS region. Also builds the VPC endpoint service names, which are region-qualified."
  type        = string
}

variable "vpc_cidr" {
  description = "The VPC's CIDR block. Split into two /20 public and two /20 private subnets, one pair per availability zone."
  type        = string
}

variable "account_id" {
  description = "AWS account id. Builds the flow-log trust policy's aws:SourceAccount and aws:SourceArn conditions, which guard the confused-deputy problem AWS documents for this role."
  type        = string
}

variable "availability_zone_names" {
  description = "Availability zone names to draw the two subnet pairs from, read at root. Sorted and sliced here, so the caller passes the data source's list unfiltered by order."
  type        = list(string)
}
