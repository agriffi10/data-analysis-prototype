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
# raised by `cloudfront:*` actions that could have been scoped and were not — CKV_AWS_355 on
# every one of them and CKV_AWS_290 on the writes among them. SPEC-202
# retired the distribution and the grant, so the list is empty and the gate now blocks on every
# IAM finding. The mechanism stays for the next one: an entry is accepted by check ID AND
# resource — not by check ID — so the same rule firing on any other policy still fails.
#
# A STALE ACCEPT IS A HARD ERROR, same as the .tf enforced list. An acceptance that matches
# no finding either describes something already fixed or points at a resource that has been
# renamed — and in the second case it is silently accepting nothing while reading as an
# acceptance. Both want a deliberate edit.
#
# A NEW IAM DOCUMENT THE PLAN CANNOT SHOW IS A HARD ERROR. A policy naming a resource created in
# the same apply is `(known after apply)`: the plan omits it, and every IAM check Checkov still
# runs on the resource passes without a document to read. Measured against 3.3.9 on a plan
# `tofu show -json` rendered: a role policy granting s3:GetObject on "*" failed CKV_AWS_288 and
# CKV_AWS_355, and the same grant beside a statement naming a queue created in the same apply
# ran two checks, both passed; a trust policy naming a role created in the same apply passed
# CKV_AWS_60, which one open to every principal fails while it is known. It is not
# hypothetical. The results-conversion plane's `pipe` and `sfn` policies were unknown on the pull
# request that added them, so this gate first read them on a later one, which a finding in them
# would have blocked for a cause it did not contain. So the plan the scan read is the third
# argument, and an `aws_iam_*` resource being created or replaced whose `policy` or
# `assume_role_policy` it marks unknown is refused by address.
#
# AN UPDATED ONE IS NAMED, NOT REFUSED, by decision. When the split was chosen, 23 of the 27
# unknown updates over the hundred pull-request plan runs 33009167982 to 34997976131 were the
# observability module's documents, deferred by its `depends_on` with their content unchanged.
# Those are now built without a data source and known at plan, so what an update leaves unknown
# is a real edit: an existing policy gaining a new resource's ARN, or a function a plane replaces
# by design. Refusing those was declined, and the warning says the gate did not read them.
#
# This is PR-only despite living in the deploy workflow: `plan` runs on pull_request, `apply`
# runs on push/dispatch and does not depend on it. Nothing here can redden a production
# deploy. An earlier draft made this a warning on the opposite belief and said so in five
# places; the belief was wrong.
#
# Usage: checkov-plan-iam.sh <checkov-plan-json> <accepted-list-file> <plan-json>
# Prints the unaccepted IAM finding count on stdout. Diagnostics go to stderr.

set -euo pipefail

json="${1:?checkov plan json required}"
accepted_file="${2:?accepted list file required}"
plan="${3:?the rendered plan the scan read is required}"

err() { echo "::error title=Checkov (plan IAM)::$1" >&2; }

[ -f "$json" ] || { err "$json is missing — the scan did not run."; exit 2; }
[ -f "$accepted_file" ] || { err "$accepted_file is missing — that file IS the gate."; exit 2; }
[ -f "$plan" ] || { err "$plan is missing, so a policy unknown until apply cannot be told from one the scan read."; exit 2; }

norm='(if type=="array" then .[0] else . end)'

# The file must hold a Checkov result: a numeric failure count, under `.summary` or, in the bare
# shape Checkov prints when it found nothing to scan, at the top. An EMPTY file holds no JSON
# value, and plain jq reads "no value" as success, so without this a scan that wrote nothing
# (checkov-scan.sh's refusal, or a crash) would narrow to a clean zero.
if ! jq -e "$norm | (.summary.failed // .failed) | numbers" "$json" >/dev/null 2>&1; then
  err "$json holds no Checkov result, so there is nothing to count. The scan did not run, or was refused."
  exit 2
fi

if ! jq -e '.planned_values | objects' "$plan" >/dev/null 2>&1; then
  err "$plan is not a rendered plan, so it cannot say which IAM documents the scan could not read."
  exit 2
