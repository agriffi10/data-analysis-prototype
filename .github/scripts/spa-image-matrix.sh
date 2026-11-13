#!/usr/bin/env bash
# The portal image's behaviour matrix. Every criterion this image is built against is a response
# header, a status code, a byte of HTML or a file in a layer, and NOTHING in the other suites
# observes any of them in the image that ships: Vitest drives modules, not the standalone server.
# Without this script the image's whole specification is documentation.
#
# IT ASSERTS ON RESPONSES, NEVER ON THE SOURCE'S TEXT. A route handler that exists in the tree but
# was not built answers nothing; a header the proxy sets can override a route handler's; and the
# optional catch-all answers ANY unmatched path with the app shell under a 200, so a missing health
# route, a missing configuration document and a missing chunk all read as success by status alone.
#
# The container under test runs the way ECS runs it — read-only root, uid 1000, one tmpfs at /tmp
# and no other — because "it works with a writable filesystem" is not the claim.
#
# Usage: spa-image-matrix.sh <image-ref> [expected-build-version]
set -uo pipefail

IMAGE="${1:?usage: spa-image-matrix.sh <image-ref> [expected-build-version]}"
EXPECTED_VERSION="${2:-}"

PORT=18099
BASE="http://localhost:${PORT}"
NAME="spa-matrix"

# Fixture values, chosen so a value that leaks somewhere it should not is recognisable on sight.
CONNECT_SRC="'self' https://cognito-idp.us-east-1.amazonaws.com https://auth.fixture.test https://api.fixture.test"
CONNECT_SRC_ALT="'self' https://alternate.fixture.test"

# Deliberately awkward, and carried by a real key rather than a probe of its own: a quote, a
# backslash and a newline are legal in a configuration value and must reach the document intact.
AWKWARD_VALUE='he said "hi" \ then left
on a new line'

# The whole page policy, with NONCE standing for the response's own nonce. Every directive but
# script-src's nonce and connect-src describes the bundle; the TypeScript suite holds them against a
# recorded literal, and this is what every page response is measured against.
EXPECTED_CSP_TEMPLATE="default-src 'self'; script-src 'self' 'nonce-NONCE'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data:; font-src 'self' data: https://fonts.gstatic.com; worker-src 'self' blob:; connect-src ${CONNECT_SRC}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"

# The policy a request carrying a body gets instead: it never reaches the proxy.
LOCKDOWN_CSP="default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"

# Next's cache class for a dynamically rendered page. Every page carries a per-request nonce, so a
# page must never be stored anywhere.
PAGE_CACHE="private, no-cache, no-store, max-age=0, must-revalidate"

# The document's required keys. Restated here rather than imported: this script runs in a shell
# with no TypeScript, and the classification's agreement with the task definition is asserted by
# the suites that can read both.
REQUIRED_ENV=(
  -e CONFIG_apiBaseUrl=https://api.fixture.test
  -e CONFIG_appUrl=https://portal.fixture.test
  -e CONFIG_awsRegion=us-east-1
  -e CONFIG_userSpaceBucket=fixture-user-space
  -e CONFIG_cognitoUserPoolId=us-east-1_FIXTURE
  -e CONFIG_cognitoUserPoolClientId=fixtureclientid
  -e CONFIG_cognitoDomain=auth.fixture.test
)
OPTIONAL_ENV=(
  -e "CONFIG_environment=$AWKWARD_VALUE"
  -e CONFIG_maxUploadBytes=1048576
  -e CONFIG_sharedSpaceBucket=fixture-shared-space
)
# The mount ECS creates, owned by the container's user: a task volume arrives empty and root-owned,
# which a non-root container cannot write.
RUNTIME_FLAGS=(
  --read-only --user 1000
  --tmpfs /tmp:uid=1000,gid=1000,mode=1777
)

FAILURES=0
CHECKS=0

