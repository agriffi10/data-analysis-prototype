# One image for the whole Lambda fleet. Dependencies installed once, shared code copied once,
# every function running the same image with a different command.
#
# WHAT THIS REPLACED, and why the replacement was the point: what a function could import used to
# be decided at DEPLOY time, by a join between two JSON tables and a literal attach-order loop, and
# was observable nowhere else. A missing layer was a ModuleNotFoundError at the next cold start, in
# production, behind a green suite — which happened, and lasted nine days. Here it is a property of
# an artefact that can be pulled and run, and the behaviour matrix runs it.
#
# THE WHOLE FLEET RUNS THIS IMAGE. Every function's `package_type` is `Image`, no function attaches
# a layer, and the tables, the layer build and the attach loop are deleted. Nothing in this
# repository can produce a zip-packaged Lambda any more.
#
# THE BASE IS PINNED BY DIGEST, not by tag, for the reason the SPA image states: a tag is mutable,
# so a rebuild of an unchanged commit could produce a different image — which makes "the sha
# identifies what is running" false, and that claim is the entire reason the pipeline tags by
# commit sha.
#
# THE BUILD CONTEXT IS THE REPOSITORY ROOT, and the ignore file that applies is
# `lambdas/Dockerfile.dockerignore` rather than the root `.dockerignore`. BuildKit reads
# `<dockerfile-path>.dockerignore` when one exists and falls back to the context root's otherwise
# — measured, not assumed, because the whole layout depends on it. The root file excludes
# `lambdas` and `infra` deliberately, to keep them out of the SPA's context (whose build asserts
# their absence), so this build needs its own. `apps/portal/Dockerfile` has no sibling ignore
# file and is therefore untouched by any of this.
#
# THE ROOT IS THE CONTEXT AND NOTHING OUTSIDE `lambdas/` IS COPIED ANY MORE. It used to be the
# context because the layer table sat at `.github/lambda-layers.json`, outside `lambdas/`, and the
# assembler read it; the table is gone and the assembler reads the tree. Narrowing the context to
# `lambdas/` is therefore possible and is deliberately NOT done here: it would move every path in
# every COPY below, in the one change whose whole claim is that the image's contents do not move.
# It is a change worth making on its own, where a byte-for-byte comparison of the two images is
# the evidence rather than a side effect.
#
# NO NETWORK BEYOND TWO HOSTS. Every layer below reaches the package index or the base image
# registry and nothing else: no curl, no wget, no system package manager, no AWS call. A test
# asserts that, because "reproducible from a clean checkout" is a property nobody would notice
# losing.

FROM public.ecr.aws/lambda/python:3.12@sha256:3f57e489de055cfcd849d91c480bd4d50f95ec6c2a51616d45808dabfcbe105f

# The union of every shared source's dependencies plus the fleet-wide file, copied first so the
# install layer survives a source-only change. Renamed on the way in because four of the five are called
# `requirements.txt` and a single COPY of all five would collapse them onto one destination.
#
# EVERY REQUIREMENTS FILE UNDER lambdas/ MUST BE NAMED HERE, TWICE — once in a COPY and once in
# the install below. Nothing derives this list from the tree, so a new file that is not added is
# not installed, and the function that needed it fails at the moment a user first reaches the
# code path that imports it.
COPY lambdas/requirements.txt /tmp/requirements/base.txt
COPY lambdas/control-plane-common/requirements.txt /tmp/requirements/cpcommon.txt
COPY lambdas/table-builder-infer-schema/requirements.txt /tmp/requirements/table-builder-polars.txt
COPY lambdas/data-quality-polars/requirements.txt /tmp/requirements/data-quality-polars.txt
COPY lambdas/results-conversion-convert/requirements.txt /tmp/requirements/results-conversion-convert.txt

