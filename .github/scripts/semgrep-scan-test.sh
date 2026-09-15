#!/usr/bin/env bash
#
# The fixture corpus for semgrep-scan.sh. It runs against the INSTALLED Semgrep, in the job whose
# gate relies on the wrapper, before that job's Semgrep scans.
#
# A refusal is the half of the wrapper that no ordinary run exercises. In CI there is never an
# ignore file to refuse, so a refusal that stopped firing, for instance because a Semgrep release
# renamed the skip reason the wrapper reads, would look exactly like a clean scan. This corpus
# plants each thing the wrapper refuses (a pattern in the root `.semgrepignore`, a nested
# `.semgrepignore`, the root file's absence, and a SEMGREP_* variable) and asserts the REASON: the
# wrapper names what was planted, prints nothing a caller could parse, and leaves no report. Each
# case starts with a stale report at the path, one reading as a clean scan, so "leaves no report"
# means the wrapper removed it. The clean cases assert the other direction. With nothing planted,
# both of the fixture's findings are reported by rule ID, one of them under a test/ directory that
# Semgrep's built-in list would skip, so a wrapper that refused everything, or an empty root file
# that stopped switching the list off, fails here too.
#
# It scans with a local rule rather than the registry's, so it needs no network and its finding
# cannot move with a ruleset update. Every case runs with HOME pointed at an empty directory.
#
# Usage: semgrep-scan-test.sh   (with semgrep on PATH)
# Exit: 0 when every case holds, 1 when any does not, 2 when the corpus could not run.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
scan="$here/semgrep-scan.sh"

command -v semgrep >/dev/null 2>&1 || {
  echo "::error title=Semgrep corpus::semgrep is not installed. The corpus did not run, which is not a pass." >&2
  exit 2
}

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo"
report="$work/report.json"
mkdir -p "$repo/lambdas/plane" "$repo/src/test" "$work/home" "$work/stub"

cat > "$work/rule.yml" <<'EOF'
rules:
  - id: planted-eval
    languages: [python]
    severity: ERROR
    message: A finding the corpus planted and expects to see reported.
    pattern: eval(...)
EOF
printf 'def run(x):\n    return eval(x)\n' > "$repo/lambdas/plane/handler.py"
printf 'def check(x):\n    return eval(x)\n' > "$repo/src/test/helper.py"
printf '# Empty on purpose, as the repository root one is.\n' > "$repo/.semgrepignore"
if ! (cd "$repo" && export HOME="$work/home" GIT_CONFIG_NOSYSTEM=1 \
    && git init -q && git add -A && git -c user.email=corpus@example.invalid -c user.name=corpus commit -qm fixture); then
  echo "::error title=Semgrep corpus::could not build the fixture repository. The corpus did not run, which is not a pass." >&2
  exit 2
fi

failures=0
fail() { echo "::error title=Semgrep corpus::$1" >&2; failures=$((failures + 1)); }

scan_args=(--config "$work/rule.yml" --metrics=off --disable-version-check lambdas src)

# A report from an earlier run that reads as a clean scan: no finding, nothing skipped.
stale='{"results":[],"errors":[],"paths":{"scanned":[],"skipped":[]}}'

# Runs the wrapper from the fixture repository, with HOME and any extra environment given as
# NAME=value words before `--`, after leaving a stale report at the path. Leaves the exit status in
# $rc, stdout in $work/out and stderr in $work/err, and the report, if one is there, at $report.
run() {
  local env=()
  while [ "$1" != "--" ]; do env+=("$1"); shift; done
  shift
  rc=0
  printf '%s' "$stale" > "$report"
  # The `+` form, because bash 3.2 treats an empty array as unset under `set -u`.
  (cd "$repo" && env HOME="$work/home" ${env[@]+"${env[@]}"} "$scan" "$report" "$@") > "$work/out" 2> "$work/err" || rc=$?
}

expect_refusal() {
  local case="$1" needle="$2"
  if [ "$rc" -ne 2 ]; then
    fail "$case: the wrapper exited $rc, not 2. What was planted was not refused."
  elif [ -s "$work/out" ]; then
    fail "$case: the wrapper refused but wrote to stdout."
  elif [ -e "$report" ]; then
    fail "$case: the wrapper refused but left the report behind, which a caller could count as a scan."
  elif ! grep -qF -- "$needle" "$work/err"; then
    fail "$case: the wrapper refused without naming ${needle}. Its reason was: $(head -c 600 "$work/err")"
  else
    echo "ok - $case"
  fi
}

both_found='[.results[] | select(.check_id | endswith("planted-eval")) | .path] | sort == ["lambdas/plane/handler.py", "src/test/helper.py"]'

expect_clean() {
  local case="$1"
  if [ "$rc" -ne 0 ]; then
    fail "$case: the wrapper exited $rc with nothing planted. $(head -c 600 "$work/err")"
  elif ! jq -e "$both_found" "$report" >/dev/null 2>&1; then
    fail "$case: the report does not hold planted-eval on both fixture files, so the fixture no longer proves what a plant hides."
  else
    echo "ok - $case"
  fi
}

# Clean: nothing refused, and both findings reported, including the one under test/ that only an
# existing root .semgrepignore keeps Semgrep's built-in list from skipping.
run -- "${scan_args[@]}"
expect_clean "clean scan reports planted-eval on both files, test/ included"

