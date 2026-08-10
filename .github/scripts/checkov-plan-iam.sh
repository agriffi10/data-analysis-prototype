#!/usr/bin/env bash
#
# The rendered-plan gate's numerator: IAM findings that are not on the accepted list.
#
# SPEC-139 built this scan for one reason — the .tf scan evaluates ZERO IAM checks, because
# the policies are `templatefile()` calls, so a green Checkov said nothing about the
# `${aws:PrincipalTag/username}` isolation model. The plan renders them, and 45x IAM checks
# run against real documents.
#
# WHY THE COUNT IS IAM-ONLY. The plan scan reports the same non-IAM rules the .tf scan does
# (no VPC, no CMK, no X-Ray), all of them already dispositioned in docs/security-baseline.md.
# Gating those twice would make this job fail for reasons that have nothing to do with what
# it exists to check. The full count is still published to the summary.
#
# WHY AN ACCEPT LIST AND NOT A BLANKET BLOCK. Two IAM findings on the deploy role are
# permanent: `cloudfront:CreateDistribution`, `cognito-idp:CreateUserPool`,
# `cognito-identity:CreateIdentityPool` and the Lake Formation account-level actions have no
# resource ARN to name before the resource exists, and no applicable condition key. They are
# accepted by check ID AND resource — not by check ID — so the same rule firing on any other
# policy still fails.
#
# A STALE ACCEPT WARNS, IT DOES NOT FAIL. This runs in the workflow that applies production
# infrastructure, where a hard error over gate bookkeeping would block a deploy for a reason
# unrelated to the deploy. (The .tf scan's enforced list takes the opposite choice, and can:
# it runs on PRs and a weekly schedule, and blocks nothing that ships.) The warning is loud
# and lands in the job summary; the fix is deleting the line.
#
# Usage: checkov-plan-iam.sh <checkov-plan-json> <accepted-list-file>
# Prints the unaccepted IAM finding count on stdout. Diagnostics go to stderr.

set -euo pipefail

json="${1:?checkov plan json required}"
accepted_file="${2:?accepted list file required}"

err() { echo "::error title=Checkov (plan IAM)::$1" >&2; }
warn() { echo "::warning title=Checkov (plan IAM)::$1" >&2; }

[ -f "$json" ] || { err "$json is missing — the scan did not run."; exit 2; }
[ -f "$accepted_file" ] || { err "$accepted_file is missing — that file IS the gate."; exit 2; }

norm='(if type=="array" then .[0] else . end)'
iam='(.resource | test("(^|[.])aws_iam_"))'

accepted=$(sed -e 's/#.*//' "$accepted_file" | awk 'NF >= 2 {print $1 "\t" $2}' | sort -u || true)

# An accept line naming a non-IAM resource would sit in this file doing nothing, because the
# count it modifies is IAM-only. Refuse it rather than let it read as a suppression.
if [ -n "$accepted" ]; then
  while IFS=$'\t' read -r _ resource; do
    case "$resource" in
      *aws_iam_*) ;;
      *) err "accepted entry names a non-IAM resource ($resource). This list only modifies the IAM count; a non-IAM line suppresses nothing."; exit 2 ;;
    esac
  done <<< "$accepted"
fi

if ! iam_failed=$(jq -er "$norm | (.results.failed_checks // []) | map(select($iam)) | map(.check_id + \"\t\" + .resource) | .[]" "$json" 2>/dev/null); then
  iam_failed=""
fi
iam_failed=$(echo "$iam_failed" | grep -v '^$' | sort -u || true)

if [ -n "$accepted" ]; then
  stale=$(comm -23 <(echo "$accepted") <(echo "$iam_failed") || true)
  if [ -n "$stale" ]; then
    while IFS=$'\t' read -r id resource; do
      [ -n "$id" ] || continue
      warn "$id on $resource is accepted but no longer reported — either it was fixed (delete the line) or the resource was renamed (the acceptance is now pointing at nothing)."
    done <<< "$stale"
  fi
fi

if [ -n "$iam_failed" ]; then
  unaccepted=$(comm -13 <(echo "$accepted") <(echo "$iam_failed") || true)
else
  unaccepted=""
fi

count=0
if [ -n "$unaccepted" ]; then
  count=$(echo "$unaccepted" | grep -c . || true)
  while IFS=$'\t' read -r id resource; do
    [ -n "$id" ] || continue
    err "$id on $resource — an IAM finding that is not on the accepted list."
  done <<< "$unaccepted"
fi

total=$(echo "$iam_failed" | grep -c . || true)
echo "IAM findings: $total; accepted: $(echo "$accepted" | grep -c . || true); unaccepted: $count" >&2
echo "$count"
