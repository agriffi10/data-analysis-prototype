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
# WHY AN ACCEPT LIST AND NOT A BLANKET BLOCK. It held two findings on the deploy role, both
# raised by write actions on `cloudfront:*` that could have been scoped and were not. SPEC-202
# retired the distribution and the grant, so the list is empty and the gate now blocks on every
# IAM finding. The mechanism stays for the next one: an entry is accepted by check ID AND
# resource — not by check ID — so the same rule firing on any other policy still fails.
#
# A STALE ACCEPT IS A HARD ERROR, same as the .tf enforced list. An acceptance that matches
# no finding either describes something already fixed or points at a resource that has been
# renamed — and in the second case it is silently accepting nothing while reading as an
# acceptance. Both want a deliberate edit.
#
# This is PR-only despite living in the deploy workflow: `plan` runs on pull_request, `apply`
# runs on push/dispatch and does not depend on it. Nothing here can redden a production
# deploy. An earlier draft made this a warning on the opposite belief and said so in five
# places; the belief was wrong.
#
# Usage: checkov-plan-iam.sh <checkov-plan-json> <accepted-list-file>
# Prints the unaccepted IAM finding count on stdout. Diagnostics go to stderr.

set -euo pipefail

json="${1:?checkov plan json required}"
accepted_file="${2:?accepted list file required}"

err() { echo "::error title=Checkov (plan IAM)::$1" >&2; }

[ -f "$json" ] || { err "$json is missing — the scan did not run."; exit 2; }
[ -f "$accepted_file" ] || { err "$accepted_file is missing — that file IS the gate."; exit 2; }

norm='(if type=="array" then .[0] else . end)'
# `.resource // ""` because jq's test() RAISES on null, and a raise aborts the whole filter —
# one malformed finding with no resource would take every real finding down with it and
# report a clean zero.
iam='((.resource // "") | test("(^|[.])aws_iam_"))'

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

# NOT swallowed. An unreadable scan is not an absence of findings, and a `|| true` here would
# make every jq failure look like a clean IAM result.
#
# No `-e`: with it, jq exits non-zero merely because the selection was EMPTY, which is the
# healthy case. Plain jq exits non-zero only when it could not read or evaluate.
if ! raw=$(jq -r "$norm | [(.results.failed_checks // [])[] | select($iam) | .check_id + \"\t\" + (.resource // \"\")] | .[]" "$json"); then
  err "could not read IAM findings from $json — the scan output is not readable."
  exit 2
fi
iam_failed=$(printf '%s\n' "$raw" | grep -v '^$' | sort -u || true)

if [ -n "$accepted" ]; then
  stale=$(comm -23 <(echo "$accepted") <(echo "$iam_failed") || true)
  if [ -n "$stale" ]; then
    while IFS=$'\t' read -r id resource; do
      [ -n "$id" ] || continue
      err "$id on $resource is accepted but no longer reported — either it was fixed (delete the line) or the resource was renamed, in which case the acceptance is covering nothing while reading as an acceptance."
    done <<< "$stale"
    exit 2
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