# EVERY REQUIREMENT MUST CARRY A VERSION CONSTRAINT, and the build refuses one that does not.
# Not "must be pinned exactly": PyJWT[crypto]>=2.8,<3 is a deliberate range while log-foundry
# ==1.0.0 is exact, and demanding exactness here would be a dependency-policy change smuggled into
# a packaging one. The check runs in Python because this image has no `find` and no `xargs` — the
# obvious shell version of it exits 127.
#
# NOT PIPED. `pip install … | tail` reports the exit status of `tail`, so a failed install would
# produce an image missing its dependencies and a build that reported success.
#
# The line is cut at `#` and `;` before it is matched, because a requirement's TRAILING COMMENT or
# its environment marker can carry the very characters the check looks for — `polars  # pinned to
# ==1.12.0 elsewhere` and `polars ; python_version < "3.13"` both read as constrained otherwise,
# and both are ordinary things to write.
RUN python -c "\
import pathlib, re, sys; \
lines = [(p.name, n, l.strip()) \
         for p in sorted(pathlib.Path('/tmp/requirements').iterdir()) \
         for n, l in enumerate(p.read_text().splitlines(), 1) \
         if l.strip() and not l.strip().startswith('#')]; \
spec = lambda l: l.split('#')[0].split(';')[0]; \
loose = [(f, n, l) for f, n, l in lines if not re.search(r'[<>=~!]=|[<>]', spec(l))]; \
sys.exit('\n'.join(f'{f}:{n} {l!r} carries no version constraint' for f, n, l in loose)) \
    if loose else print(f'{len(lines)} requirement(s), all constrained')" \
 && pip install --no-cache-dir \
      --requirement /tmp/requirements/base.txt \
      --requirement /tmp/requirements/cpcommon.txt \
      --requirement /tmp/requirements/table-builder-polars.txt \
      --requirement /tmp/requirements/data-quality-polars.txt \
      --requirement /tmp/requirements/results-conversion-convert.txt \
 && rm -rf /tmp/requirements

# The tree. What is shared code and what is a function is decided by the assembler from the tree
# itself, so this is the whole of the build's input.
COPY lambdas /tmp/source/lambdas

# BOTH LAYOUTS, WRITTEN BY ONE MODULE, which is also the module the layout tests import — so the
# image and its guard cannot drift apart. It strips each function directory's own level and
# preserves everything below it, which a COPY cannot express: a recursive copy would carry the
# directories that are NOT functions into the task root, where the shared sources among them would
# shadow the /opt/python copies of themselves for every function in the fleet.
#
# The assembler is deleted in the same layer it runs in, so it is not in the shipped image.
RUN python /tmp/source/lambdas/docker/assemble.py /tmp/source "/opt/python" "${LAMBDA_TASK_ROOT}" \
 && rm -rf /tmp/source

# THE BUILD STAMP, AS A FILE IN THE TASK ROOT rather than an environment variable. That is not a
# style choice — it is the only place it can live. Tofu owns each function's environment map and
# `update-function-configuration --environment` replaces it whole, so an env-borne version would
# either race an apply or be reverted by the next one; a test in test_api_module.py forbids
# Terraform setting it for exactly that reason. `cpcommon.observability._build_version` already
# reads `$LAMBDA_TASK_ROOT/BUILD_VERSION` — the path the zip pipeline wrote — so putting the file
# there needed no code change at all, and the zip and container fleets answered the same way while
# both existed.
#
# LAST LAYER ON PURPOSE: the argument changes on every commit, so anything below it would rebuild
# every time. The dependency install and the assemble step above stay cached.
#
# The ARG is declared AFTER `FROM`. One before it is scoped to the FROM line alone and would
# expand to nothing here — the trap spa-image-matrix.sh records for its own multi-stage build,
# which this single-stage one does not have but would fail the same way.
ARG BUILD_VERSION=""
RUN printf '%s' "${BUILD_VERSION}" > "${LAMBDA_TASK_ROOT}/BUILD_VERSION"

# NO CMD, DELIBERATELY. Every function supplies its own command; an image with a default handler
# would let a function that forgot to declare one start and quietly do the wrong thing.