pass() { CHECKS=$((CHECKS + 1)); printf '  ok   %s\n' "$1"; }
fail() {
  CHECKS=$((CHECKS + 1)); FAILURES=$((FAILURES + 1))
  printf '  FAIL %s\n' "$1"
  [ $# -gt 1 ] && printf '       %s\n' "$2"
  return 0
}

# Every equality below compares two DERIVED values, and two derived values that are both empty are
# equal. A guard that cannot tell "matched" from "found nothing" is the failure this whole file
# exists to prevent, so nothing is compared before it is known to be non-empty.
check_eq() {
  local label="$1" actual="$2" expected="$3"
  if [ -z "$actual" ]; then
    fail "$label" "read nothing — the probe found no value, which is not the same as a match"
  elif [ "$actual" = "$expected" ]; then
    pass "$label"
  else
    fail "$label" "expected [$expected], got [$actual]"
  fi
}

check_contains() {
  local label="$1" haystack="$2" needle="$3"
  if [ -z "$haystack" ]; then
    fail "$label" "read nothing"
  elif [[ "$haystack" == *"$needle"* ]]; then
    pass "$label"
  else
    fail "$label" "expected to contain [$needle], got [$haystack]"
  fi
}

check_absent() {
  local label="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    fail "$label" "found [$needle] where it must not appear"
  else
    pass "$label"
  fi
}

# For a header whose correct state is ABSENCE. check_eq cannot express this: it treats an empty
# reading as "the probe found nothing", which is the right default everywhere else and wrong here.
check_header_missing() {
  local label="$1" name="$2"
  if grep -qi "^${name}:" /tmp/matrix-head; then
    fail "$label" "the header is present: $(grep -i "^${name}:" /tmp/matrix-head | head -1)"
  else
    pass "$label"
  fi
}

# FAIL CLOSED. A probe that shells into the image and compares its output to "nothing found" would
# read a command that failed for ANY reason as clean, so the container prints a sentinel after the
# real command, and its absence is the failure.
probe_image() {
  docker run --rm --platform linux/amd64 --entrypoint sh "$IMAGE" -c "$1; echo __probe_ran__" 2>&1
}

check_probe() {
  local label="$1" output="$2"
  if [[ "$output" != *"__probe_ran__"* ]]; then
    fail "$label" "the probe did not run to completion: ${output:-(no output at all)}"
    return 0
  fi
  local found="${output%%__probe_ran__*}"
  if [ -n "$(printf '%s' "$found" | tr -d '[:space:]')" ]; then
    fail "$label" "found: $(printf '%s' "$found" | head -3 | tr '\n' ' ')"
  else
    pass "$label"
  fi
}

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

section() { printf '\n== %s\n' "$1"; }

# ── Static properties of the image ────────────────────────────────────────────
section "The image"

DOCKERFILE="${DOCKERFILE_PATH:-apps/portal/Dockerfile}"
# A tag is mutable, so a rebuild of an unchanged commit can produce a different image, which makes
# "the sha identifies what is running" false.
FROM_LINES=$(grep -c '^FROM ' "$DOCKERFILE")
PINNED=$(grep -c '^FROM .*@sha256:' "$DOCKERFILE")
check_eq "every FROM is pinned by digest ($FROM_LINES stages)" "$PINNED" "$FROM_LINES"

USER_CONFIG=$(docker image inspect --format '{{.Config.User}}' "$IMAGE" 2>/dev/null)
check_eq "the image declares the task's non-root user" "$USER_CONFIG" "1000"

UID_INSIDE=$(docker run --rm --platform linux/amd64 --entrypoint id "$IMAGE" -u 2>/dev/null)
if [ "$UID_INSIDE" = "0" ] || [ -z "$UID_INSIDE" ]; then
  fail "the running process is not root" "id -u reported [$UID_INSIDE]"
else
  pass "the running process is not root (uid $UID_INSIDE)"
fi

if [ -n "$EXPECTED_VERSION" ]; then
  check_eq "the image's revision label is the commit it was built from" \
    "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE")" \
    "$EXPECTED_VERSION"
fi

