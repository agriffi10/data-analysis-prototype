"""Shared machinery for the portal API: configuration, request context, refusals, identity.

A package rather than flat modules because the API grows a route per ported feature, and the
alternative is a widening set of ``api_*.py`` files at the function root with no boundary
between what a route may reach and what only the framework should.
"""
