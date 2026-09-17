#!/usr/bin/env bash
# The supervisor's watch: a normalised snapshot of the PR queue, open PRs, main's push-run verdict,
# where sessions' work meets, and sessions that look ready to archive, printed as the lines that
# appeared (+) or disappeared (-) since the previous snapshot.
#
# Two modes, because the harness offers two ways to be woken:
#   --until-change  (default) exit on the first change. Run it with Bash run_in_background and
#                   relaunch after handling each event; a quiet night costs no wake-ups.
#   --stream        print every change and never exit, for the Monitor tool (which it outlives
#                   by expiring every 30 minutes and needing a re-arm).
#
# The state file persists between runs, so a relaunch never replays the baseline; delete it to see
# the whole snapshot once. The queue is read from the Q= line of the main checkout's pre-push hook,
# which several-agents.md names as the one authority for where the live queue is.
#
# Usage: scripts/supervisor/watch.sh --self <this session's id> [--until-change|--stream]
#   SUPERVISOR_STATE_DIR  where watch.state lives (default: $TMPDIR/supervisor-<checkout name>)
#   SUPERVISOR_INTERVAL   seconds between snapshots (default 150)
set -u
export LC_ALL=C GIT_OPTIONAL_LOCKS=0
HERE=$(cd "$(dirname "$0")" && pwd)
common=$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir) || exit 3
REPO=$(dirname "$common")
Q=$(sed -n "s/^Q=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" "$common/hooks/pre-push" 2>/dev/null | head -1)
MODE=until-change SELF=""
while [ $# -gt 0 ]; do
  case "$1" in
    --self) SELF=${2:-}; shift 2;;
    --until-change) MODE=until-change; shift;;
    --stream) MODE=stream; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
[ -n "$SELF" ] || { echo "--self <session id> is required, so this session is never offered for archive" >&2; exit 2; }
STATE_DIR=${SUPERVISOR_STATE_DIR:-${TMPDIR:-/tmp}/supervisor-$(basename "$REPO")}
mkdir -p "$STATE_DIR"
STATE="$STATE_DIR/watch.state"
INTERVAL=${SUPERVISOR_INTERVAL:-150}

snapshot() {
  cd "$REPO" || return
  if [ -z "$Q" ]; then
    echo "ALERT no Q= line in $common/hooks/pre-push; queue not watched"
  elif [ -f "$Q/lock/holder" ]; then
    spec=$(awk '$1=="spec"{print $2}' "$Q/lock/holder"); br=$(awk '$1=="branch"{print $2}' "$Q/lock/holder")
    since=$(awk '$1=="since"{print $2}' "$Q/lock/holder")
    echo "QUEUE lock held by $spec on $br since $since"
    age=$(( $(date -u +%s) - $(date -ju -f %Y-%m-%dT%H:%M:%SZ "$since" +%s 2>/dev/null || date -u +%s) ))
    [ "$age" -gt 4800 ] && echo "ALERT lock held by $spec for over 80 minutes"
  else
    echo "QUEUE lock free"
  fi
  for t in "${Q:-/nonexistent}"/tickets/*; do [ -d "$t" ] || continue
    echo "QUEUE waiting $(basename "$t") $(cat "$t/spec" 2>/dev/null)"
  done
  if prs=$(gh pr list --state open --json number,headRefName,isDraft --jq '.[]|"PR open #\(.number) \(.headRefName)\(if .isDraft then " DRAFT" else "" end)"' 2>&1); then
    [ -n "$prs" ] && echo "$prs"
  else echo "ALERT gh pr list failed"; fi
  if runs=$(gh run list --branch main --event push --limit 12 --json headSha,name,status,conclusion 2>&1); then
    echo "$runs" | python3 -c '
import json, sys
runs = json.load(sys.stdin)
if not runs:
    print("MAIN no push runs")
    sys.exit()
sha = runs[0]["headSha"]
mine = [r for r in runs if r["headSha"] == sha]
bad = [r["name"] for r in mine if r["status"] == "completed" and r["conclusion"] not in ("success", "skipped", "neutral")]
busy = [r for r in mine if r["status"] != "completed"]
print("MAIN %s %s" % (sha[:8], "RED: " + ", ".join(bad) if bad else ("building" if busy else "green")))'
  else echo "ALERT gh run list failed"; fi
  "$HERE/overlap.sh" 2>/dev/null | grep -E '^(SHARED|CONFLICT)'
  python3 "$HERE/done_check.py" --self "$SELF" 2>/dev/null | awk -F'\t' '$4=="ARCHIVABLE"{print "ARCHIVABLE " $1 " " $2}'
}

while true; do
  cur=$(snapshot | sort -u)
  if [ ! -f "$STATE" ]; then
    printf '%s\n' "$cur" | sed 's/^/= /'
    printf '%s\n' "$cur" > "$STATE"
    [ "$MODE" = until-change ] && exit 0
  elif [ "$cur" != "$(cat "$STATE")" ]; then
    diff <(cat "$STATE") <(printf '%s\n' "$cur") | sed -n 's/^> /+ /p; s/^< /- /p'
    printf '%s\n' "$cur" > "$STATE"
    [ "$MODE" = until-change ] && exit 0
  fi
  sleep "$INTERVAL"
done
