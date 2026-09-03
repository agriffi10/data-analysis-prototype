"""Domain helpers for the data-quality verb Lambdas, shipped in the fleet's container image.

Imported as a package (``from dqcommon import config``) rather than flat top-level modules, so its
module names cannot collide with the other shared packages' — under one pytest process, and on
``/opt/python``, where the image puts them all in ONE directory.

This package carries the domain surface only; the shared control-plane surface is ``cpcommon``,
which every verb imports alongside it.

It declares no external dependencies of its own. PyJWT and cryptography are declared once, in
cpcommon. polars is declared for ``inspect-source``, which must read Parquet footers since Athena
needs an explicit column list and does not auto-detect a Parquet schema. **The image installs every
requirements file into one site-packages, so polars is importable by every function** — the
per-function isolation a separate layer used to give is gone, and only the declaration says who is
meant to use it. There is no Excel engine: this arc does not support Excel, so convert first and
check the resulting Parquet.
"""
