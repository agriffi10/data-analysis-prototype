"""Shared helpers for every control-plane verb Lambda, published as a Lambda layer.

Imported as a package (``from cpcommon import auth``) so its module names cannot collide
with the domain layers' under one pytest run. Every control-plane verb attaches this layer
alongside its domain layer (tbcommon / tscommon / dqcommon / shared-space-common).

This file is deliberately import-free and must stay that way: ``config`` reads six
environment variables at import time, and three functions attach the layer for
``observability`` alone without setting any of them. An import added here breaks them at
cold start — on pre-signup that breaks sign-up itself. Pinned by
``test_layer_import_safety.py``; see ``docs/lambda-rationale.md``.
"""
