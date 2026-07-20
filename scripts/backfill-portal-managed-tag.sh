#!/usr/bin/env bash
#
# Backfill the `portal-managed` Lake Formation LF-Tag onto existing Glue databases.
#
# WHY: every user / shared-space database created from now on is tagged by the
# provisioning Lambdas (post_confirmation.py / create_space.py). Databases that
# existed BEFORE that shipped (e.g. `agriffith`) were never tagged, so the
# control-plane execution roles (table-builder / table-share / data-quality) — which
# are granted CREATE_TABLE on the TAG, not per-DB — cannot create tables in them.
# This one-off applies the tag to the databases you name.
#
# NOT here: DATA_LOCATION_ACCESS. That is a per-BUCKET static Terraform grant
# (analytics + shared-spaces lakeformation.tf), not per-DB, so there is nothing to
# backfill for it.
#
# The tag key/value MUST match aws_lakeformation_lf_tag.portal_managed
# (infra/modules/analytics/lakeformation.tf).
#
# REQUIRES credentials that are a Lake Formation data-lake admin (or that hold
# lakeformation:AddLFTagsToResource + grant on the tag). The tofu deploy *role* is an
# admin; the deploy *user* (static keys) is not.
#
# USAGE:
#   ./scripts/backfill-portal-managed-tag.sh <database> [<database> ...]
#   ./scripts/backfill-portal-managed-tag.sh agriffith
#
# You must name every pre-existing DB explicitly (a missed one stays un-taggable by
# the control plane). Enumerate them with:
#   aws glue get-databases --query 'DatabaseList[].Name' --output text
# then tag all: ./scripts/backfill-portal-managed-tag.sh $(aws glue get-databases \
#   --query 'DatabaseList[].Name' --output text)
#
# Idempotent: re-tagging a database with the same value is a no-op.

set -euo pipefail

TAG_KEY="portal-managed"
TAG_VALUE="true"

if [[ $# -eq 0 ]]; then
  echo "usage: $0 <database> [<database> ...]" >&2
  exit 2
fi

count=$#
failures=0

for db in "$@"; do
  resource="{\"Database\":{\"Name\":\"${db}\"}}"
  lftags="[{\"TagKey\":\"${TAG_KEY}\",\"TagValues\":[\"${TAG_VALUE}\"]}]"

  # add-lf-tags-to-resource reports per-tag problems in a Failures array, not via a
  # non-zero exit — so a request that "succeeds" can still have tagged nothing. Both
  # paths (API error, and a non-empty Failures) are treated as a failure for this DB.
  if result="$(aws lakeformation add-lf-tags-to-resource \
    --resource "$resource" \
    --lf-tags "$lftags" \
    --query 'Failures' --output json 2>&1)"; then
    if [[ "$result" == "[]" ]]; then
      echo "ok   - ${db} tagged ${TAG_KEY}=${TAG_VALUE}"
    else
      echo "FAIL - ${db}: ${result}" >&2
      failures=$((failures + 1))
    fi
  else
    echo "FAIL - ${db}: ${result}" >&2
    failures=$((failures + 1))
  fi
done

if [[ $failures -gt 0 ]]; then
  echo "" >&2
  echo "${failures} of ${count} database(s) failed to tag" >&2
  exit 1
fi

echo ""
echo "${count} database(s) tagged"
