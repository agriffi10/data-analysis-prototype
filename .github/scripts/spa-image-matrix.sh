#!/usr/bin/env bash
# The SPA image's behaviour matrix. Every criterion this image is built against is a response
# header, a status code or a file in a layer, and NOTHING in the other suites observes any of
# them — no Vitest test sees nginx, no pytest sees a Dockerfile. Without this script the image's
# whole specification is documentation.
#
# IT ASSERTS ON RESPONSES, NEVER ON THE CONFIGURATION'S TEXT. Grepping an nginx config for
# `add_header` passes on a config nginx never loaded, on a server block that lost to another one
# on the same port, and on a header wiped by the inheritance rule that makes this file necessary.
#
# The container under test runs the way ECS runs it — read-only root, uid 101, the two tmpfs
# mounts and no others — because "it works on my laptop with a writable filesystem" is not the
# claim. It is also started with no `--entrypoint` override, so the entrypoint under test is the
# deployed one.
#
# Usage: spa-image-matrix.sh <image-ref> [expected-build-version]
set -uo pipefail

IMAGE="${1:?usage: spa-image-matrix.sh <image-ref> [expected-build-version]}"
EXPECTED_VERSION="${2:-}"

PORT=18099
BASE="http://localhost:${PORT}"
NAME="spa-matrix-$$"

# Fixture values, chosen so a value that leaks somewhere it should not is recognisable on sight.
CONNECT_SRC="'self' https://cognito-idp.us-east-1.amazonaws.com https://auth.fixture.test https://api.fixture.test"
CONNECT_SRC_ALT="'self' https://alternate.fixture.test"

