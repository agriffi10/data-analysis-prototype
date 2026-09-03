"""Shared helpers for the table-builder verb Lambdas, shipped in the fleet's container image.

Imported as a package (``from tbcommon import notify``) rather than flat top-level modules, so its
module names cannot collide with the other shared packages' — when several are imported in one
pytest process, and on ``/opt/python``, where the image puts them all in ONE directory.
"""
