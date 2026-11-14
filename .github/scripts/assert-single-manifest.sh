#!/usr/bin/env bash
# Refuse an image Lambda cannot run: anything but a single manifest.
#
# Docker adds a provenance attestation by default, and an image carrying one is stored, and pushed,
# as an OCI image INDEX. Lambda's UpdateFunctionCode refuses an index for every function, in another
# workflow, after the push has reported success. This runs BEFORE the push, on the built image, so a
# refused shape never reaches a registry it cannot be deleted from.
#
# AN ALLOWLIST, not a denylist: a type nobody expected, or nothing at all, fails closed.
#
# Usage: assert-single-manifest.sh <image>
set -euo pipefail

image="${1:?usage: assert-single-manifest.sh <image>}"
media=$(docker image inspect --format '{{.Descriptor.mediaType}}' "$image")

case "$media" in
  application/vnd.docker.distribution.manifest.v2+json | application/vnd.oci.image.manifest.v1+json)
    echo "$image is a single manifest ($media)."
    ;;
  *)
    echo "::error title=Not a single manifest::$image is '${media}', which Lambda refuses. Build it with --provenance=false --sbom=false." >&2
    exit 1
    ;;
esac
