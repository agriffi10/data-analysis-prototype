# The SPA image: a Vite build served by nginx. That is the whole of it, and the triviality is the
# trap — the distribution this replaces was doing five other jobs, each configured once and then
# invisible, and every one of them fails SILENTLY when it is wrong. A missing fallback breaks only
# deep links and only on reload; a wrong cache header runs last week's bundle intermittently, on
# exactly the users whose cache is warm; a CSP missing one host breaks one flow days later; a health
# check that falls through to the shell makes the balancer call a broken container healthy and keep
# it in rotation. The behaviour matrix in CI is what makes each of those able to fail.
#
# EVERY BASE IS PINNED BY DIGEST, not by tag. A tag is mutable, so a rebuild of an unchanged commit
# can produce a different image — which makes "the sha identifies what is running" false, and that
# claim is the entire reason the pipeline tags by commit sha.

FROM node:24-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build

WORKDIR /src

# The workspace root's manifests, so the install layer survives a source-only change.
COPY package.json package-lock.json ./
COPY apps/portal/package.json apps/portal/
RUN npm ci

COPY . .

# NOT baked into the bundle. Every value a deployed portal reads arrives at runtime from
# /config.json; these exist only so the build's own dev-fallback table resolves. The bundle is
# asserted elsewhere to carry no VITE_ name at all.
RUN npm run build -w apps/portal

# Pre-compress at build time rather than per request: every compressible asset gets a
# maximum-ratio artefact with no CPU cost at serve time. `-k` keeps the original, because a client
# that does not send `Accept-Encoding: gzip` still has to be served.
RUN find apps/portal/dist/assets -type f \( -name '*.js' -o -name '*.css' \) \
      -exec gzip -9 -k {} + \
 && echo "pre-compressed $(find apps/portal/dist/assets -name '*.gz' | wc -l) assets"

# The context is the repository root, so the ignore file that keeps a developer's .env out of it
# lives there too — a .dockerignore beside this file would be read by nothing. Asserted here, in
# the stage that can actually see the context: the runtime stage copies only dist/ and so could
# never fail this check no matter what leaked.
RUN test ! -e .env && test ! -e apps/portal/.env && test ! -e apps/portal/.env.local \
 && test ! -d infra && test ! -d lambdas && test ! -d .git \
 || (echo "the build context carries files /.dockerignore should have excluded" >&2 && exit 1)

# jq, for the entrypoint's rendering. Taken from a pinned scratch image rather than installed with
# apk, so the build reaches only the registries named in this file and the npm registry — an
# `apk add` would add a third network dependency that no digest pins.
FROM ghcr.io/jqlang/jq:1.8.1@sha256:4f34c6d23f4b1372ac789752cc955dc67c2ae177eb1b5860b75cdc5091ce6f91 AS jq

# The runtime base is nginx-unprivileged, NOT stock nginx plus a hand-written USER. The stock
# image's entrypoint writes /var/cache/nginx and binds :80 as root before dropping privileges, so a
# bare USER produces a container that fails at start for reasons that read as configuration errors.
# This one listens on 8080 as uid 101 by construction — the same uid the task definition sets and
# names in every tmpfs mount option, because a mount owned by anyone else is silently unwritable by
# the process that has to write to it.
FROM nginxinc/nginx-unprivileged:1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0

# Re-declared, because ARG does not cross a stage boundary. Without this line both the label and
# the environment variable below resolve to the empty string, and an equality check between them
# passes as "" == "" — green, and false.
ARG BUILD_VERSION

LABEL org.opencontainers.image.revision="${BUILD_VERSION}"

ENV BUILD_VERSION="${BUILD_VERSION}"

# nginx's error_log level. The only other thing the entrypoint interpolates, and it has a default
# here so an unset value is never a refusal.
ENV PORTAL_LOG_LEVEL=warn

USER root

# The base image's own default site, removed. It also listens on 8080 with no security headers, so
# whichever server parses first would win — see nginx.conf, which drops the include as well.
RUN rm -f /etc/nginx/conf.d/default.conf

COPY --from=jq /jq /usr/local/bin/jq

# Run it here, in the image that has to run it, so a binary incompatible with musl fails the BUILD
# rather than the deploy — where it would surface as `exec: jq: not found` on Fargate.
RUN jq --version

COPY apps/portal/docker/nginx.conf /etc/nginx/nginx.conf
COPY apps/portal/docker/portal/ /etc/nginx/portal/
COPY apps/portal/docker/docker-entrypoint.d/ /docker-entrypoint.d/
RUN chmod +x /docker-entrypoint.d/*.sh

COPY --from=build /src/apps/portal/dist/ /usr/share/nginx/html/

# The two writable paths, and the ONLY two. They arrive as tmpfs mounts created owned by this
# image's user; nothing here prepares them and nothing should. A task-level volume was tried and
# cannot work — it arrives empty and root-owned and does not initialise from the image, so seeding
# a directory here changes nothing. The rendered configuration and the pid go under /tmp; nginx's
# own temp paths go under /var/cache/nginx.
EXPOSE 8080
USER 101
