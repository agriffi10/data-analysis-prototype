#!/usr/bin/env bash
# Live checks for the results-conversion control plane. ONE SCRIPT FOR THE PLANE, NOT ONE PER SPEC.
#
# NOT RUNNABLE AS WRITTEN (found 2026-09-10, banner added 2026-09-22 after a session followed
# USAGE step 2 into nothing). Since SPEC-262 the browser holds no token at all. Either read the token
# from the session store as step 2 now says, or send each section's body from the signed-in page, which is how the SPEC-239 section ran
# on 2026-09-22 (see docs/testing/sessions.md). Every section's EXPECT text still holds.
#
# Named for the plane for the reason file-ops-plane.sh states at length: four specs build this
# thing, and a script each would be four files sharing a token, a queue URL and an envelope
# builder. A spec that owes a CLI check ADDS A SECTION HERE and points its owed.md row at it.
#
# WHAT IS LEFT HERE, AND WHY (updated when SPEC-223 shipped the browser surface). This file used to
# carry every check, because nothing in the browser reached this plane. A conversion is now a click:
# the per-format saves, the read-back, the overwrite question and the notification's link are steps
# in e2e.md §4.3 and §4.5, and this script is no longer the way to run them.
#
# What stays is what a browser cannot express, which is a shorter list than it looks:
#   - The raw envelope — a literal 200 with the echoed request id, which a click only shows with
#     the network panel open.
#   - `destination_occupied` staged as a REAL race. The browser cannot send `onConflict: refuse`
#     at an occupied destination at all: `useSaveResults` runs an `objects.exists` pre-flight and
#     turns an occupied answer into the overwrite question, so reaching the plane's own conditional
#     refusal needs a hand-crafted envelope that skips the probe.
#   - Refusals with no browser path — a malformed envelope, an execution that is not the actor's.
#   - The CloudWatch reads.
#
# USAGE
#   1. Sign in to the portal as the account you want to act as.
#   2. Copy its ID token into /tmp/idtoken (no trailing newline). Since SPEC-262 the browser holds no
#      token: the portal server keeps it in the session store. Load any portal page first, so the
#      server refreshes a token near expiry, copy the __Host-dq_session cookie's value from the
#      browser's developer tools, and read the item it names:
#        COOKIE='<the cookie value>'
#        PK="session#$(printf %s "$COOKIE" | shasum -a 256 | cut -d' ' -f1)"
#        aws dynamodb get-item --table-name dat-prod-sessions --consistent-read \
#          --key "{\"pk\":{\"S\":\"$PK\"}}" --projection-expression idToken \
#          --query Item.idToken.S --output text | tr -d '\n' > /tmp/idtoken
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

# The fifth argument is spliced in whole, so it carries its own leading comma or is empty --
# `columnIndexes` is the one optional field on this request and a JSON object cannot hold a
# trailing one.
enqueue() { # enqueue <format> <filename> <onConflict> <tag> [<,"columnIndexes":[...]>]
  curl -sS -X POST "$API/v1/enqueue/results-conversion" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "$(printf '{"requestId":"live-%s-%s","queryExecutionId":"%s","format":"%s","onConflict":"%s","submittedAt":"%s"%s,"destination":{"space":{"kind":"personal","name":"%s"},"prefix":"spec-222/","filename":"%s"}}' \
      "$4" "$(date +%s)" "$EXECUTION_ID" "$1" "$3" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$5" "$USERNAME" "$2")"
}

# ── SPEC-222 §1 · one conversion per format ──────────────────────────────────
# owed.md: "A conversion end to end, one per format"
echo "== SPEC-222 §1 · a conversion per format =="
for fmt in parquet json xlsx; do
  case "$fmt" in parquet) ext=parquet ;; json) ext=json ;; xlsx) ext=xlsx ;; esac
  body="$(enqueue "$fmt" "live.$ext" refuse "$fmt" "")"
  printf '%s' "$body" | grep -q '"requestId"'
  check $? "$fmt accepted: $body"
done

# ── SPEC-239 · the fourth writer, and the columns it keeps ───────────────────
# A CSV conversion is the one the browser asks for only when the file keeps a SUBSET of the
# result's columns, so the interesting request is the one carrying a list. The refusal beside it
# is the VERB's, on the list's shape; the API's length bound is not exercised here, because a
# 1,501-entry body is a thing this file would have to build rather than read, and the suite
# already measures it against the state limit.
echo "== SPEC-239 · a CSV conversion of the chosen columns =="
body="$(enqueue csv "live-columns.csv" refuse csv-cols ',"columnIndexes":[1,0]')"
printf '%s' "$body" | grep -q '"requestId"'
check $? "csv with a column choice accepted: $body"

body="$(enqueue csv "live-whole.csv" refuse csv-whole "")"
printf '%s' "$body" | grep -q '"requestId"'
check $? "csv with no column choice accepted: $body"

body="$(enqueue csv "live-bad.csv" refuse csv-bad ',"columnIndexes":[0,0]')"
printf '%s' "$body" | grep -q '"requestId"'
check $? "a repeated position is accepted at the door and refused by the verb: $body"
cat <<'EYES'

  BY EYE, for the three SPEC-239 requests above: "live-columns.csv" arrives holding the result's
  first two columns in the order 2nd, 1st, and no others; "live-whole.csv" holds every column in
  the result's own order; and the repeated position comes back as "Couldn't save the query
  results: the columns chosen for this file don't match the query's results, so nothing was
  saved." with no file written.

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
  byte(s)" line.

  Excel's time and memory are both spent per CELL, not per byte, and its cap is a cell count
  derived in rccommon.config from a measured model; the plane suite scales every measured shape
  to the largest input the caps admit, slowing its local rate by 5 (a measured 4.0). Compare
  Max Memory Used with that model for the input you converted — e2e.md section 4.3 carries the
  one input worth converting for this, the largest the caps admit, with the model's bound. A
  reading above the model is a finding against the constants, not a pass.
EYES

echo
echo "== $pass passed, $fail failed, plus the observations above =="
[ "$fail" = 0 ]