# The build stage asserts nothing leaked into the CONTEXT; this is the second half: nothing
# unwanted was copied out of it. node_modules is expected (the standalone server's own), sources are
# not, and neither is a developer's environment file.
check_probe "no .git, environment file, test file, source tree or next-env.d.ts in the image" \
  "$(probe_image "find /app \( -name .git -o -name '.env*' -o -name '*.test.ts' -o -name '*.test.tsx' -o -name next-env.d.ts \) -print 2>/dev/null | head -5; test -d /app/apps/portal/src && echo /app/apps/portal/src")"

# ── No environment is baked into the image ────────────────────────────────────
section "No environment is baked into the image"

# The server's own tree is where a build-time value would land: the browser bundle legitimately
# carries Amplify's endpoint rules, which name amazonaws.com by the thousand. The server tree names
# no deployment's host, because every one arrives in the environment at start.
for literal in amazoncognito.com cognito-idp. fixture-user-space api.fixture.test; do
  check_probe "no '$literal' in the server's built tree" \
    "$(probe_image "grep -rl '$literal' /app/apps/portal/.next/server /app/apps/portal/server.js 2>/dev/null | head -3")"
done

# ── The running container ─────────────────────────────────────────────────────
start_container() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  docker run -d --name "$NAME" --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "${REQUIRED_ENV[@]}" "${OPTIONAL_ENV[@]}" \
    -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC" "$@" -p "${PORT}:8080" "$IMAGE" >/dev/null
  for _ in $(seq 1 30); do
    curl -fsS -o /dev/null "${BASE}/healthz" 2>/dev/null && return 0
    sleep 1
  done
  echo "the container never answered /healthz; logs follow" >&2
  docker logs "$NAME" >&2 2>&1
  return 1
}

start_container || { echo "cannot run the matrix against a container that will not start" >&2; exit 1; }

ASSET=$(docker exec "$NAME" sh -c 'ls /app/apps/portal/.next/static/chunks/*.js | head -1 | xargs basename')
[ -n "$ASSET" ] || { echo "no hashed chunk in the image — the build produced nothing" >&2; exit 1; }

# One request, reused by every assertion about it: headers to a file, body to another. Transfer
# framing is decoded (a route handler's body arrives chunked) and content encoding is not, so a
# gzip-encoded asset is read from its headers only.
fetch() {
  local path="$1"; shift
  curl -sS -o /tmp/matrix-body -D /tmp/matrix-head "$@" "${BASE}${path}"
}
status()  { head -1 /tmp/matrix-head | awk '{print $2}'; }
header()  { grep -i "^$1:" /tmp/matrix-head | head -1 | cut -d' ' -f2- | tr -d '\r'; }
nonce()   { header content-security-policy | sed -n "s/.*'nonce-\([^']*\)'.*/\1/p"; }

# THE FULL HEADER SET ON EVERY CLASS. A class that loses one header has no symptom anywhere else.
# The page policy is checked whole, with the response's own nonce put back into the template: a
# policy is only as good as its least asserted directive.
assert_security_headers() {
  local label="$1" expected_csp="$2"
  check_eq "$label: the whole CSP" "$(header content-security-policy)" "$expected_csp"
  check_eq "$label: HSTS" "$(header strict-transport-security)" "max-age=31536000; includeSubDomains"
  check_absent "$label: HSTS claims no preload" "$(header strict-transport-security)" "preload"
  check_eq "$label: X-Frame-Options" "$(header x-frame-options)" "DENY"
  check_eq "$label: nosniff" "$(header x-content-type-options)" "nosniff"
  check_eq "$label: Referrer-Policy" "$(header referrer-policy)" "strict-origin-when-cross-origin"
  check_contains "$label: Permissions-Policy" "$(header permissions-policy)" "geolocation=()"
  check_eq "$label: COOP" "$(header cross-origin-opener-policy)" "same-origin"
  check_eq "$label: CORP" "$(header cross-origin-resource-policy)" "same-origin"
  # Absent BY DECISION: require-corp buys cross-origin isolation this app cannot use.
  check_header_missing "$label: no COEP" "cross-origin-embedder-policy"
  check_header_missing "$label: no X-Powered-By" "x-powered-by"
  check_header_missing "$label: no Server banner" "server"
  if [ -z "$(header cache-control)" ]; then
    fail "$label: Cache-Control is present" "no Cache-Control at all — browsers apply heuristic freshness"
  else
    pass "$label: Cache-Control is present"
  fi
}

