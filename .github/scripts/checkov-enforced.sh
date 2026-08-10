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

unevaluated=$(comm -23 <(echo "$enforced") <(echo "$evaluated"))
if [ -n "$unevaluated" ]; then
  err "enforced check(s) evaluated against nothing: $(echo "$unevaluated" | tr '\n' ' ')"
  err "an ID that runs nowhere enforces nothing. Either it is wrong (a typo, or renamed by a scanner bump) or the resources it covered have left the repo. Fix or remove the line deliberately."
  exit 2
fi

ids_json=$(echo "$enforced" | jq -R . | jq -sc .)
count=$(jq -r --argjson ids "$ids_json" \
  "$norm | (.results.failed_checks // []) | map(select(.check_id as \$c | \$ids | index(\$c))) | length" "$json")

if [ "$count" -gt 0 ]; then
  jq -r --argjson ids "$ids_json" \
    "$norm | (.results.failed_checks // []) | map(select(.check_id as \$c | \$ids | index(\$c))) |
     group_by(.check_id)[] | \"::error title=Checkov (enforced)::\(.[0].check_id) failed \(length) time(s), first at \(.[0].resource) — this check is held at zero.\"" "$json" >&2
fi

echo "enforcing $(echo "$enforced" | wc -l | tr -d ' ') check ID(s); $count finding(s) on them" >&2
echo "$count"
