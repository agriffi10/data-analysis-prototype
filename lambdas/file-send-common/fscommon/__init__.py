"""Shared helpers for the file-send control-plane verbs, published as a Lambda layer.

Imported as a package (``from fscommon import authz``) so its module names cannot collide
with another domain layer's under one pytest run. Every file-send verb attaches this layer
alongside ``cpcommon``.

The split with ``cpcommon`` is SPEC-156's and is not negotiable per plane: **cpcommon owns
the algorithm, this layer owns file-send's tables and wording**. Nothing here re-implements a
CAS loop, a message resolver, an SQS parser or a token verification — a second copy of one of
those is what SPEC-156 spent a whole spec removing.

This file is deliberately import-free and must stay that way (``test_layer_import_safety``
pins it for every layer). The reason is cold-start cost: an import here runs for every
attaching function whether or not it uses the module.
"""
