"""Shared helpers for every control-plane verb Lambda (SPEC-107).

Published as the control-plane-common Lambda layer and imported as a package
(from cpcommon import auth). It carries the surface that was duplicated across the
table-builder (tbcommon) and table-share (tscommon) layers — auth / clients / errors /
registry / s3_listing / events plus the notify skeleton, the shared config core, and
the SPEC-106 base message registry — so a JWKS or claim-validation fix lands in ONE
place, not four. Every control-plane verb attaches this layer alongside its domain
layer (tbcommon / tscommon / the future dqcommon / fccommon).

A PACKAGE (python/cpcommon/), not flat modules, so its module names (config/auth/…)
don't collide with the domain layers' or shared-space-common's under one pytest run.

THIS FILE IS DELIBERATELY IMPORT-FREE, and that is a load-bearing property, not tidiness
(SPEC-137 FR-001). config.py _require()s six environment variables AT IMPORT, so anything
imported here runs for every function attaching the layer. Three of them — pre-signup,
post-confirmation and notifications-writer — attach it for ONE module, observability, and
set none of the six. A single import added here breaks all three at cold start, and on
pre-signup that is a Cognito trigger, so it breaks sign-up itself. Pinned by
test_layer_import_safety.py, which imports observability in a subprocess with a scrubbed
environment (in-process cannot see it: conftest.py stamps the six before collection).
"""
