#!/usr/bin/env bash
#
# The fixture corpus for gitleaks-scan.sh. It runs against the INSTALLED gitleaks, in the job whose
# gate relies on the wrapper, before that job's scan.
#
# A refusal is the half of the wrapper that no ordinary run exercises. In CI there is never a
# suppression file to refuse, so a refusal that stopped firing, for instance because a gitleaks
# release stopped logging a file it still reads, would look exactly like a clean scan. This corpus
# plants each source that decides what gitleaks sees: a `.gitleaks.toml` and a `.gitleaksignore` in
# the scanned repository, GITLEAKS_CONFIG and GITLEAKS_CONFIG_TOML in the environment, and a git
# attribute that shows a path to gitleaks as binary, from a root `.gitattributes`, a nested one,
# `.git/info/attributes`, and one naming a path only the history still holds. It asserts the
# REASON: the refusal quotes the line gitleaks printed about that source, or names the path git
# hides, prints nothing to stdout, and leaves no report. Each case starts with a stale report at the
# path, one reading as a clean scan, so "leaves no report" means the wrapper removed it, and with a
# temporary directory of its own, which the wrapper must leave empty. A scan started below the
# repository's top level is refused, since git would read the history's paths there as other
# paths and find no attribute on any of them. The clean
# cases assert the other direction. With nothing planted, and with a `.gitattributes` holding only
# a harmless diff driver, both fixture credentials are reported by rule ID and the real scan prints
# no debug line, so a wrapper that refused everything, or ran the scan at the level that prints what
# it decodes, fails here too.
#
# The fixture's credentials are assembled when the corpus runs, because this file is in the history
# the real scan reads.
#
# Usage: gitleaks-scan-test.sh <gitleaks executable>
# Exit: 0 when every case holds, 1 when any does not, 2 when the corpus could not run.

set -uo pipefail

here=$(cd "$(dirname "$0")" && pwd)
scan="$here/gitleaks-scan.sh"

[ "$#" -eq 1 ] && [ -x "$1" ] || {
  echo "::error title=gitleaks corpus::usage: gitleaks-scan-test.sh <gitleaks executable>, and it must exist. The corpus did not run, which is not a pass." >&2
  exit 2
}
bin="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
real_git=$(command -v git)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
repo="$work/repo"
report="$work/report.json"
mkdir -p "$repo/lambdas" "$work/home" "$work/stub" "$work/stub-git"

# Two credentials in the first commit; the second commit deletes one, so only the history holds it.
head_part=AKIA
printf 'aws_id = "%s%s"\n' "$head_part" Q7ZK3M5PX2WR4TLN > "$repo/lambdas/config.py"
printf 'aws_id = "%s%s"\n' "$head_part" R4TLNQ7ZK3M5PX2W > "$repo/lambdas/old.py"
if ! (cd "$repo" && export HOME="$work/home" GIT_CONFIG_NOSYSTEM=1 \
    && git init -q && git add -A && git -c user.email=corpus@example.invalid -c user.name=corpus commit -qm fixture \
    && git rm -q lambdas/old.py && git -c user.email=corpus@example.invalid -c user.name=corpus commit -qm removal); then
  echo "::error title=gitleaks corpus::could not build the fixture repository. The corpus did not run, which is not a pass." >&2
  exit 2
fi
cat > "$work/allow.toml" <<'EOF'
[extend]
useDefault = true

[allowlist]
paths = ['''lambdas/config\.py''']
EOF

failures=0
fail() { echo "::error title=gitleaks corpus::$1" >&2; failures=$((failures + 1)); }

# Runs the wrapper from $run_dir, the fixture repository unless a case says otherwise, after
# leaving a stale report that reads as a clean scan at the path, with any extra environment given
# as NAME=value words before `--` and the executable and its flags after it. TMPDIR is a directory
# of its own, so a case can see what the wrapper left there. Leaves the exit status in $rc, stdout
# in $work/out and stderr in $work/err.
run_dir="$repo"
run() {
  local env=()
  while [ "$1" != "--" ]; do env+=("$1"); shift; done
  shift
  rc=0
  printf '[]' > "$report"
  rm -rf "$work/tmp" && mkdir "$work/tmp"
  # The `+` form, because bash 3.2 treats an empty array as unset under `set -u`.
  (cd "$run_dir" && env HOME="$work/home" GIT_CONFIG_NOSYSTEM=1 TMPDIR="$work/tmp" ${env[@]+"${env[@]}"} "$scan" "$report" "$@") > "$work/out" 2> "$work/err" || rc=$?
}

