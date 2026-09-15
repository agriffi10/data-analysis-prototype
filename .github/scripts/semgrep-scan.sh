#!/usr/bin/env bash
#
# Every Semgrep scan's one entry point. Runs `semgrep scan` with the arguments given, writing its
# JSON report to the path named first, and refuses the scan if Semgrep reports that an ignore file
# decided what it covered, or if a SEMGREP_* variable is set where Semgrep could read it.
#
# WHY. Semgrep reads a `.semgrepignore` at the project root and in every directory under it, and
# does not scan a target one of them matches. Measured against 1.172.0 with the Lambdas scan's
# invocation, on a fixture holding one `subprocess` call with `shell=True`: a root `.semgrepignore`
# naming `lambdas/` took the finding count from 1 to 0, and `lambdas/.semgrepignore` naming a
# subdirectory did the same. Semgrep exited 0 with no parse error, which is exactly what a clean
# scan prints. SEMGREP_BASELINE_COMMIT took the same finding off and recorded nothing at all.
#
# WHY REFUSE RATHER THAN IGNORE. The one switch that turns the files off is marked internal, and a
# `.semgrepignore` the scan quietly ignored would read as a suppression while suppressing nothing.
#
# HOW. `--verbose` makes the report list every target Semgrep skipped, with its reason. That is
# Semgrep's own answer about what decided the scan's coverage, so an ignore file in a place this
# script never names is covered too. A skip whose reason names an ignore file is refused. With no
# `.semgrepignore` at the project root, Semgrep applies a built-in list under the same reason, and
# that list skips every `test/` directory. So the repository keeps an empty root `.semgrepignore`,
# the list never applies, and any such skip is a pattern somebody wrote. A report without its skip
# list is refused as unreadable. Semgrep cannot report the variables it reads, so every SEMGREP_*
# name is refused except SEMGREP_VERSION, the workflow's own pin, which is removed from Semgrep's
# environment. semgrep-scan-test.sh plants each of these against the installed Semgrep, ahead of
# the scans, because a release that renamed the skip reason would be silent here.
#
# Usage: semgrep-scan.sh <report.json> <semgrep scan arguments...>
# The wrapper adds `--json --output <report.json> --verbose`; the arguments must not set an output.
# Stdout: Semgrep's own. The report is deleted before anything else, and on every exit but a scan
# that completed and was not refused, so a report left from an earlier run is never read as this
# one, and a caller counting findings fails rather than reading a scan that was refused, failed, or
# stopped the script early. Diagnostics go to stderr.
# Exit: 2 on a refusal, otherwise Semgrep's own status.

set -euo pipefail

err() { echo "::error title=Semgrep (configuration)::$1" >&2; }

[ "$#" -gt 1 ] || { err "usage: semgrep-scan.sh <report.json> <semgrep scan arguments...>. The scan did not run."; exit 2; }
report="$1"
shift
rm -f "$report"
trap 'rm -f "$report"' EXIT

refuse() {
  err "$1"
  exit 2
}

command -v semgrep >/dev/null 2>&1 || refuse "semgrep is not installed. The scan did not run."

set_vars=$(compgen -e | awk '/^SEMGREP_/ && $0 != "SEMGREP_VERSION"' | paste -sd ' ' -)
[ -z "$set_vars" ] \
  || refuse "refusing to scan: ${set_vars} set in the environment. Semgrep reads these without reporting them, and SEMGREP_BASELINE_COMMIT alone removes findings. Unset them. A setting the scan needs belongs on the invocation in the workflow."

rc=0
env -u SEMGREP_VERSION semgrep scan --json --output "$report" --verbose "$@" || rc=$?
[ "$rc" -le 1 ] || exit "$rc"

jq -e '.paths.skipped | type == "array"' "$report" >/dev/null 2>&1 \
  || refuse "the report at ${report} lists no skipped targets, so it cannot show that no ignore file decided what was scanned. Semgrep's report format has changed, or --verbose no longer adds the list. Re-measure this script against the installed version."

ignore_skips='[.paths.skipped[] | select((.reason // "") | tostring | ascii_downcase | contains("ignore"))]'
count=$(jq "$ignore_skips | length" "$report") \
  || refuse "the skip list in ${report} could not be read, so the scan cannot be shown to cover what this command line names."

if [ "$count" -gt 0 ]; then
  jq -r "$ignore_skips | .[:50][] | \"  \(.path) (\(.reason))\"" "$report" >&2 || true
  refuse "refusing the scan: Semgrep skipped ${count} target(s), the first 50 listed above, because an ignore file matched them. A .semgrepignore anywhere in the tree does this, and so does deleting the empty one at the repository root, which brings back Semgrep's built-in list. Delete the pattern. A path the scan must not cover belongs on the invocation in the workflow as --exclude."
fi

trap - EXIT
exit "$rc"
