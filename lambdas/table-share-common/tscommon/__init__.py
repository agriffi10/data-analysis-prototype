"""Shared helpers for the table-share verb Lambdas, published as a Lambda layer.

Imported as a package (``from tscommon import notify``) rather than flat top-level modules,
so its module names cannot collide with the other layers' when several are imported in one
pytest process.
"""
