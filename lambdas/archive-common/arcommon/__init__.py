"""Shared helpers for the archive control-plane verbs, shipped in the fleet's container image.

Imported as a package (``from arcommon import authz``) so its module names cannot collide with
another domain package's — under one pytest run, and now also on ``/opt/python``, where the image
puts every shared package in ONE directory. Every archive verb can import it; nothing is attached.

The split with ``cpcommon`` is the and is not negotiable per plane: **cpcommon owns the
algorithm, this layer owns archive's tables, key layout and wording**. Nothing here
re-implements a CAS loop, a message resolver, an SQS parser, a token verification or the key
containment rule — containment in particular moved to ``cpcommon.paths`` with this spec rather
than being copied, because this is the third plane to ask the identical question.

This file is deliberately import-free and must stay that way (``test_layer_import_safety`` pins
it for every layer). The reason is cold-start cost: an import here runs for every attaching
function whether or not it uses the module.
"""