# The workflow's own pin is the one SEMGREP_* name the wrapper lets through.
run SEMGREP_VERSION=0.0.0 -- "${scan_args[@]}"
expect_clean "SEMGREP_VERSION in the environment is not refused"

# The reported case: a pattern in the root file.
printf 'lambdas/\n' > "$repo/.semgrepignore"
run -- "${scan_args[@]}"
expect_refusal "a pattern in the root .semgrepignore" "lambdas/plane/handler.py (semgrepignore_patterns_match)"
printf '# Empty on purpose, as the repository root one is.\n' > "$repo/.semgrepignore"

# A .semgrepignore in a subdirectory, which Semgrep reads as well.
printf 'plane/\n' > "$repo/lambdas/.semgrepignore"
run -- "${scan_args[@]}"
expect_refusal "a nested .semgrepignore" "lambdas/plane/handler.py (semgrepignore_patterns_match)"
rm "$repo/lambdas/.semgrepignore"

# No root file at all, so Semgrep's built-in list applies and skips the test/ directory.
mv "$repo/.semgrepignore" "$work/root-semgrepignore"
run -- "${scan_args[@]}"
expect_refusal "no root .semgrepignore, so the built-in list applies" "src/test/helper.py (semgrepignore_patterns_match)"
mv "$work/root-semgrepignore" "$repo/.semgrepignore"

# A variable Semgrep reads without reporting it.
run SEMGREP_BASELINE_COMMIT=HEAD -- "${scan_args[@]}"
expect_refusal "SEMGREP_BASELINE_COMMIT in the environment" "SEMGREP_BASELINE_COMMIT set in the environment"

# Semgrep rejects the invocation: its failure comes back as a failure, not as a scan.
run -- "${scan_args[@]}" --no-such-flag
if [ "$rc" -lt 2 ]; then
  fail "an invocation semgrep rejects: the wrapper exited $rc, which a caller reads as a completed scan."
elif [ -e "$report" ]; then
  fail "an invocation semgrep rejects: the stale report is still there, and a caller would count it."
else
  echo "ok - an invocation semgrep rejects fails with semgrep's own status ($rc) and no report"
fi

# The report's format, which is Semgrep's own. A stub stands in for semgrep here because these
# cases are about the wrapper reading a report the installed version does not write. It writes
# the file STUB_REPORT names where the arguments say, nothing when STUB_REPORT is unset, and exits
# with STUB_EXIT, or 0.
cat > "$work/stub/semgrep" <<'EOF'
#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
  if [ "$1" = --output ] && [ -n "${STUB_REPORT+set}" ]; then cp "$STUB_REPORT" "$2"; shift; fi
  shift
done
exit "${STUB_EXIT:-0}"
EOF
chmod +x "$work/stub/semgrep"
stub_report() { printf '%s' "$2" > "$work/stub-$1.json"; }
stub_report no-skip-list '{"results":[],"errors":[],"paths":{"scanned":["lambdas/plane/handler.py"]}}'
stub_report renamed '{"results":[],"errors":[],"paths":{"scanned":[],"skipped":[{"path":"lambdas/plane/handler.py","reason":"ignore_file_matched"}]}}'
stub_report clean-looking "$stale"
# More skips than a pipe holds, so a refusal that printed its list through one would be killed
# by SIGPIPE before it deleted the report.
jq -n '{results: [], errors: [], paths: {scanned: [], skipped: [range(5000) | {path: "lambdas/vendored/f\(.).py", reason: "semgrepignore_patterns_match"}]}}' > "$work/stub-many.json"

run PATH="$work/stub:$PATH" STUB_REPORT="$work/stub-no-skip-list.json" -- "${scan_args[@]}"
expect_refusal "a report with no skip list" "lists no skipped targets"

# Semgrep exits 0 and writes nothing, so the only report there is the stale one.
run PATH="$work/stub:$PATH" -- "${scan_args[@]}"
expect_refusal "a scan that wrote no report of its own" "lists no skipped targets"

# A skip reason with a name the wrapper has never seen is refused if it still says "ignore". A
# rename that dropped the word would instead stop the planted cases above being refused, which
# fails here too.
run PATH="$work/stub:$PATH" STUB_REPORT="$work/stub-renamed.json" -- "${scan_args[@]}"
expect_refusal "a renamed ignore-file reason" "lambdas/plane/handler.py (ignore_file_matched)"

run PATH="$work/stub:$PATH" STUB_REPORT="$work/stub-many.json" -- "${scan_args[@]}"
expect_refusal "five thousand ignored targets" "skipped 5000 target(s)"

# Semgrep writes a clean-looking report and then fails. A failed scan has no count either.
run PATH="$work/stub:$PATH" STUB_REPORT="$work/stub-clean-looking.json" STUB_EXIT=2 -- "${scan_args[@]}"
if [ "$rc" -ne 2 ]; then
  fail "a scan that failed after writing its report: the wrapper exited $rc, not semgrep's own 2."
elif [ -e "$report" ]; then
  fail "a scan that failed after writing its report: the report is still there, and a caller would count it."
else
  echo "ok - a scan that failed after writing its report leaves no report"
fi

if [ "$failures" -gt 0 ]; then
  echo "::error title=Semgrep corpus::$failures case(s) failed. The wrapper's refusal cannot be trusted with this semgrep." >&2
  exit 1
fi
echo "every case held"
