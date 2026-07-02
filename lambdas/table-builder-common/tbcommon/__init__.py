"""Shared helpers for the table-builder verb Lambdas.

Published as the table-builder-common Lambda layer and imported as a package
(from tbcommon import auth). It is a package — not flat top-level modules — so its
module names (config/auth/registry) don't collide with shared-space-common's when
both are imported in one pytest process.
"""
