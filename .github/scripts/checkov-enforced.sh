#!/usr/bin/env bash
#
# The Checkov gate's numerator: how many findings landed on a check the project has decided
# to hold at zero.
#
# Gating Checkov's TOTAL is not available to us and never will be. The failures are mostly
# "no VPC", "no CMK", "no X-Ray" — deliberate, documented accepts (docs/security-baseline.md).
# Blocking the total would mean suppressing 20-odd rules to enforce the handful that matter,
# and a suppression file that long stops being read.
#
# So the gate runs the other way round: an explicit list of check IDs, every one at zero
# failures when the list was written, held there. That costs no remediation to turn on and
# fails the moment a change reintroduces one — the ratchet-at-the-measured-level shape the
# coverage floors already use (SPEC-150 FR-002) and the mypy baseline now uses too.
#
# AN ENFORCED ID EVALUATED AGAINST NOTHING IS A HARD ERROR. A typo, a check renamed by a
# scanner bump, or a resource class that left the repo all produce one thing: a line that
# enforces nothing while reading as enforcement. That is "did not run is never clean"
# (SPEC-138) turned on the gate's own configuration. The fix is a deliberate edit with a
# reason, never a silent pass.
#
# A FINDING CHECKOV REPORTS SKIPPED ON AN ENFORCED ID IS A HARD ERROR, NOT A COUNT. An inline
# `checkov:skip=<ID>` in the scanned file moves that resource's result into skipped_checks
# while the ID still runs on every other resource, so a count of failures alone reads zero
# and the coverage check above still holds. Measured against 3.3.9: `bridgecrew:skip=` and a
# skip naming the ID's BC_* alias land there too, and a skip on a resource that would have
# PASSED is recorded as skipped, not passed. So a skip is a suppression rather than a
# finding, and counting it would report a misconfiguration that may not exist. It is refused,
# like any suppression that is not on a list the gate names: that list is where a reviewer
# reads a change to the gate, and a comment beside one resource is not. The check reads
# Checkov's own record of what it skipped rather than grepping for the comment, so every
# spelling Checkov honours is covered. It runs before the coverage check, whose message
# would otherwise blame a typo and invite removing the ID when every instance is skipped.
#
# A MODULE THE SCAN COULD NOT READ IS A HARD ERROR. OpenTofu downloads a module whose source is
# not a local path when it initialises, and applies what it declares. Checkov reads one only
# under --download-external-modules, which no scan here passes, and otherwise only warns. A
# review measured a git-sourced module declaring an SSH-open security group pass this gate with
# a count of 0. Checkov's CKV_TF_1 scores every module call whose source does not start with
# `./` or `../`, and returns UNKNOWN, which it records nowhere, for one that does (read from its
# source and measured against 3.3.9), so any CKV_TF_1 result, whether passed, failed or skipped,
# is Checkov's own statement that a module was not read. The ID need not be enforced for this,
# and a skip of it is read too, since a skip would otherwise hide the only record.
#
# The scan JSON must carry passed_checks, so the caller must NOT pass --quiet to checkov —
# the same constraint, for the same reason, that deploy-infra.yml's plan scan already states.
#
# Usage: checkov-enforced.sh <checkov-json> <enforced-list-file>
# Prints the enforced failure count on stdout. Every diagnostic goes to stderr.

set -euo pipefail

json="${1:?checkov json required}"
list="${2:?enforced list file required}"

err() { echo "::error title=Checkov (enforced)::$1" >&2; }

[ -f "$json" ] || { err "$json is missing — the scan did not run."; exit 2; }
[ -f "$list" ] || { err "$list is missing — that file IS the gate."; exit 2; }

norm='(if type=="array" then .[0] else . end)'

enforced=$(sed -e 's/#.*//' "$list" | tr -d '[:blank:]' | grep -E '^CKV[0-9]*_[A-Z]+_[0-9]+$' | sort -u || true)
if [ -z "$enforced" ]; then
  err "$list holds no usable check IDs. A gate enforcing nothing must not read as green."
  exit 2
fi

if ! evaluated=$(jq -er "$norm | [((.results.passed_checks // [])[], (.results.failed_checks // [])[]).check_id] | unique | .[]" "$json" | sort -u); then
  err "could not read check results from $json — the scan did not complete."
  exit 2
fi

# No `-e`, for the reason given at the skipped check below.
if ! remote=$(jq -r "$norm"' | [(.results.passed_checks // [])[], (.results.failed_checks // [])[], (.results.skipped_checks // [])[]]
    | .[] | select(.check_id == "CKV_TF_1")
    | "module \"\(.resource // "?")\" (\(.file_path // "?"), lines \((.file_line_range // []) | map(tostring) | join("-")))"' "$json"); then
  err "could not read module results from $json — the scan output is not readable."
  exit 2
fi
if [ -n "$remote" ]; then
  while IFS= read -r module; do
    err "$module takes its source from outside the checkout, so the scan read none of what it declares."
  done <<< "$remote"
  err "OpenTofu downloads a module that is not called by a local path, and Checkov does not. Copy the module into the repository and call it by a path starting ./ or ../, so the scan reads it."
  exit 2
fi

ids_json=$(echo "$enforced" | jq -R . | jq -sc .)

# No `-e`: with it, jq exits non-zero when nothing is selected, which is the healthy case.
if ! skipped=$(jq -r --argjson ids "$ids_json" "$norm"' | (.results.skipped_checks // [])[]
    | select(.check_id as $c | $ids | index($c))
    | "\(.check_id) on \(.resource // "?") is SKIPPED (\(.file_path // "?"), lines \((.file_line_range // []) | map(tostring) | join("-")))"' "$json"); then
  err "could not read skipped checks from $json — the scan output is not readable."
  exit 2
fi
if [ -n "$skipped" ]; then
  while IFS= read -r finding; do
    err "$finding — a suppression of a check held at zero is refused, not counted."
  done <<< "$skipped"
  err "Checkov records an inline checkov:skip as SKIPPED, which a count of failures cannot see. Delete the skip. If the check should stop being enforced, remove its line from $list deliberately, with a reason."
  exit 2
fi

unevaluated=$(comm -23 <(echo "$enforced") <(echo "$evaluated"))
if [ -n "$unevaluated" ]; then
  err "enforced check(s) evaluated against nothing: $(echo "$unevaluated" | tr '\n' ' ')"
  err "an ID that runs nowhere enforces nothing. Either it is wrong (a typo, or renamed by a scanner bump) or the resources it covered have left the repo. Fix or remove the line deliberately."
  exit 2
fi

count=$(jq -r --argjson ids "$ids_json" \
  "$norm | (.results.failed_checks // []) | map(select(.check_id as \$c | \$ids | index(\$c))) | length" "$json")

if [ "$count" -gt 0 ]; then
  jq -r --argjson ids "$ids_json" \
    "$norm | (.results.failed_checks // []) | map(select(.check_id as \$c | \$ids | index(\$c))) |
     group_by(.check_id)[] | \"::error title=Checkov (enforced)::\(.[0].check_id) failed \(length) time(s), first at \(.[0].resource) — this check is held at zero.\"" "$json" >&2
fi

echo "enforcing $(echo "$enforced" | wc -l | tr -d ' ') check ID(s); $count finding(s) on them" >&2
echo "$count"
