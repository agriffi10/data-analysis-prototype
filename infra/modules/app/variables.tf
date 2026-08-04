variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

# The four below exist only to build the CSP's connect-src (SPEC-140). They are
# passed as constructed strings from root locals, never as module outputs: this
# module is upstream of base -> data, so a module reference would be a cycle.

variable "aws_region" {
  description = "AWS region, used to build the AWS service endpoints the CSP's connect-src allows"
  type        = string
}

variable "user_space_bucket_name" {
  description = "Bucket 1 name. CSP connect-src must allow its S3 endpoint or every file operation is blocked."
  type        = string
}

variable "shared_space_bucket_name" {
  description = "Bucket 2 name. CSP connect-src must allow its S3 endpoint or shared-space reads are blocked."
  type        = string
}

variable "cognito_hosted_ui_domain" {
  description = "Fully-qualified Hosted UI domain (no scheme). CSP connect-src must allow it or the OAuth token exchange is blocked and sign-in can never complete."
  type        = string
}
