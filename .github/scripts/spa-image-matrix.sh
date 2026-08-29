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
NAME="spa-matrix"

# Fixture values, chosen so a value that leaks somewhere it should not is recognisable on sight.
CONNECT_SRC="'self' https://cognito-idp.us-east-1.amazonaws.com https://auth.fixture.test https://api.fixture.test"
CONNECT_SRC_ALT="'self' https://alternate.fixture.test"

# Deliberately awkward, and carried by a real key rather than a probe of its own: a quote, a
# backslash and a newline are what a heredoc render breaks on, and every one of them is legal in a
# configuration value.
AWKWARD_VALUE='he said "hi" \ then left
on a new line'

# Every directive but connect-src is a property of the BUNDLE and ships baked in the image; this
# is the whole policy those two halves compose to. Its agreement with the Terraform local is the
# Python suite's assertion — here it is what every response class is measured against.
EXPECTED_CSP="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data:; font-src 'self' data: https://fonts.gstatic.com; worker-src 'self' blob:; connect-src ${CONNECT_SRC}; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; upgrade-insecure-requests"

# The document's required keys. Restated here rather than imported: this script runs in a
# container-less shell with no TypeScript, and the agreement between this list and the
# classification is asserted by the Python suite, which can read both.
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
  -e CONFIG_cognitoIdentityPoolId=us-east-1:fixture
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

# FAIL CLOSED. Four probes below shell out to docker and compare the output to "nothing found".
# Given a `${X:-clean}` default, a command that failed for ANY reason — a typo in the entrypoint
# override, an image that will not run, a path that moved — produces no output and reads as clean.
# So the container prints a sentinel after the real command, and its absence is the failure.
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

# Clear anything an interrupted earlier run left holding the port, before the first start rather
# than after a confusing failure.
cleanup

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
check_probe "no node_modules, .git, env file or test file in the image" \
  "$(probe_image "find / -xdev \( -name node_modules -o -name .git -o -name '*.env' -o -name .env.example -o -name '*.test.ts' -o -name '*.test.tsx' \) -print 2>/dev/null | head -5")"

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
  check_probe "no '$literal' under /etc/nginx or /docker-entrypoint.d" \
    "$(probe_image "grep -rl '$literal' /etc/nginx /docker-entrypoint.d 2>/dev/null | head -3")"
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
  # THE WHOLE HEADER, not a directive or two of it. A policy is only as good as its least
  # asserted directive: dropping `frame-ancestors` or `object-src` from the snippet used to leave
  # this gate at 151/151 green. Built from one expected string, so every directive is covered by
  # construction rather than by whoever remembered to add a check.
  check_eq "$label: the whole CSP" "$(header content-security-policy)" "$EXPECTED_CSP"
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

# DERIVED FROM THE FIXTURE, not restated beside it. A key added to the entrypoint but to neither
# the fixture nor a hand-written expectation renders empty, is dropped from the document, and both
# sides of a restated comparison agree that it is absent — the container then ships one feature
# silently unconfigured with this check green.
#
# The entrypoint's own key list is compared against the browser's classification by the Python
# suite, which can read TypeScript; this end asserts that everything supplied is served.
EXPECTED_KEYS=$(
  { printf 'version\n'
    printf '%s\n' "${REQUIRED_ENV[@]}" "${OPTIONAL_ENV[@]}" \
      | sed -n 's/^CONFIG_\([A-Za-z]*\)=.*/\1/p'
  } | sort | paste -sd, -
)
check_eq "the document serves exactly version plus every key the task definition supplied" \
  "$SERVED_KEYS" "$EXPECTED_KEYS"

# Guard-the-guard: a fixture that stopped supplying keys would make the comparison above agree on
# a nearly empty document.
#
# DERIVED from the entrypoint's own key list, not a literal. It was `-lt 21`, and a spec that
# legitimately RETIRED a configuration key took the fixture to 20 and failed here — in a script
# that runs in no local gate, on a line two hundred away from the one the spec edited in this same
# file. A hand-written floor is a second copy of a count that is supposed to move, and it only
# ever fails the change that was allowed to move it.
DECLARED=$(
  sed -n "s/^KEYS='\(.*\)'/\1/p" apps/portal/docker/docker-entrypoint.d/40-render-portal-config.sh \
    | tr ' ' '\n' | grep -c .
)
SUPPLIED=$(printf '%s\n' "$EXPECTED_KEYS" | tr ',' '\n' | wc -l | tr -d ' ')
# +1 for `version`, which the document carries and the entrypoint's list does not name.
if [ "$DECLARED" -lt 2 ]; then
  fail "the entrypoint's key list was readable" "parsed $DECLARED keys, so the floor below is not a floor"
elif [ "$SUPPLIED" -ne $((DECLARED + 1)) ]; then
  fail "the fixture supplies the whole document" \
    "$SUPPLIED keys supplied, entrypoint declares $DECLARED (+version), so the check above proves little"
else
  pass "the fixture supplies the whole document ($SUPPLIED keys)"
fi
check_eq "the document's version is the one the browser accepts" "$(jq -r '.version' /tmp/matrix-body)" "1"
# A HEREDOC RENDER PASSES EVERY CHECK ABOVE and breaks on the first value carrying a quote, a
# backslash or a newline — presenting as a blank app, because the loader refuses what it cannot
# parse. This is the assertion the `jq -n --arg` decision exists to satisfy.
check_eq "a value carrying a quote and a backslash round-trips" \
  "$(jq -r '.environment' /tmp/matrix-body)" "$AWKWARD_VALUE"

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