fi

# The two documents the IAM checks read, named rather than matched by a suffix. A role that
# configures no `inline_policy` has it marked unknown on create, because the provider computes
# it, so `policy$` refused every new role on a real plan. Checkov does not read `inline_policy`
# at all, known or not. CKV_AWS_274 also reads a `policy_arn`, which is not a document and is
# unknown on every new customer-managed policy's attachment, so it is not refused; the register
# records both. The two named attributes are strings, which a rendered plan lists in
# `after_unknown` only while unknown (measured), so a listed key counts as unknown whatever its
# value. `after_unknown` was an object on every managed resource measured, and one that is not
# is skipped. Managed resources only: a data source read at apply is not a document this change
# writes. A replacement's actions hold "create" beside "delete", in either order, so it is new
# here, as it is to IAM.
if ! unknown=$(jq -r '
    (.resource_changes // [])[]
    | select(.mode == "managed" and ((.type // "") | test("^aws_iam_")))
    | .address as $address
    | (if ((.change.actions // []) | index("create")) then "new" else "updated" end) as $kind
    | (.change.after_unknown // {}) | objects
    | to_entries[] | select(.key == "policy" or .key == "assume_role_policy")
    | "\($kind)\t\($address): its \(.key)"' "$plan"); then
  err "could not read which IAM documents are unknown from $plan — the plan is not readable."
  exit 2
fi
updated=$(printf '%s\n' "$unknown" | awk -F '\t' '$1 == "updated" { print $2 }')
new=$(printf '%s\n' "$unknown" | awk -F '\t' '$1 == "new" { print $2 }')
if [ -n "$updated" ]; then
  while IFS= read -r finding; do
    echo "::warning title=Checkov (plan IAM)::$finding is unknown until apply on an in-place update, so this gate did not read it. It is named rather than refused, by decision: read its change in the plan, because no scanner did." >&2
  done <<< "$updated"
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    {
      echo "**IAM documents this gate did not read**, unknown until apply on an in-place update:"
      echo
      printf '%s\n' "$updated" | sed 's/^/- /'
      echo
    } >> "$GITHUB_STEP_SUMMARY"
  fi
fi
if [ -n "$new" ]; then
  while IFS= read -r finding; do
    err "$finding is unknown until apply on a new resource, so Checkov scored the IAM checks on it without reading it."
  done <<< "$new"
  err "A new document the plan cannot show is one this gate has never read. Build each ARN its Resource names from that resource's name, in a local, so the plan knows it. A Principal must exist when IAM writes the policy, so a role it names needs an explicit dependency on that role, or lands in an earlier pull request, as does a resource whose ARN AWS generates, such as a KMS key or a Cognito pool."
  exit 2
fi

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

# A SKIPPED IAM FINDING IS REFUSED, for the reason checkov-enforced.sh gives: a skip moves the
# finding out of failed_checks, so the count above cannot see it. The scan as the workflow runs
# it records none, because Checkov reads a `.tf` file's `checkov:skip` comments into a plan scan
# only under --repo-root-for-plan-enrichment. Measured against 3.3.9 on the corpus fixture: with
# that flag, a skip beside the plan took CKV_AWS_355 off and this count went from 2 to 1. So the
# gate held only because nobody had added a flag, which nothing checked. Checked before the
# stale accepts, whose message would otherwise blame a fix or a rename.
if ! skipped=$(jq -r "$norm | (.results.skipped_checks // [])[] | select($iam) | .check_id + \" on \" + (.resource // \"\")" "$json"); then
  err "could not read skipped checks from $json — the scan output is not readable."
  exit 2
fi
if [ -n "$skipped" ]; then
  while IFS= read -r finding; do
    err "$finding is SKIPPED — a suppression of an IAM finding is refused, not counted."
  done <<< "$skipped"
  err "Delete the skip. A finding that should be accepted gets a line in $accepted_file, by check ID and resource, where a reviewer reads it as a change to the gate."
  exit 2
fi

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