page_csp() { local n; n=$(nonce); printf '%s' "${EXPECTED_CSP_TEMPLATE//NONCE/${n:-MISSING}}"; }

section "The shell"
fetch "/"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/html"
check_eq "cache class" "$(header cache-control)" "$PAGE_CACHE"
check_eq "exactly one Content-Security-Policy header" "$(grep -ci '^content-security-policy:' /tmp/matrix-head)" "1"
assert_security_headers "shell" "$(page_csp)"

FIRST_NONCE=$(nonce)
# Every script and stylesheet carries THIS response's nonce. A tag without it is blocked by the
# policy, and the page boots without it in a way nothing but a browser shows.
SCRIPTS=$(grep -o '<script[^>]*>' /tmp/matrix-body | wc -l | tr -d ' ')
SCRIPTS_NONCED=$(grep -o '<script[^>]*>' /tmp/matrix-body | grep -c "nonce=\"${FIRST_NONCE}\"")
STYLES=$(grep -o '<link[^>]*rel="stylesheet"[^>]*>' /tmp/matrix-body | wc -l | tr -d ' ')
STYLES_NONCED=$(grep -o '<link[^>]*rel="stylesheet"[^>]*>' /tmp/matrix-body | grep -c "nonce=\"${FIRST_NONCE}\"")
if [ "${SCRIPTS:-0}" -eq 0 ] || [ "${STYLES:-0}" -eq 0 ]; then
  fail "the page has scripts and a stylesheet to stamp" "found $SCRIPTS script(s) and $STYLES stylesheet(s)"
else
  check_eq "every script carries the response's nonce ($SCRIPTS)" "$SCRIPTS_NONCED" "$SCRIPTS"
  check_eq "every stylesheet carries the response's nonce ($STYLES)" "$STYLES_NONCED" "$STYLES"
fi
check_contains "theme-init.js is one of them" \
  "$(grep -o '<script[^>]*theme-init\.js[^>]*>' /tmp/matrix-body)" "nonce=\"${FIRST_NONCE}\""

fetch "/" -H "x-nonce: chosen-by-the-client" -H "Content-Security-Policy: script-src *"
SECOND_NONCE=$(nonce)
if [ -n "$SECOND_NONCE" ] && [ "$SECOND_NONCE" != "$FIRST_NONCE" ] && [ "$SECOND_NONCE" != "chosen-by-the-client" ]; then
  pass "a second request gets a fresh nonce, not one the client sent"
else
  fail "a second request gets a fresh nonce, not one the client sent" "first [$FIRST_NONCE], second [$SECOND_NONCE]"
fi

section "A deep link"
fetch "/files/alice/reports"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/html"
check_eq "cache class is the page's" "$(header cache-control)" "$PAGE_CACHE"
assert_security_headers "deep link" "$(page_csp)"

section "A hashed asset"
fetch "/_next/static/chunks/${ASSET}" -H 'Accept-Encoding: gzip, br'
check_eq "status" "$(status)" "200"
check_eq "cache class" "$(header cache-control)" "public, max-age=31536000, immutable"
check_eq "served gzipped when asked" "$(header content-encoding)" "gzip"
check_contains "Vary names Accept-Encoding" "$(header vary)" "Accept-Encoding"
assert_security_headers "asset" "$(page_csp)"

section "A missing hashed asset"
# Without the /_next/ route handler the catch-all answers this with the app shell under a 200, and
# a module script fails on HTML with no way to tell "removed" from "never existed".
fetch "/_next/static/chunks/missing-$RANDOM.js"
check_eq "status" "$(status)" "404"
check_absent "the response is not HTML" "$(header content-type)" "text/html"
check_eq "cache class" "$(header cache-control)" "no-store"
assert_security_headers "asset 404" "$(page_csp)"