# Sent with the Host an ALB sends, not the fixture's own. Under `Host: localhost:PORT` a
# scheme-and-host redirect is indistinguishable from a relative one, which is the single Host value
# that hides this.
fetch "/assets" -H 'Host: portal.fixture.test'
check_eq "the directory form redirects" "$(status)" "301"
# THE VALUE, not the absence of a port. Deleting `absolute_redirect off` leaves the port suppressed
# by `port_in_redirect off` and downgrades the scheme instead — `http://portal.fixture.test/assets/`
# behind an HTTPS-terminating balancer. An absence check stayed green through exactly that.
check_eq "the redirect is relative, so neither scheme nor port can be wrong" "$(header location)" "/assets/"

section "The responses generated before a location is resolved"
# A malformed request line, a malformed header and an over-long URI are answered by nginx before it
# resolves a location, so the per-location discipline cannot reach them. Measured, they came back
# as HTML with no Cache-Control and not one security header — the exact response shape this whole
# configuration is written to make impossible.
for probe in '--path-as-is /../../etc/passwd' 'long-uri'; do
  if [ "$probe" = "long-uri" ]; then
    long=$(head -c 20000 < /dev/zero | tr '\0' 'a')
    curl -sS --raw -o /tmp/matrix-body -D /tmp/matrix-head "${BASE}/${long}"
    label="an over-long URI"
  else
    curl -sS --raw --path-as-is -o /tmp/matrix-body -D /tmp/matrix-head "${BASE}/../../etc/passwd"
    label="a malformed request"
  fi
  code=$(status)
  if [ "${code:0:1}" != "4" ]; then
    fail "$label is refused" "expected a 4xx, got [$code]"
  else
    pass "$label is refused ($code)"
    assert_security_headers "$label"
    check_eq "$label: cache class" "$(header cache-control)" "no-store"
  fi
done

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

check_probe "every asset js and css has a .gz sibling" \
  "$(probe_image 'cd /usr/share/nginx/html/assets && for f in *.js *.css; do [ -f "$f.gz" ] || echo "missing $f.gz"; done | head -3')"

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
# DETACHED AND BOUNDED, not a foreground run. A container that refuses exits in under a second, so
# a foreground `docker run` reads its status immediately — but the FAILURE case is a container that
# starts and stays up, and in the foreground that hangs the gate until the job's own timeout rather
# than reporting anything. The failure mode a check exists to catch must not be the one that stops
# it reporting.
refusal() {
  local label="$1"; shift
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
  elif [[ "$out" != *"refusing to start"* ]]; then
    fail "$label" "exited $code without saying what it refused: $(echo "$out" | tail -1)"
  else
    local named
    named=$(echo "$out" | grep -o 'refusing to start\..*' | head -1)
    pass "$label (exit $code — ${named:-refused})"
  fi
}

# EVERY required key, one at a time, unset and then empty. Fixing on one of them left the other
# six unproven — and this script, not the unit suite, is what the deploy pipeline runs before it
# pushes to a registry the image cannot be deleted from.
for held_out in "${REQUIRED_ENV[@]}"; do
  case "$held_out" in -e) continue ;; esac
  key="${held_out%%=*}"

  without=()
  for entry in "${REQUIRED_ENV[@]}"; do
    case "$entry" in -e) continue ;; "$held_out") continue ;; esac
    without+=(-e "$entry")
  done

  refusal "$key UNSET" "${without[@]}" -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
  refusal "$key EMPTY" "${without[@]}" -e "${key}=" -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC"
done

# Not "starts and serves connect-src ;", which is a policy that blocks every fetch and presents to
# a user as a network outage rather than as a misconfiguration.
refusal "connect-src EMPTY" "${REQUIRED_ENV[@]}" -e PORTAL_CSP_CONNECT_SRC=
refusal "connect-src UNSET" "${REQUIRED_ENV[@]}"

# THE TWO VALUES SUBSTITUTED INTO NGINX CONFIGURATION, which has no escaping mechanism. Measured
# before these refusals existed: a connect-src carrying a quote truncated the policy after
# `connect-src` — object-src, base-uri, form-action, frame-ancestors and upgrade-insecure-requests
# all gone — and appended a header of its own, on a container that started, reported healthy and
# entered the target group.
refusal "connect-src carrying a quote and a semicolon" "${REQUIRED_ENV[@]}" \
  -e PORTAL_CSP_CONNECT_SRC='self"; add_header X-Injected yes always; #'
refusal "connect-src carrying a newline" "${REQUIRED_ENV[@]}" \
  -e "PORTAL_CSP_CONNECT_SRC=$(printf "'self'\nadd_header X-Injected yes always;")"
# Not one of nginx's eight levels: without this it is either an [emerg] at start naming no
# variable, or — with the right punctuation — the same injection.
refusal "a log level nginx does not have" "${REQUIRED_ENV[@]}" \
  -e PORTAL_CSP_CONNECT_SRC="$CONNECT_SRC" -e PORTAL_LOG_LEVEL=chatty

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
LEAKED=$(docker exec "$NAME" sh -c 'grep -c SENTINEL /tmp/nginx-conf/default.conf; echo "__ran__"' 2>&1)
if [[ "$LEAKED" != *"__ran__"* ]]; then
  fail "no sentinel reached the rendered configuration" "the probe never ran: $LEAKED"
else
  check_eq "no sentinel reached the rendered configuration" "$(printf '%s' "${LEAKED%%__ran__*}" | tr -d '[:space:]')" "0"
fi

printf '\n%s\n' "----------------------------------------"
if [ "$FAILURES" -eq 0 ]; then
  printf 'matrix: %d checks, all passed\n' "$CHECKS"
else
  printf 'matrix: %d checks, %d FAILED\n' "$CHECKS" "$FAILURES"
fi
exit $(( FAILURES > 0 ? 1 : 0 ))
