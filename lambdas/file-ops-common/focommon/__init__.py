"""Shared helpers for the file-operations control-plane verbs, published as a Lambda layer.

Imported as a package (``from focommon import authz``) so its module names cannot collide with
another domain layer's under one pytest run. Every file-ops verb attaches this layer alongside
``cpcommon``.

The split with ``cpcommon`` is not negotiable per plane: **cpcommon owns the algorithm, this layer
owns file-ops' tables and wording**. Nothing here re-implements a CAS loop, a message resolver, an
SQS parser, a token verification or a transfer primitive — the lock protocol this plane needs lives
in ``cpcommon.lock``, and ``lock`` below is a binding to it rather than a second copy.

This file is deliberately import-free and must stay that way (``test_layer_import_safety`` pins it
for every layer). The reason is cold-start cost: an import here runs for every attaching function
whether or not it uses the module.
"""
