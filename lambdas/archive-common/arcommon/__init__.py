"""Shared helpers for the archive control-plane verbs, published as a Lambda layer.

Imported as a package (``from arcommon import authz``) so its module names cannot collide with
another domain layer's under one pytest run. Every archive verb attaches this layer alongside
``cpcommon``.

The split with ``cpcommon`` is SPEC-156's and is not negotiable per plane: **cpcommon owns the
algorithm, this layer owns archive's tables, key layout and wording**. Nothing here
re-implements a CAS loop, a message resolver, an SQS parser, a token verification or the key
containment rule — containment in particular moved to ``cpcommon.paths`` with this spec rather
than being copied, because this is the third plane to ask the identical question.

This file is deliberately import-free and must stay that way (``test_layer_import_safety`` pins
it for every layer). The reason is cold-start cost: an import here runs for every attaching
function whether or not it uses the module.
"""
