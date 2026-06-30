"""Shared helpers for the table-builder verb Lambdas (SPEC-067+).

Published as the ``table-builder-common`` Lambda LAYER (deploy-lambdas.yml) and
imported by the verb functions as a PACKAGE (``from tbcommon import auth``). It is a
package — not flat top-level modules like ``shared-space-common`` — so the module
names (config/auth/registry) don't collide with shared-space-common's in a single
``pytest lambdas/`` process (both would otherwise land on ``sys.modules['config']``).
"""
