"""Shared helpers for every control-plane verb Lambda, shipped in the fleet's container image.

Imported as a package (``from cpcommon import auth``) so its module names cannot collide with the
domain packages' — under one pytest run, and on ``/opt/python``, where the image puts every shared
package in ONE directory.

This file is deliberately import-free and must stay that way. The original reason has expired:
``config`` used to ``_require`` six environment variables at import, and some functions did not set
them all, so an import added here broke them at cold start. What replaces it is cold-start COST,
and the image makes that argument stronger rather than weaker — every function in the fleet runs
this image and resolves this package, so an import here is paid by all of them whether or not they
use the module. ``type_mapping`` imports polars, which the image installs for everyone, so what an
import here would cost is no longer megabytes but every function's cold start. Pinned by
``lambdas/info/shared-layer.md``.
"""