section "The runtime configuration document"
fetch "/config.json"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "application/json"
check_eq "cache class" "$(header cache-control)" "no-store"
assert_security_headers "config.json" "$(page_csp)"
check_eq "the document serves exactly version plus every key the environment supplied" \
  "$(jq -r 'keys | join(" ")' /tmp/matrix-body)" \
  "apiBaseUrl appUrl awsRegion cognitoDomain cognitoUserPoolClientId cognitoUserPoolId environment maxUploadBytes sharedSpaceBucket userSpaceBucket version"
check_eq "the document's version is the one the browser accepts" "$(jq -r '.version' /tmp/matrix-body)" "1"
check_eq "a value carrying a quote, a backslash and a newline round-trips" \
  "$(jq -r '.environment' /tmp/matrix-body)" "$AWKWARD_VALUE"

section "The health probe"
fetch "/healthz"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/plain"
check_eq "body is exactly ok" "$(cat /tmp/matrix-body)" "ok"
check_eq "cache class" "$(header cache-control)" "no-store"
assert_security_headers "healthz" "$(page_csp)"

section "The root-level static files"
fetch "/theme-init.js"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "javascript"
check_eq "cache class" "$(header cache-control)" "public, max-age=0"
assert_security_headers "theme-init.js" "$(page_csp)"

fetch "/favicon.svg"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "image/svg+xml"

# THE CATCH-ALL'S TRAP, pinned so a change to it is visible: a removed root-level file answers the
# app shell under a 200, so a removal is never verifiable by status code. Read content-type.
fetch "/removed-$RANDOM.js"
check_eq "a removed root file still answers 200" "$(status)" "200"
check_contains "…as text/html, which is why removals are read from content-type" "$(header content-type)" "text/html"

# ── A request that carries a body ─────────────────────────────────────────────
section "A request with a body is answered promptly"

# When the proxy matches a request with a body, Next waits for the WHOLE body before any page or
# handler answers. Measured: a client declaring a gigabyte and sending one byte held every path,
# the health probe included. So a bodied request skips the proxy and gets the lockdown floor.
#
# Raw sockets, not curl: curl would send the body it declared. `read -t` is the bound, a builtin, so
# no `timeout` binary is needed where this runs.
bodied() {
  local label="$1" path="$2" framing="$3"
  local head="" line
  exec 3<>"/dev/tcp/127.0.0.1/${PORT}" || { fail "$label" "could not connect"; return 0; }
  if [ "$framing" = "chunked" ]; then
    printf 'POST %s HTTP/1.1\r\nHost: localhost\r\nTransfer-Encoding: chunked\r\n\r\n1\r\nx\r\n' "$path" >&3
  else
    printf 'POST %s HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1073741824\r\n\r\nx' "$path" >&3
  fi
  while IFS= read -r -t 2 line <&3; do
    line="${line%$'\r'}"
    [ -z "$line" ] && break
    head="${head}${line}"$'\n'
  done
  exec 3<&- 3>&-
  printf '%s' "$head" > /tmp/matrix-head
  if [ -z "$head" ]; then
    fail "$label" "no answer within two seconds — the connection is held until the body arrives"
    return 0
  fi
  pass "$label: answered ($(head -1 /tmp/matrix-head))"
  check_eq "$label: the lockdown policy" "$(header content-security-policy)" "$LOCKDOWN_CSP"
  check_eq "$label: X-Frame-Options" "$(header x-frame-options)" "DENY"
  check_eq "$label: HSTS" "$(header strict-transport-security)" "max-age=31536000; includeSubDomains"
}

for path in / /files /config.json /healthz "/_next/static/chunks/missing-$RANDOM.js"; do
  bodied "a 1 GB declaration to $path" "$path" length
done
bodied "a chunked body that never ends, to /" "/" chunked

# ── The refusals, and the renders that must differ ────────────────────────────
section "Refusals"

