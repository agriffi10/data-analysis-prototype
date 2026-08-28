variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

variable "content_security_policy" {
  description = "The assembled Content-Security-Policy header value, computed once at root and shared with the container so both delivery paths emit one policy. Never built here: a local inside this module is unreadable to a root-level check, and this module is deleted when the distribution is retired."
  type        = string
}
