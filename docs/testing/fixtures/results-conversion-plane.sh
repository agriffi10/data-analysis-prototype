#!/usr/bin/env bash
# Live checks for the results-conversion control plane. ONE SCRIPT FOR THE PLANE, NOT ONE PER SPEC.
#
# Named for the plane for the reason file-ops-plane.sh states at length: four specs build this
# thing, and a script each would be four files sharing a token, a queue URL and an envelope
# builder. A spec that owes a CLI check ADDS A SECTION HERE and points its owed.md row at it.
#
# WHY A SCRIPT AND NOT STEPS IN e2e.md: nothing in the browser reaches this plane. SPEC-221 built
# the front door and SPEC-222 the converter, and both shipped with "nothing a user can reach" as
# an explicit scope line — the browser surface is SPEC-223. So a conversion is an authenticated
# POST rather than a click, and every check here is an `owed.md` row that running this discharges.
#
# WHEN IT GOES AWAY: SPEC-223 gives the plane a UI. The checks a signed-in session can then drive
# move into e2e.md's query section, and this file keeps only what a browser cannot express — the
# refusals that need a hand-crafted envelope, and the CloudWatch reads.
#
# USAGE
#   1. Sign in to the portal as the account you want to act as.
#   2. Copy its ID token out of local storage into /tmp/idtoken (no trailing newline):
#        JSON.parse(Object.entries(localStorage).find(([k]) => k.endsWith('.idToken'))[1])
#   3. Run a query in the Query workspace that returns a few thousand rows of mixed types and
#      copy its execution id.
#   4. USERNAME=alice EXECUTION_ID=<id> ./results-conversion-plane.sh
#
# It prints one PASS/FAIL per machine-checkable assertion and lists the observations that need a
# pair of eyes (the notifications, the table builder, the workbook).

set -uo pipefail

API="${API:-https://api.dataquarry.app}"
TOKEN_FILE="${TOKEN_FILE:-/tmp/idtoken}"
: "${USERNAME:?USERNAME=<your portal username>}"
: "${EXECUTION_ID:?EXECUTION_ID=<a finished execution of your own>}"
[ -r "$TOKEN_FILE" ] || { echo "no token at $TOKEN_FILE — see USAGE"; exit 2; }
TOKEN="$(cat "$TOKEN_FILE")"
OUT="${OUT:-${TMPDIR:-/tmp}/results-conversion-live}"
mkdir -p "$OUT"
pass=0 fail=0
check() { if [ "$1" = 0 ]; then echo "  PASS  $2"; pass=$((pass + 1)); else echo "  FAIL  $2"; fail=$((fail + 1)); fi; }

enqueue() { # enqueue <format> <filename> <onConflict> <tag>
  curl -sS -X POST "$API/v1/enqueue/results-conversion" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "$(printf '{"requestId":"live-%s-%s","queryExecutionId":"%s","format":"%s","onConflict":"%s","submittedAt":"%s","destination":{"space":{"kind":"personal","name":"%s"},"prefix":"spec-222/","filename":"%s"}}' \
      "$4" "$(date +%s)" "$EXECUTION_ID" "$1" "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$USERNAME" "$2")"
}

# ── SPEC-222 §1 · one conversion per format ──────────────────────────────────
# owed.md: "A conversion end to end, one per format"
echo "== SPEC-222 §1 · a conversion per format =="
for fmt in parquet json xlsx; do
  case "$fmt" in parquet) ext=parquet ;; json) ext=json ;; xlsx) ext=xlsx ;; esac
  body="$(enqueue "$fmt" "live.$ext" refuse "$fmt")"
  printf '%s' "$body" | grep -q '"requestId"'
  check $? "$fmt accepted: $body"
