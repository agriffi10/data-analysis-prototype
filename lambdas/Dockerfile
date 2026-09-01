# One image for the whole Lambda fleet. Dependencies installed once, shared code copied once,
# every function running the same image with a different command.
#
# WHAT THIS REPLACES, and why the replacement is the point: today what a function can import is
# decided at DEPLOY time, by a join between two JSON tables and a literal attach-order loop, and is
# observable nowhere else. A missing layer is a ModuleNotFoundError at the next cold start, in
# production, behind a green suite — which has happened, and lasted nine days. Here it is a
# property of an artefact that can be pulled and run, and the behaviour matrix runs it.
#
# NOTHING IS DEPLOYED FROM THIS YET. No aws_lambda_function is touched by the spec that builds it;
# the fleet still ships as zips with layers, and the cutover is its own change.
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
# The root is the context because the layer table lives at `.github/lambda-layers.json`, outside
# `lambdas/`. Copying the table into `lambdas/` to narrow the context would be a second copy of
# the one declaration this image's shared layout is derived from.
#
# NO NETWORK BEYOND TWO HOSTS. Every layer below reaches the package index or the base image
# registry and nothing else: no curl, no wget, no system package manager, no AWS call. A test
# asserts that, because "reproducible from a clean checkout" is a property nobody would notice
# losing.

FROM public.ecr.aws/lambda/python:3.12@sha256:3f57e489de055cfcd849d91c480bd4d50f95ec6c2a51616d45808dabfcbe105f

# The union of every layer's dependencies plus the shared file, copied first so the install layer
# survives a source-only change. Renamed on the way in because three of the four are called
# `requirements.txt` and a single COPY of all four would collapse them onto one destination.
COPY lambdas/requirements.txt /tmp/requirements/base.txt
COPY lambdas/control-plane-common/requirements.txt /tmp/requirements/cpcommon.txt
COPY lambdas/table-builder-infer-schema/requirements.txt /tmp/requirements/table-builder-polars.txt
COPY lambdas/data-quality-polars/requirements.txt /tmp/requirements/data-quality-polars.txt

# EVERY REQUIREMENT MUST CARRY A VERSION CONSTRAINT, and the build refuses one that does not.
# Not "must be pinned exactly": PyJWT[crypto]>=2.8,<3 is a deliberate range while log-foundry
# ==0.6.0 is exact, and demanding exactness here would be a dependency-policy change smuggled into
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
 && rm -rf /tmp/requirements

# The tree, and the layer table the assembler reads to decide what is shared code.
COPY lambdas /tmp/source/lambdas
COPY .github/lambda-layers.json /tmp/source/.github/lambda-layers.json

# BOTH LAYOUTS, WRITTEN BY ONE MODULE, which is also the module the layout tests import — so the
# image and its guard cannot drift apart. It strips each function directory's own level and
# preserves everything below it, which a COPY cannot express: a recursive copy would carry the ten
# directories that are NOT functions into the task root, where they would shadow the /opt/python
# copies of themselves for every function in the fleet.
#
# The assembler is deleted in the same layer it runs in, so it is not in the shipped image.
RUN python /tmp/source/lambdas/docker/assemble.py /tmp/source "/opt/python" "${LAMBDA_TASK_ROOT}" \
 && rm -rf /tmp/source

# NO CMD, DELIBERATELY. Every function supplies its own command; an image with a default handler
# would let a function that forgot to declare one start and quietly do the wrong thing.
