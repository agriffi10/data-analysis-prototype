"""Shared helpers for every control-plane verb Lambda, published as a Lambda layer.

Imported as a package (``from cpcommon import auth``) so its module names cannot collide
with the domain layers' under one pytest run. Every control-plane verb attaches this layer
alongside its domain layer (tbcommon / tscommon / dqcommon / shared-space-common).

This file is deliberately import-free and must stay that way. The original reason expired in
``config`` used to ``_require`` six environment variables at import, and three
functions attach the layer without setting them all, so an import added here broke them at
cold start — and the reason that replaces it is cold-start COST. An import here runs for every
attaching function whether or not it uses the module, on the layer that attaches to all of
them; ``type_mapping`` alone would pull polars onto fifteen verbs. Pinned by
``test_layer_import_safety.py``; see ``lambdas/info/shared-layer.md``.
"""
