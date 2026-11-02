variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "environment" {
  description = "Deployment environment, part of the bucket's name"
  type        = string
}

variable "spa_host" {
  description = "The portal's hostname, built at root. The distribution's alias and the record's name."
  type        = string
}

variable "route53_zone_id" {
  description = "The zone the alias record goes in. A variable because the deploy role cannot look a zone up."
  type        = string
}

variable "spa_certificate_arn" {
  description = "ACM certificate for spa_host, in us-east-1. Fed from the VALIDATION resource, so the distribution cannot attach a certificate still pending."
  type        = string
}

variable "content_security_policy" {
  description = "The assembled Content-Security-Policy, computed once at root."
  type        = string
}

variable "runtime_config" {
  description = "Every key of the runtime configuration document, computed at root. An empty value reads as unset and is left out of the document."
  type        = map(string)
}