# DETACHED AND BOUNDED, not a foreground run. The failure case is a container that starts and stays
# up, and in the foreground that hangs the gate instead of reporting anything. A throw in the start
# hook was measured to do exactly that: up, and answering 500 to every path.
refusal() {
  local label="$1" variable="$2"; shift 2
  local container="spa-refusal-$RANDOM"

  if ! docker run -d --name "$container" --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "$@" "$IMAGE" >/dev/null 2>&1; then
    fail "$label" "the container could not be created at all"
    return 0
  fi

  local state code
  for _ in $(seq 1 20); do
    state=$(docker inspect -f '{{.State.Status}}' "$container" 2>/dev/null)
    [ "$state" = "exited" ] && break
    sleep 1
  done

  code=$(docker inspect -f '{{.State.ExitCode}}' "$container" 2>/dev/null)
  local out
  out=$(docker logs "$container" 2>&1)
  docker rm -f "$container" >/dev/null 2>&1

  if [ "$state" != "exited" ]; then
    fail "$label" "the container is still running after 20s; it must refuse and exit"
  elif [ "$code" -eq 0 ]; then
    fail "$label" "the container exited 0; a refusal must be non-zero"
  elif [[ "$out" != *"refusing to start. ${variable} "* ]]; then
    fail "$label" "exited $code without naming ${variable}: $(echo "$out" | tail -1)"
  else
    pass "$label (exit $code, names ${variable})"
  fi
}

# EVERY required key, one at a time, unset and then empty: an unset repository variable and an
# unset task variable both arrive as the empty string.
for held_out in "${REQUIRED_ENV[@]}"; do
  case "$held_out" in -e) continue ;; esac
  key="${held_out%%=*}"

  without=()
  for entry in "${REQUIRED_ENV[@]}"; do
    case "$entry" in -e) continue ;; "$held_out") continue ;; esac
    without+=(-e "$entry")
  done

  refusal "$key UNSET" "$key" "${without[@]}" -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
  refusal "$key EMPTY" "$key" "${without[@]}" -e "${key}=" -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
done

refusal "connect-src EMPTY" PORTAL_CSP_CONNECT_SRC "${REQUIRED_ENV[@]}" -e PORTAL_CSP_CONNECT_SRC=
refusal "connect-src UNSET" PORTAL_CSP_CONNECT_SRC "${REQUIRED_ENV[@]}"
# A `;` would append a directive of the sender's choosing to every page's policy.
refusal "connect-src carrying a quote and a semicolon" PORTAL_CSP_CONNECT_SRC "${REQUIRED_ENV[@]}" \
  -e PORTAL_CSP_CONNECT_SRC="'self\"; script-src *"
refusal "connect-src carrying a newline" PORTAL_CSP_CONNECT_SRC "${REQUIRED_ENV[@]}" \
  -e "PORTAL_CSP_CONNECT_SRC=$(printf "'self'\nX-Injected: yes")"

section "One image, two environments"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "${REQUIRED_ENV[@]}" \
  -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC_ALT" -p "${PORT}:8080" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do curl -fsS -o /dev/null "${BASE}/healthz" 2>/dev/null && break; sleep 1; done
fetch "/"
# The same digest must produce a different policy, or the CSP is baked and the image carries one
# environment's hosts everywhere.
check_contains "the same digest emits the second environment's policy" "$(header content-security-policy)" "connect-src ${CONNECT_SRC_ALT};"
check_absent "…and not the first's" "$(header content-security-policy)" "cognito-idp"

section "Shutdown"
# ECS stops a task with SIGTERM and kills it thirty seconds later. A server that ignores the signal
# holds every deployment for those thirty seconds and then dies mid-request.
STARTED=$(date +%s)
docker stop "$NAME" >/dev/null 2>&1
ELAPSED=$(( $(date +%s) - STARTED ))
if [ "$ELAPSED" -le 3 ]; then
  pass "SIGTERM stops the server within three seconds (${ELAPSED}s)"
else
  fail "SIGTERM stops the server within three seconds" "it took ${ELAPSED}s"
fi

printf '\n%s\n' "----------------------------------------"
if [ "$FAILURES" -eq 0 ]; then
  printf 'matrix: %d checks, all passed\n' "$CHECKS"
else
  printf 'matrix: %d checks, %d FAILED\n' "$CHECKS" "$FAILURES"
fi
exit $(( FAILURES > 0 ? 1 : 0 ))
