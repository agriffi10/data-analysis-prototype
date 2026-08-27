variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

# The policy string arrives whole. It used to be assembled here from four
# constructed strings, and before that from `csp_connect_src` alone; both are
# gone. The reasoning for the move lives beside the computation at root.

variable "content_security_policy" {
  description = "The assembled Content-Security-Policy header value, computed once at root and shared with the container so both delivery paths emit one policy. Never built here: a local inside this module is unreadable to a root-level check, and this module is deleted when the distribution is retired."
  type        = string
}
