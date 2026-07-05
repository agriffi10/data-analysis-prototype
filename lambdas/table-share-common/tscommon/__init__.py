"""Shared helpers for the table-share verb Lambdas.

Published as the table-share-common Lambda layer and imported as a package
(from tscommon import auth). It is a package — not flat top-level modules — so its
module names (config/auth/registry) don't collide with shared-space-common's or
tbcommon's when several are imported in one pytest process.

Stubbed namespaces in SPEC-088; filled in by SPEC-089→094 as the verb logic lands.
"""
