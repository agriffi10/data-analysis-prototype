# The portal image: the Next.js standalone server and the files it serves.
#
# The server does the jobs a static origin used to do, and each one fails SILENTLY when it is wrong:
# a missing route handler falls through to the not-found page, so a broken health probe answers HTML
# and a missing configuration document reads as markup; a header set in the wrong place overrides a
# cache class; a policy missing one host breaks one flow days later. The behaviour matrix in CI is
# what makes each of those able to fail.
#
# EVERY BASE IS PINNED BY DIGEST, not by tag. A tag is mutable, so a rebuild of an unchanged commit
# can produce a different image, which makes "the sha identifies what is running" false, and that
# claim is the entire reason the pipeline tags by commit sha.

FROM node:24-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS build

WORKDIR /src

# The workspace root's manifests, so the install layer survives a source-only change.
COPY package.json package-lock.json ./
COPY apps/portal/package.json apps/portal/
RUN npm ci

COPY . .

# No configuration is built in. Every value a deployed portal reads arrives at runtime, in the
# server's environment, and the start-time check that refuses an incomplete one never runs here.
RUN npm run build -w apps/portal

# The context is the repository root, so the ignore file that keeps a developer's .env out of it
# lives there too, and a .dockerignore beside this file would be read by nothing. Asserted here, in
# the stage that can see the context: the runtime stage copies only the build's output and so could
# never fail this check no matter what leaked.
RUN test ! -e .env && test ! -e apps/portal/.env && test ! -e apps/portal/.env.local \
 && test ! -d infra && test ! -d lambdas && test ! -d .git \
 || (echo "the build context carries files /.dockerignore should have excluded" >&2 && exit 1)

FROM node:24-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df

# Re-declared, because ARG does not cross a stage boundary. Without this line both the label and
# the environment variable below resolve to the empty string, and an equality check between them
# passes as "" == "": green, and false.
ARG BUILD_VERSION

LABEL org.opencontainers.image.revision="${BUILD_VERSION}"

# HOSTNAME is the address the server binds, not the machine's name: unset, Next binds whatever the
# platform puts in HOSTNAME, which is not every interface. Telemetry is off so a client environment
# never calls out on the framework's behalf. NODE_ENV is not set here: the standalone server sets it
# itself, and stating it in this file is what lambdas/test_local_install_guard.py refuses, for the
# build stage's sake.
ENV BUILD_VERSION="${BUILD_VERSION}" \
    PORT=8080 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

# The standalone server and the only modules it needs, then the two trees Next leaves for the
# deployer to place: the hashed assets and `public/`. Owned by root and read-only to the server,
# which writes nothing but its temp directory, and that arrives as a tmpfs mount.
COPY --from=build /src/apps/portal/.next/standalone/ ./
COPY --from=build /src/apps/portal/.next/static ./apps/portal/.next/static
COPY --from=build /src/apps/portal/public ./apps/portal/public
COPY --from=build /src/apps/portal/server-guard.cjs ./apps/portal/server-guard.cjs

# The node base image's own unprivileged user, the same uid the task definition sets and names in
# its tmpfs mount option, because a mount owned by anyone else is silently unwritable.
USER 1000

EXPOSE 8080

# The guard starts Next's standalone server behind it: it answers a path whose percent-escape does
# not decode, a request target that is not a path, every WebSocket upgrade and every server-action
# request with a 400 carrying the security headers, where Next would answer a bare 500, an off-site
# redirect, nothing at all, or its action handler's error.
CMD ["node", "apps/portal/server-guard.cjs"]