done
cat <<'EYES'

  BY EYE, after ~30s, in Notifications — one message per format:
    Saved N rows as <Parquet|JSON|Excel> to "live.<ext>".
  and its link lands in spec-222/. The .xlsx one ALSO carries the sentence about numbers being
  rounded IFF the result set holds a bigint over 2^53 or a decimal wider than 15 digits.

  THEN: build a table from spec-222/live.parquet and from spec-222/live.json. Both must create,
  and their column names and types must match the query's. That round trip is the reason this
  arc exists; a conversion that cannot be read back has not converted anything useful.

  THEN: download all three into $OUT and re-run this script — §3 checks the workbook.
EYES

# ── SPEC-222 §2 · the conditional write ──────────────────────────────────────
# owed.md: "destination_occupied, staged as a real race"
#
# THIS SECTION MUST NOT RACE §1. The refusal it is checking for is "the name is already taken",
# which is only what happened if §1's parquet has actually landed first — run concurrently, a
# second request can win, the first can report the refusal, and the section passes while proving
# the opposite of what it says. The `overwrite` check below is worse: "the modified time moves"
# means nothing if two writes are in flight. So this waits.
echo
echo "== SPEC-222 §2 · a name already taken =="
if [ -t 0 ]; then
  printf '  Press RETURN once §1'"'"'s three notifications have arrived and spec-222/live.parquet exists. '
  read -r _
else
  echo "  not a terminal — sleeping 60s instead of waiting for you"
  sleep 60
fi
body="$(enqueue parquet "live.parquet" refuse race)"
printf '%s' "$body" | grep -q '"requestId"'
check $? "second refuse-mode request accepted: $body"
echo "  BY EYE: the notification must be the NAMED refusal —"
echo '    …a file called "live.parquet" is already in that folder, so nothing was saved.'
echo "  An AccessDenied or a generic sentence here means the conditional write is not the thing"
echo "  doing the refusing, which is the whole design."
if [ -t 0 ]; then
  printf '  Press RETURN once the refusal above has arrived, so the overwrite is not racing it. '
  read -r _
else
  sleep 60
fi
body="$(enqueue parquet "live.parquet" overwrite overwrite)"
printf '%s' "$body" | grep -q '"requestId"'
check $? "overwrite-mode request accepted: $body"
echo "  BY EYE: this one SUCCEEDS and live.parquet's modified time moves."

# ── SPEC-222 §3 · the workbook, once downloaded ──────────────────────────────
echo
echo "== SPEC-222 §3 · the Excel fences =="
if [ -f "$OUT/live.xlsx" ]; then
  python3 - "$OUT/live.xlsx" <<'PY'
import re, sys, xml.etree.ElementTree as ET, zipfile
book = zipfile.ZipFile(sys.argv[1])
sheet = book.read("xl/worksheets/sheet1.xml").decode()
formulas = re.findall(r"<f[ >]", sheet)
names = [s.get("name") for s in ET.fromstring(book.read("xl/workbook.xml")).iter() if s.tag.endswith("}sheet")]
print(f"    formula cells: {len(formulas)}   sheets: {names}")
sys.exit(0 if not formulas and names == ["results"] else 1)
PY
  check $? "no cell is a formula, and there is one sheet named results"
else
  echo "  SKIP  $OUT/live.xlsx not downloaded yet"
fi

# ── SPEC-222 §4 · the measurement no local run can take ──────────────────────
# owed.md: "The converter's real throughput on amd64"
echo
echo "== SPEC-222 §4 · throughput on the deployed architecture =="
cat <<'EYES'
  Read the LAST log stream of /aws/lambda/dat-prod-results-conversion-convert and record, for the
  .xlsx run: the REPORT line's Duration and Max Memory Used, and the "converted N row(s) into M
  byte(s)" line. Divide the source CSV's size by the duration.

  The size caps derate a measured 4.2 MB/s Excel figure by 4, because that measurement was taken
  on an arm64 build and this runs amd64. BELOW ROUGHLY 1 MB/s AND THE CAP MUST COME DOWN. Max
  Memory Used against the 3008 MB the function is sized at is the other half — the Excel cap is
  memory-bound, at a measured 23-32x the input CSV.
EYES

echo
echo "== $pass passed, $fail failed, plus the observations above =="
[ "$fail" = 0 ]
