# TEMPORARY, reverted before merge. A pending create in module.base, so this pull request's plan
# is one where every module waiting on module.base would defer its data sources.
resource "terraform_data" "deferral_probe" {
  input = "deferral probe"
}
