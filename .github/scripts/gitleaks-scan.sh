#!/usr/bin/env bash
#
# Every gitleaks scan's one entry point. Runs `gitleaks git` over the repository in the working
# directory, with the flags given and its JSON report written to the path named first, and refuses
# to run it at all if the scan's coverage would be decided anywhere but its command line and its
# defaults: by gitleaks configuration (a `.gitleaks.toml` or `.gitleaksignore` in the repository,
# or GITLEAKS_CONFIG or GITLEAKS_CONFIG_TOML in the environment), or by a git attribute that makes
# `git log -p` show a path's content to gitleaks as binary.
#
# WHY. gitleaks loads a `.gitleaks.toml` from the directory it scans, skips every finding whose
# fingerprint a `.gitleaksignore` there lists, and takes a whole configuration from either
# variable. It also reads the repository through `git log -p`, which prints "Binary files differ"
# instead of the content of any path whose `diff` attribute is unset, as a `-diff` or `binary` line
# in any `.gitattributes` does, for every commit in history. Measured against 8.30.1 with the
# workflow's invocation: on a repository holding two committed credentials, an allowlist in
# `.gitleaks.toml` naming one of their files took the count from 2 to 1, one line in
# `.gitleaksignore` did the same, and the same allowlist from either variable did the same; on one
# holding a single credential, `*.py -diff` or `*.py binary` took it from 1 to 0. Each run exited
# and reported exactly as a scan with that many findings does, and each file sits outside anything
# a reviewer reads as part of the gate.
#
# WHY REFUSE RATHER THAN IGNORE. A suppression the scan was made to ignore would read as one while
# suppressing nothing.
#
# HOW. Both questions go to the tool that answers them, not to a list of places copied from its
# source. Git is asked, with `git check-attr`, which `diff` attribute it gives every path in the
# history `gitleaks git` reads, so every attribute source git consults is covered: a
# `.gitattributes` at any depth, `.git/info/attributes`, and a `core.attributesFile`. Any path it
# reports as unset is refused, a file that is binary anyway included: telling the two apart would
# mean reading every version of the path, and a refusal of a harmless line is loud where a miss is
# silent. Then gitleaks is asked, with the same flags, which configuration it
# would use. At debug level it names its configuration's source and every ignore file it loads,
# all before the line saying which `git log` it runs. The ask adds `--log-opts=--max-count=0` and
# so reads no commit. That matters: at debug level gitleaks prints decoded fragments of what it
# scans, which `--redact` does not cover, so the real scan never runs at that level. Every line
# before the `git log` line must be one this script knows, and one of them must say the default
# configuration is in use, so a discovery place that a version bump adds is refused too. The lines
# are gitleaks's own and pinned with it, and gitleaks-scan-test.sh plants each source against the
# installed binary, ahead of the scan.
#
# The wrapper supplies `git` and the repository `.` itself, and runs only from the repository's
# top level, so the repository git is asked about is the one gitleaks scans, and the paths the
# history names are the paths `git check-attr` reads them as, which is relative to where it runs.
#
# Usage: gitleaks-scan.sh <report.json> <gitleaks executable> [gitleaks git flags...]
# The wrapper adds `--report-format json --report-path <report.json>`; the flags must not set a
# report.
# Stdout: gitleaks's own output. Nothing on a refusal. The report is deleted before anything else,
# so a refused scan leaves none, and one left from an earlier run is never read as this one.
# Diagnostics go to stderr.
# Exit: 2 on a refusal, otherwise gitleaks's own status.

set -euo pipefail

err() { echo "::error title=gitleaks (configuration)::$1" >&2; }

[ "$#" -gt 1 ] || { err "usage: gitleaks-scan.sh <report.json> <gitleaks executable> [gitleaks git flags...]. The scan did not run."; exit 2; }
report="$1"
bin="$2"
shift 2
rm -f "$report"
command -v "$bin" >/dev/null 2>&1 || { err "${bin} is not an executable. The scan did not run."; exit 2; }
prefix=$(git rev-parse --show-prefix 2>/dev/null) && [ -z "$prefix" ] \
  || { err "this runs only from the top level of a git repository, and '$(pwd)' is not one. The history's paths are read relative to where git check-attr runs. The scan did not run."; exit 2; }

