#!/bin/sh
# Renders everything this container needs that is not knowable at build time: the runtime
# configuration document, and the two nginx documents whose only interpolation is the CSP's
# source list. It runs before nginx binds a port, so a container that cannot render one of
# them never becomes healthy and never enters the target group.
#
# THE BASE ENTRYPOINT ABORTS ON A NON-ZERO EXIT HERE. Measured, not assumed: the upstream
# script runs `set -e` and launches each file as a bare simple command inside a
# `find | while read` pipeline, whose status the outer shell then sees. A refusal below stops
# the container with this script's exit code and nginx never starts.
#
# ONE CAVEAT WORTH KNOWING: that loop runs only when the entrypoint's first argument is
# `nginx`. A container definition carrying a `command` skips every script here silently, and
# an `include` matching zero files is not an nginx error — it would start clean and serve
# nothing at all.
set -eu

# The document's keys, named rather than scooped from the environment. A bare
# `CONFIG_*` sweep publishes whatever same-prefixed variable a task definition, a base image
# or an orchestrator introduces — into a world-readable document.
KEYS='apiBaseUrl appUrl awsRegion environment maxUploadBytes cognitoUserPoolId cognitoUserPoolClientId cognitoDomain cognitoIdentityPoolId userSpaceBucket sharedSpaceBucket'

# The ones with no degraded path. A container serving a document without these renders a boot
# failure to every user, so it refuses to serve at all instead.
REQUIRED='apiBaseUrl appUrl awsRegion userSpaceBucket cognitoUserPoolId cognitoUserPoolClientId cognitoDomain'

# The version the browser's loader accepts. It refuses a document whose version differs — it
# does not guess — so a mismatch here is a white screen, not a degraded feature.
VERSION=1

CONF_DIR=/tmp/nginx-conf
TEMPLATE_DIR=/etc/nginx/portal

# ── Refuse first ──────────────────────────────────────────────────────────────
# UNSET AND EMPTY ARE THE SAME FAILURE. An unset repository variable, an unset Terraform input
# and an unsubstituted shell expansion all arrive as the empty string, and a container that
# starts with an empty required value serves a shell that fails every call. `[ -z "${VAR+x}" ]`
# tests only for unset and would pass all three.
#
# Every missing name is collected and reported together: a container that names one variable,
# is fixed, and then names the next costs a deploy cycle per variable.
missing=''
for key in $REQUIRED; do
  eval "value=\${CONFIG_${key}:-}"
  [ -n "$value" ] || missing="$missing CONFIG_${key}"
done
[ -n "${PORTAL_CSP_CONNECT_SRC:-}" ] || missing="$missing PORTAL_CSP_CONNECT_SRC"

if [ -n "$missing" ]; then
  echo "portal: refusing to start. Unset or empty:$missing" >&2
  echo "portal: these arrive from the task definition; an empty value is not a partial" >&2
  echo "portal: configuration, it is a portal that fails every call it makes." >&2
  exit 1
fi

# ── Then refuse what cannot be safely interpolated ────────────────────────────
# THE TWO VALUES BELOW ARE SUBSTITUTED INTO NGINX CONFIGURATION, and nginx configuration has no
# escaping mechanism the way `jq --arg` does. A value carrying a `"` closes the directive it sits
# in and everything after it inside that directive is LOST — for the policy that means
# `object-src`, `base-uri`, `form-action`, `frame-ancestors` and `upgrade-insecure-requests` all
# silently gone — while a trailing `;` starts a new directive of the attacker's choosing and a `#`
# comments out the rest of the line. Measured: the container starts, reports healthy, enters the
# target group, and serves a truncated policy with an injected header.
#
# A value that does NOT parse is barely better: nginx dies with `[emerg]` and no explanation of
# which variable was at fault, which is the generic essential-container exit this whole image is
# written to avoid producing.
#
# So both are validated against what they are allowed to contain, not scanned for what they are
# not. An allowlist cannot be outflanked by a character nobody thought of.

# A CSP source list: hosts, schemes, keywords, wildcards. Nothing else has any business here.
case "$PORTAL_CSP_CONNECT_SRC" in
  *[!A-Za-z0-9\'\:/.\ _*-]*)
    echo "portal: refusing to start. PORTAL_CSP_CONNECT_SRC contains a character that is not" >&2
    echo "portal: valid in a CSP source list. Interpolated into nginx configuration, a quote" >&2
    echo "portal: truncates the policy and a semicolon appends a directive of its own." >&2
    exit 1
    ;;
esac

# nginx's eight levels, named. Anything else is either an [emerg] at start with no attribution, or
# — with the right punctuation — the same injection as above.
case "$PORTAL_LOG_LEVEL" in
  debug|info|notice|warn|error|crit|alert|emerg) ;;
  *)
    echo "portal: refusing to start. PORTAL_LOG_LEVEL is not one of nginx's levels" >&2
    echo "portal: (debug info notice warn error crit alert emerg)." >&2
    exit 1
    ;;
esac

# ── The runtime configuration document ────────────────────────────────────────
# `jq -n --arg`, never a heredoc. A heredoc produces a document that parses today and breaks
# on the first value carrying a `"`, a `\` or a newline — presenting as a blank app, because
# the loader refuses what it cannot parse.
set -- -n --argjson version "$VERSION"
for key in $KEYS; do
  eval "value=\${CONFIG_${key}:-}"
  set -- "$@" --arg "$key" "$value"
done

# Built as an object of exactly the named keys, with the empty ones dropped: the accessor reads
# an absent key and an empty one identically, and a document that omits them says what it means.
FILTER='{version: $version}'
for key in $KEYS; do
  FILTER="${FILTER} + (if \$${key} == \"\" then {} else {${key}: \$${key}} end)"
done

jq "$@" "$FILTER" > /tmp/config.json

# ── The nginx documents ───────────────────────────────────────────────────────
# `envsubst` WITH AN EXPLICIT LIST, which is the whole point. Given no list it substitutes every
# variable it finds a definition for, so a task definition carrying a variable named `uri` or
# `host` would silently blank the nginx runtime variables of the same name and break routing in
# a way no configuration review would catch.
mkdir -p "$CONF_DIR/snippets"
SUBSTITUTE='$PORTAL_CSP_CONNECT_SRC $PORTAL_LOG_LEVEL'
envsubst "$SUBSTITUTE" < "$TEMPLATE_DIR/snippets/security-headers.conf.template" \
  > "$CONF_DIR/snippets/security-headers.conf"
envsubst "$SUBSTITUTE" < "$TEMPLATE_DIR/default.conf.template" \
  > "$CONF_DIR/default.conf"