left_behind() { ls -A "$work/tmp"; }

expect_refusal() {
  local case="$1" needle="$2"
  if [ -n "$(left_behind)" ]; then
    fail "$case: the wrapper left $(left_behind) in its temporary directory."
  elif [ "$rc" -ne 2 ]; then
    fail "$case: the wrapper exited $rc, not 2. The planted configuration was not refused."
  elif [ -s "$work/out" ]; then
    fail "$case: the wrapper refused but wrote to stdout."
  elif [ -e "$report" ]; then
    fail "$case: the wrapper refused but a report is still at the path, which a caller could count."
  elif ! grep -qF -- "$needle" "$work/err"; then
    fail "$case: the wrapper refused without quoting '${needle}'. Its reason was: $(head -c 600 "$work/err")"
  else
    echo "ok - $case"
  fi
}

both_found='[.[] | select(.RuleID == "aws-access-token") | .File] | sort == ["lambdas/config.py", "lambdas/old.py"]'

expect_clean() {
  local case="$1"
  if [ -n "$(left_behind)" ]; then
    fail "$case: the wrapper left $(left_behind) in its temporary directory, which the scan it hands over to cannot remove."
  elif [ "$rc" -ne 1 ]; then
    fail "$case: the wrapper exited $rc, where gitleaks exits 1 on a finding. $(head -c 600 "$work/err")"
  elif ! jq -e "$both_found" "$report" >/dev/null 2>&1; then
    fail "$case: aws-access-token was not reported in both fixture files, so the fixture no longer proves what a plant hides."
  elif grep -q ' DBG ' "$work/err"; then
    fail "$case: the scan printed debug lines, and at that level gitleaks prints decoded fragments of what it scans, which --redact does not cover."
  else
    echo "ok - $case"
  fi
}

# Clean: no refusal, both credentials reported by rule ID, and not one debug line from the scan.
run -- "$bin" --redact
expect_clean "clean scan reports aws-access-token in both files, at gitleaks's own log level"
fingerprint=$(jq -r '[.[] | select(.File == "lambdas/config.py")][0].Fingerprint // empty' "$report" 2>/dev/null)
[ -n "$fingerprint" ] || { echo "::error title=gitleaks corpus::the clean scan left no fingerprint to plant. The corpus did not run, which is not a pass." >&2; exit 2; }

# An attribute that changes nothing gitleaks reads is not refused.
printf '*.py diff=python\n' > "$repo/.gitattributes"
run -- "$bin" --redact
expect_clean "a .gitattributes naming only a diff driver is not refused"
rm "$repo/.gitattributes"

# A config in the scanned repository, allowlisting the file that holds the credential.
cp "$work/allow.toml" "$repo/.gitleaks.toml"
run -- "$bin" --redact
# shellcheck disable=SC2016 # the backticks are in gitleaks's own line, matched literally
expect_refusal "a .gitleaks.toml in the repository" 'from `(--source)/.gitleaks.toml`'
rm "$repo/.gitleaks.toml"

# The credential's fingerprint in a .gitleaksignore.
printf '%s\n' "$fingerprint" > "$repo/.gitleaksignore"
run -- "$bin" --redact
expect_refusal "a .gitleaksignore in the repository" "found .gitleaksignore file"
rm "$repo/.gitleaksignore"

# The same allowlist from each variable gitleaks reads.
run GITLEAKS_CONFIG="$work/allow.toml" -- "$bin" --redact
expect_refusal "GITLEAKS_CONFIG in the environment" "using gitleaks config from GITLEAKS_CONFIG env var"
run GITLEAKS_CONFIG_TOML="$(cat "$work/allow.toml")" -- "$bin" --redact
expect_refusal "GITLEAKS_CONFIG_TOML in the environment" "using gitleaks config from GITLEAKS_CONFIG_TOML env var"