ask=$(mktemp -d "${TMPDIR:-/tmp}/gitleaks-scan.XXXXXX")
trap 'rm -rf "$ask"' EXIT

# Every path a commit in the history adds, changes or removes, each once. Renames are listed as a
# removal and an addition so both names are asked about, a superset of what gitleaks reads.
if ! git log --all --full-history --no-renames --format= --name-only -z > "$ask/history" \
    || ! sort -zu "$ask/history" > "$ask/paths" \
    || ! git check-attr -z --stdin diff < "$ask/paths" > "$ask/attributes"; then
  err "git could not report the diff attribute of every path in the history, so the scan cannot be shown to read their content."
  exit 2
fi

# check-attr answers in threes (path, attribute, value). Reading fewer answers than there are paths
# means the answer was misread, and a loop over nothing would find nothing to refuse.
asked=$(tr -cd '\0' < "$ask/paths" | wc -c | tr -d ' ')
answered=0
hidden=()
while IFS= read -r -d '' path && IFS= read -r -d '' _ && IFS= read -r -d '' value; do
  answered=$((answered + 1))
  [ "$value" != unset ] || hidden+=("$path")
done < "$ask/attributes"
if [ "$answered" -ne "$asked" ]; then
  err "git answered for ${answered} of the ${asked} paths in the history, so its attribute report was misread and cannot show that gitleaks sees their content."
  exit 2
fi
if [ "${#hidden[@]}" -gt 0 ]; then
  printf '  %s\n' "${hidden[@]:0:50}" >&2
  err "refusing to scan: git shows gitleaks ${#hidden[@]} path(s), the first 50 listed above, as binary, because an attribute such as '-diff' or 'binary' in a .gitattributes unsets their diff attribute, and gitleaks never reads a path git shows it as binary. Every such path is refused, a file that is binary anyway included, since this does not read their content. Delete the line. If it is there for merging or line endings, say that without '-diff': '-text -merge' in place of 'binary'."
  exit 2
fi

if ! "$bin" git "$@" . --log-opts=--max-count=0 --report-format json --report-path "$ask/report.json" --log-level debug --no-color --no-banner > "$ask/log" 2>&1; then
  err "gitleaks could not report its configuration for these flags, so the scan cannot be shown to use only its defaults."
  exit 2
fi

# Drops each line's first word, the time, which on the first lines keeps a colour code even under
# --no-color; a code anywhere else leaves a line no pattern here matches, which is refused. Prints
# each unknown line ahead of `executing:`; exits 3 when there is no such line, and 4 when the
# default configuration was never named. The scan runs only on an exit of 0 with nothing printed,
# so an awk that failed for any other reason is a refusal too.
rc=0
outside=$(awk '
    { sub(/^[^ ]+ /, "") }
    /^DBG executing: / { ran = 1; exit }
    /^DBG using [^ ]+ regex engine$/ { next }
    /^DBG no gitleaks config found in path [^ ]*\.gitleaks\.toml, using default gitleaks config$/ { dflt = 1; next }
    { print }
    END { if (!ran) exit 3; if (!dflt) exit 4 }' "$ask/log") || rc=$?

if [ "$rc" -eq 3 ]; then
  err "gitleaks printed no 'executing:' line, so where its configuration phase ends cannot be found. Its log format has changed. Re-measure this script against the installed version."
  exit 2
fi
if [ "$rc" -ne 0 ] || [ -n "$outside" ]; then
  err "refusing to scan: gitleaks did not report using only its default configuration. What it reported instead is below. A .gitleaks.toml or .gitleaksignore in the repository, or GITLEAKS_CONFIG or GITLEAKS_CONFIG_TOML in the environment, changes what the gate counts from a place nobody reviews as part of it. Delete the file or unset the variable."
  printf '%s\n' "${outside:-(no line naming a configuration at all)}" >&2
  exit 2
fi

rm -rf "$ask"
trap - EXIT
exec "$bin" git "$@" . --report-format json --report-path "$report"
