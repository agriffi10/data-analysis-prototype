variable "project_name" {
  description = "Short name used as a prefix for AWS resource names"
  type        = string
}

# The four below exist only to build the CSP's connect-src. They are
# passed as constructed strings from root locals, never as module outputs: this
# module is upstream of base -> data, so a module reference would be a cycle.

variable "csp_connect_src" {
  description = "The whole connect-src directive, built at root. It used to be assembled here from four inputs; it moved out because the API's origin has to join it and root is where that origin exists — and because three consumers now need the list where only this module did before."
  type        = string
}