# Each attribute source git reads, each hiding one credential from `git log -p`. The needle is the
# hidden path as the refusal lists it, which the refusal's own wording never contains.
printf 'lambdas/config.py -diff\n' > "$repo/.gitattributes"
run -- "$bin" --redact
expect_refusal "a -diff line in the root .gitattributes" "  lambdas/config.py"
rm "$repo/.gitattributes"

printf 'config.py binary\n' > "$repo/lambdas/.gitattributes"
run -- "$bin" --redact
expect_refusal "a binary line in a nested .gitattributes" "  lambdas/config.py"
rm "$repo/lambdas/.gitattributes"

printf 'lambdas/old.py -diff\n' > "$repo/.gitattributes"
run -- "$bin" --redact
expect_refusal "an attribute on a path only the history holds" "  lambdas/old.py"
rm "$repo/.gitattributes"

printf '*.py -diff\n' > "$repo/.git/info/attributes"
run -- "$bin" --redact
expect_refusal "a -diff line in .git/info/attributes" "  lambdas/config.py"
rm "$repo/.git/info/attributes"

# From a subdirectory, git check-attr would read the history's paths relative to it and find no
# attribute on any of them, so the wrapper runs from the top level or not at all.
printf 'lambdas/config.py -diff\n' > "$repo/.gitattributes"
run_dir="$repo/lambdas"
run -- "$bin" --redact
expect_refusal "a scan started below the repository's top level" "runs only from the top level of a git repository"
run_dir="$repo"
rm "$repo/.gitattributes"

# gitleaks rejects the ask.
run -- "$bin" --redact --no-such-flag
expect_refusal "an invocation gitleaks rejects" "could not report its configuration"

# git's attribute report, which is git's own. A stub stands in for git's check-attr here because
# this case is about the wrapper reading an answer the installed git does not give.
cat > "$work/stub-git/git" <<EOF
#!/usr/bin/env bash
if [ "\$1" = check-attr ]; then cat > /dev/null; printf 'not the -z format\n'; exit 0; fi
exec "$real_git" "\$@"
EOF
chmod +x "$work/stub-git/git"
run PATH="$work/stub-git:$PATH" -- "$bin" --redact
expect_refusal "an attribute report the wrapper cannot read" "git answered for 0 of the"

# The log's format, which is gitleaks's own. A stub stands in for gitleaks here because these
# cases are about the wrapper reading lines the installed version does not print.
cat > "$work/stub/gitleaks" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$STUB_LOG" >&2
EOF
chmod +x "$work/stub/gitleaks"
engine='10:03AM DBG using github.com/wasilibs/go-re2 regex engine'
default='10:03AM DBG no gitleaks config found in path .gitleaks.toml, using default gitleaks config'
executing='10:03AM DBG executing: /usr/bin/git -C . log -p -U0 --max-count=0'

# A line naming a source the wrapper has never seen is refused, so a discovery place a release
# adds cannot pass as the default.
run STUB_LOG="$engine"$'\n'"$default"$'\n''10:03AM DBG found .gitleaksbaseline file path=.gitleaksbaseline'$'\n'"$executing" -- "$work/stub/gitleaks" --redact
expect_refusal "a configuration line the wrapper does not know" "DBG found .gitleaksbaseline file path=.gitleaksbaseline"

run STUB_LOG="$engine"$'\n'"$executing" -- "$work/stub/gitleaks" --redact
expect_refusal "a log that never names the default configuration" "(no line naming a configuration at all)"

run STUB_LOG="$engine"$'\n'"$default" -- "$work/stub/gitleaks" --redact
expect_refusal "a log with no 'executing:' line" "printed no 'executing:' line"

if [ "$failures" -gt 0 ]; then
  echo "::error title=gitleaks corpus::$failures case(s) failed. The wrapper's refusal cannot be trusted with this gitleaks." >&2
  exit 1
fi
echo "every case held"