# The document's required keys. Restated here rather than imported: this script runs in a
# container-less shell with no TypeScript, and the agreement between this list and the
# classification is asserted by the Python suite, which can read both.
REQUIRED_ENV=(
  -e CONFIG_appUrl=https://portal.fixture.test
  -e CONFIG_awsRegion=us-east-1
  -e CONFIG_userSpaceBucket=fixture-user-space
  -e CONFIG_athenaWorkgroup=fixture-workgroup
  -e CONFIG_cognitoUserPoolId=us-east-1_FIXTURE
  -e CONFIG_cognitoUserPoolClientId=fixtureclientid
  -e CONFIG_cognitoDomain=auth.fixture.test
)
OPTIONAL_ENV=(
  -e CONFIG_apiBaseUrl=https://api.fixture.test
  -e CONFIG_environment=fixture
  -e CONFIG_maxUploadBytes=1048576
  -e CONFIG_sharedSpaceBucket=fixture-shared-space
  -e CONFIG_cognitoIdentityPoolId=us-east-1:fixture
  -e CONFIG_sharedSpaceQueueUrl=https://sqs.us-east-1.amazonaws.com/1/a.fifo
  -e CONFIG_notificationsQueueUrl=https://sqs.us-east-1.amazonaws.com/1/b.fifo
  -e CONFIG_tableBuildQueueUrl=https://sqs.us-east-1.amazonaws.com/1/c.fifo
  -e CONFIG_tableShareQueueUrl=https://sqs.us-east-1.amazonaws.com/1/d.fifo
  -e CONFIG_dataQualityQueueUrl=https://sqs.us-east-1.amazonaws.com/1/e.fifo
  -e CONFIG_fileSendQueueUrl=https://sqs.us-east-1.amazonaws.com/1/f.fifo
  -e CONFIG_archiveQueueUrl=https://sqs.us-east-1.amazonaws.com/1/g.fifo
  -e CONFIG_fileOpsQueueUrl=https://sqs.us-east-1.amazonaws.com/1/h.fifo
)
# The mounts ECS creates, with the ownership that is the whole reason they are tmpfs rather than
# task volumes. A volume arrives empty and root-owned, which a non-root container cannot write.
RUNTIME_FLAGS=(
  --read-only --user 101
  --tmpfs /tmp:uid=101,gid=101,mode=1777
  --tmpfs /var/cache/nginx:uid=101,gid=101,mode=1777
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

# Every equality below compares two DERIVED values, and two derived values that are both empty
# are equal. A guard that cannot tell "matched" from "found nothing" is the failure this whole
# file exists to prevent, so nothing is compared before it is known to be non-empty.
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

check_absent() {
  local label="$1" haystack="$2" needle="$3"
  if [[ "$haystack" == *"$needle"* ]]; then
    fail "$label" "found [$needle] where it must not appear"
  else
    pass "$label"
  fi
}

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# ── Static properties of the image ────────────────────────────────────────────
section() { printf '\n== %s\n' "$1"; }

section "The image"

DOCKERFILE="${DOCKERFILE_PATH:-apps/portal/Dockerfile}"
# A tag is mutable, so a rebuild of an unchanged commit can produce a different image — which
# makes "the sha identifies what is running" false, and that claim is what the pipeline's whole
# tagging scheme rests on.
FROM_LINES=$(grep -c '^FROM ' "$DOCKERFILE")
PINNED=$(grep -c '^FROM .*@sha256:' "$DOCKERFILE")
check_eq "every FROM is pinned by digest ($FROM_LINES stages)" "$PINNED" "$FROM_LINES"

USER_CONFIG=$(docker image inspect --format '{{.Config.User}}' "$IMAGE" 2>/dev/null)
check_eq "the image declares a non-root user" "$USER_CONFIG" "101"

UID_INSIDE=$(docker run --rm --platform linux/amd64 --entrypoint id "$IMAGE" -u 2>/dev/null)
if [ "$UID_INSIDE" = "0" ] || [ -z "$UID_INSIDE" ]; then
  fail "the running process is not root" "id -u reported [$UID_INSIDE]"
else
  pass "the running process is not root (uid $UID_INSIDE)"
fi

# The runtime stage copies only dist/, so this cannot fail on a leak into the CONTEXT — the build
# stage asserts that, where it can be seen. This is the second half: nothing unwanted was copied.
STRAYS=$(docker run --rm --platform linux/amd64 --entrypoint find "$IMAGE" / -xdev \
           \( -name node_modules -o -name '.git' -o -name '*.env' -o -name '.env.example' \
              -o -name '*.test.ts' -o -name '*.test.tsx' \) -print 2>/dev/null | head -5)
check_eq "no node_modules, .git, env file or test file in the image" "${STRAYS:-clean}" "clean"

# One server, on one port. The base image ships a default site that also listens on 8080; if its
# include survived, whichever parsed first would become the default server and half the header
# set would be missing from real responses while a local curl looked perfect.
LISTENERS=$(docker run --rm --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "${REQUIRED_ENV[@]}" \
              -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC" --entrypoint sh "$IMAGE" -c \
              '/docker-entrypoint.d/40-render-portal-config.sh >/dev/null 2>&1; nginx -T 2>/dev/null | grep -c "listen 8080"')
check_eq "exactly one server listens on 8080" "$LISTENERS" "1"

# ── The literals that must not be frozen into the image ───────────────────────
section "No environment is baked into the image"

# Scoped to these two trees deliberately. The BUNDLE still ships @aws-sdk and aws-amplify, whose
# endpoint rulesets embed amazonaws.com by the thousand, so a whole-filesystem grep is
# unsatisfiable for the length of this arc and would be "fixed" by deleting it. These are the
# files that could actually freeze a host into the image.
#
# The rendered output under /tmp legitimately carries the hosts and is out of scope by design.
for literal in amazonaws.com fixture-user-space fixture-shared-space us-east-1 api.fixture.test auth.fixture.test; do
  HITS=$(docker run --rm --platform linux/amd64 --entrypoint grep "$IMAGE" -rl "$literal" /etc/nginx /docker-entrypoint.d 2>/dev/null | head -3)
  check_eq "no '$literal' under /etc/nginx or /docker-entrypoint.d" "${HITS:-clean}" "clean"
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

ASSET=$(docker exec "$NAME" sh -c 'ls /usr/share/nginx/html/assets/*.js | head -1 | xargs basename')
[ -n "$ASSET" ] || { echo "no hashed asset in the image — the build produced nothing" >&2; exit 1; }

# One request, reused by every assertion about it: headers to a file, body to another.
fetch() {
  local path="$1"; shift
  curl -sS --raw -o /tmp/matrix-body -D /tmp/matrix-head "$@" "${BASE}${path}"
}
status()  { head -1 /tmp/matrix-head | awk '{print $2}'; }
header()  { grep -i "^$1:" /tmp/matrix-head | head -1 | cut -d' ' -f2- | tr -d '\r'; }

# THE SIX CLASSES, plus the two the six do not reach: a real root-level static file (a stable URL,
# and none of the six) and the directory form under /assets/.
#
# Each is asserted for the FULL header set independently. One location that forgets the shared
# include serves its class with no CSP at all, while every other class looks perfect — there is no
# symptom, and no configuration review catches it.
assert_security_headers() {
  local label="$1"
  check_contains "$label: CSP names the fixture connect-src" "$(header content-security-policy)" "connect-src ${CONNECT_SRC}"
  check_contains "$label: CSP keeps default-src" "$(header content-security-policy)" "default-src 'self'"
  check_eq "$label: HSTS" "$(header strict-transport-security)" "max-age=31536000; includeSubDomains"
  check_absent "$label: HSTS claims no preload" "$(header strict-transport-security)" "preload"
  check_eq "$label: X-Frame-Options" "$(header x-frame-options)" "DENY"
  check_eq "$label: nosniff" "$(header x-content-type-options)" "nosniff"
  check_eq "$label: Referrer-Policy" "$(header referrer-policy)" "strict-origin-when-cross-origin"
  check_contains "$label: Permissions-Policy" "$(header permissions-policy)" "geolocation=()"
  check_eq "$label: COOP" "$(header cross-origin-opener-policy)" "same-origin"
  check_eq "$label: CORP" "$(header cross-origin-resource-policy)" "same-origin"
  # Absent BY DECISION: require-corp buys cross-origin isolation this app cannot use, at real
  # risk to subresource loads. The corresponding scanner alert stays open in the baseline.
  check_header_missing "$label: no COEP" "cross-origin-embedder-policy"
  # `Server: nginx` survives, and that is a named divergence rather than an oversight: removing it
  # needs a third-party module the official images do not ship. What must never come back is a
  # version number, which is what the scanner alert actually fires on.
  check_eq "$label: Server discloses no version" "$(header server)" "nginx"
  # An ABSENT Cache-Control is the original bug this class of header exists to fix, so presence is
  # asserted before correctness on every single class.
  if [ -z "$(header cache-control)" ]; then
    fail "$label: Cache-Control is present" "no Cache-Control at all — browsers apply heuristic freshness"
  else
    pass "$label: Cache-Control is present"
  fi
}

section "The shell"
fetch "/"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/html"
check_eq "cache class" "$(header cache-control)" "no-cache"
assert_security_headers "shell"

section "A deep link"
fetch "/files?prefix=alice/"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/html"
# The fallback is an INTERNAL REDIRECT, and a header set only in the root location and not
# inherited by the serving one is exactly the silent failure the include-per-location rule exists
# to prevent. So the fallback's cache class is asserted, not assumed to follow from the shell's.
check_eq "cache class is the shell's, not the assets one" "$(header cache-control)" "no-cache"
assert_security_headers "deep link"

section "A hashed asset"
fetch "/assets/${ASSET}"
check_eq "status" "$(status)" "200"
check_eq "cache class" "$(header cache-control)" "public, max-age=31536000, immutable"
assert_security_headers "asset"

section "A missing hashed asset — the honest 404"
fetch "/assets/index-DEADBEEF.js"
check_eq "status" "$(status)" "404"
# "Not HTML" is the criterion, and it is stated that way on purpose: nginx fixes the content type
# from the request URI BEFORE error_page runs, so this answers application/javascript for a .js
# request and text/plain for an extensionless one. Asserting "is text/plain" would redden
# truthfully and get "fixed" by weakening the check.
check_absent "the response is not HTML" "$(header content-type)" "text/html"
check_eq "cache class" "$(header cache-control)" "no-store"
# Every header here depends on `always`: without it add_header applies only to a short list of
# success and redirect codes, and this whole class silently loses the set while the 200 beside it
# keeps it. Measured.
assert_security_headers "asset 404"

section "The runtime configuration document"
fetch "/config.json"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "application/json"
check_eq "cache class" "$(header cache-control)" "no-store"
assert_security_headers "config.json"

# ASSERTED ON THE SERVED DOCUMENT, not on the entrypoint's source. A key list read from the script
# is the config-file-text assertion this file forbids.
SERVED_KEYS=$(jq -r '[keys[]] | sort | join(",")' /tmp/matrix-body 2>/dev/null)
EXPECTED_KEYS=$(printf '%s\n' version apiBaseUrl appUrl awsRegion environment maxUploadBytes \
  cognitoUserPoolId cognitoUserPoolClientId cognitoDomain cognitoIdentityPoolId userSpaceBucket \
  sharedSpaceBucket athenaWorkgroup sharedSpaceQueueUrl notificationsQueueUrl tableBuildQueueUrl \
  tableShareQueueUrl dataQualityQueueUrl fileSendQueueUrl archiveQueueUrl fileOpsQueueUrl | sort | paste -sd, -)
check_eq "the document carries exactly version plus the 20 classified keys" "$SERVED_KEYS" "$EXPECTED_KEYS"
check_eq "the document's version is the one the browser accepts" "$(jq -r '.version' /tmp/matrix-body)" "1"

section "The health endpoint"
fetch "/healthz"
check_eq "status" "$(status)" "200"
check_contains "content-type" "$(header content-type)" "text/plain"
check_eq "body is exactly ok" "$(cat /tmp/matrix-body)" "ok"
check_eq "cache class" "$(header cache-control)" "no-store"
assert_security_headers "healthz"

# A criterion that only asserts "/healthz returns 200" passes on a container with NO health
# endpoint at all, because the fallback answers 200 for everything. These two are what make the
# endpoint's existence observable.
for near in /healthz/ /healthzz; do
  fetch "$near"
  check_contains "${near} falls through to the shell (so /healthz is real)" "$(header content-type)" "text/html"
done

section "A root-level static file"
# A stable URL, and none of the six classes above — the assets rule is scoped by PREFIX precisely
# so that a root file does not accidentally inherit an immutable year.
fetch "/favicon.svg"
check_eq "status" "$(status)" "200"
check_eq "cache class" "$(header cache-control)" "no-cache"
assert_security_headers "root static file"

section "The preserved trap, and the redirect that must not name a port"
fetch "/nope.svg"
check_eq "a removed root file still answers 200" "$(status)" "200"
# Pinned so a later change to the fallback is VISIBLE rather than silent. It is why a removal can
# never be verified by status code here — read content-type instead.
check_contains "…as text/html, which is why removals are read from content-type" "$(header content-type)" "text/html"

fetch "/assets"
check_eq "the directory form redirects" "$(status)" "301"
# A container behind a load balancer that redirects to its own listen port sends the browser to an
# address that answers nothing.
check_absent "the redirect names no :8080" "$(header location)" "8080"

section "Compression"
fetch "/assets/${ASSET}" -H 'Accept-Encoding: gzip'
check_eq "an asset is served gzipped" "$(header content-encoding)" "gzip"
check_eq "Vary names Accept-Encoding" "$(header vary)" "Accept-Encoding"
docker exec "$NAME" cat "/usr/share/nginx/html/assets/${ASSET}.gz" > /tmp/matrix-sibling 2>/dev/null
# BYTE-IDENTICAL to the sibling, compared RAW. Decompressing both sides passes whether nginx
# served the pre-built artefact or re-compressed per request, which is the one thing this
# assertion exists to tell apart.
if cmp -s /tmp/matrix-body /tmp/matrix-sibling; then
  pass "the served bytes are the pre-compressed sibling, not a re-compression"
else
  fail "the served bytes are the pre-compressed sibling, not a re-compression" \
       "gzip_static is not serving the .gz artefact"
fi
docker exec "$NAME" cat "/usr/share/nginx/html/assets/${ASSET}" > /tmp/matrix-plain
if gunzip -c /tmp/matrix-body 2>/dev/null | cmp -s - /tmp/matrix-plain; then
  pass "the gzip body decompresses to the on-disk file"
else
  fail "the gzip body decompresses to the on-disk file"
fi

MISSING_GZ=$(docker exec "$NAME" sh -c 'cd /usr/share/nginx/html/assets && for f in *.js *.css; do [ -f "$f.gz" ] || echo "$f"; done' | head -3)
check_eq "every asset js and css has a .gz sibling" "${MISSING_GZ:-complete}" "complete"

fetch "/assets/${ASSET}" -H 'Accept-Encoding: br'
# The residual, pinned: brotli needs the same third-party compile stage the Server header was
# refused over, so brotli-capable browsers receive gzip and the bundle transfers larger than it
# did through the distribution. A future brotli image is then a deliberate change with a failing
# test to update.
check_absent "brotli is not served" "$(header content-encoding)" "br"

fetch "/config.json" -H 'Accept-Encoding: gzip'
check_eq "the rendered document is gzipped dynamically" "$(header content-encoding)" "gzip"
NO_SIBLING=$(docker exec "$NAME" sh -c 'test -e /tmp/config.json.gz && echo present || echo absent')
check_eq "…and has no pre-compressed sibling, being rendered at start" "$NO_SIBLING" "absent"

section "The document is not reachable through the fallback"
# With the rendered file gone the path must 404. Answering the shell with a 200 would hand the
# browser HTML where it expects its configuration, and the failure would read as a parse error.
docker exec "$NAME" rm -f /tmp/config.json
fetch "/config.json"
check_eq "a missing document is a real 404" "$(status)" "404"
# The claim is 404-rather-than-a-200-shell, not a content type: nginx's own error page is HTML and
# is not the shell. So the body is checked for the shell's mount point instead.
check_absent "…and the body is not the SPA shell" "$(cat /tmp/matrix-body)" "<div id=\"root\""
docker restart "$NAME" >/dev/null && sleep 3

section "The build stamp"
STAMPED=$(docker exec "$NAME" printenv BUILD_VERSION 2>/dev/null)
LABELLED=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$IMAGE")
if [ -z "$STAMPED" ]; then
  fail "BUILD_VERSION is stamped in the image" "empty — ARG does not cross a stage boundary, so it must be re-declared in the runtime stage"
else
  check_eq "BUILD_VERSION equals the image's revision label" "$STAMPED" "$LABELLED"
  if [[ "$STAMPED" =~ ^[0-9a-f]{40}$ ]]; then
    pass "BUILD_VERSION is a commit sha"
  else
    fail "BUILD_VERSION is a commit sha" "got [$STAMPED]"
  fi
  [ -n "$EXPECTED_VERSION" ] && check_eq "BUILD_VERSION is the commit being built" "$STAMPED" "$EXPECTED_VERSION"
fi

# ── The refusals, and the renders that must differ ────────────────────────────
section "Refusals"

# A container that starts with an empty required value serves a shell that fails every call it
# makes. Unset and empty must behave identically: an unset repository variable, an unset Terraform
# input and an unsubstituted expansion all arrive as the empty string, and a check written as
# `[ -z "${VAR+x}" ]` passes all three.
refusal() {
  local label="$1"; shift
  local out code
  out=$(docker run --rm --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "$@" "$IMAGE" 2>&1)
  code=$?
  if [ "$code" -eq 0 ]; then
    fail "$label" "the container started; it must refuse"
  elif [[ "$out" != *"refusing to start"* ]]; then
    fail "$label" "exited $code but never named the missing variable"
  else
    local named
    named=$(echo "$out" | grep -o 'Unset or empty:.*' | head -1)
    pass "$label (exit $code — $named)"
  fi
}

MOST_OF_IT=(-e CONFIG_awsRegion=us-east-1 -e CONFIG_userSpaceBucket=b -e CONFIG_athenaWorkgroup=w
            -e CONFIG_cognitoUserPoolId=u -e CONFIG_cognitoUserPoolClientId=c -e CONFIG_cognitoDomain=d)
refusal "a required key UNSET"        "${MOST_OF_IT[@]}" -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
refusal "a required key EMPTY"        "${MOST_OF_IT[@]}" -e CONFIG_appUrl= -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
# Not "starts and serves connect-src ;", which is a policy that blocks every fetch and presents to
# a user as a network outage rather than as a misconfiguration.
refusal "connect-src EMPTY"           "${REQUIRED_ENV[@]}" -e PORTAL_CSP_CONNECT_SRC=
refusal "connect-src UNSET"           "${REQUIRED_ENV[@]}"

section "One image, two environments"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "${REQUIRED_ENV[@]}" \
  -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC_ALT" -p "${PORT}:8080" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do curl -fsS -o /dev/null "${BASE}/healthz" 2>/dev/null && break; sleep 1; done
fetch "/"
# The same digest must produce a different policy, or the CSP is baked and the image carries one
# environment's hosts everywhere — the build-time-configuration failure the runtime document exists
# to end.
check_contains "the same digest emits the second environment's policy" "$(header content-security-policy)" "connect-src ${CONNECT_SRC_ALT}"
check_absent "…and not the first's" "$(header content-security-policy)" "cognito-idp"

section "envsubst substitutes only what the entrypoint declares"
docker rm -f "$NAME" >/dev/null 2>&1
# nginx's own runtime variables must survive the render. Given no explicit list, envsubst
# substitutes every variable it finds a definition for, so a task definition that happened to
# carry `uri` or `host` would blank them and break routing with nothing to read in a config review.
docker run -d --name "$NAME" --platform linux/amd64 "${RUNTIME_FLAGS[@]}" "${REQUIRED_ENV[@]}" \
  -e uri=SENTINEL -e host=SENTINEL -e request_uri=SENTINEL \
  -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC" -p "${PORT}:8080" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do curl -fsS -o /dev/null "${BASE}/healthz" 2>/dev/null && break; sleep 1; done
fetch "/files?prefix=alice/"
check_eq "routing still works with a variable named uri in the environment" "$(status)" "200"
LEAKED=$(docker exec "$NAME" sh -c 'grep -c SENTINEL /tmp/nginx-conf/default.conf || true')
check_eq "no sentinel reached the rendered configuration" "${LEAKED:-0}" "0"

printf '\n%s\n' "----------------------------------------"
if [ "$FAILURES" -eq 0 ]; then
  printf 'matrix: %d checks, all passed\n' "$CHECKS"
else
  printf 'matrix: %d checks, %d FAILED\n' "$CHECKS" "$FAILURES"
fi
exit $(( FAILURES > 0 ? 1 : 0 ))
