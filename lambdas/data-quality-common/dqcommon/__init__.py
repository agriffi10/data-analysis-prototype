"""Domain helpers for the data-quality verb Lambdas, published as a Lambda layer.

Imported as a package (``from dqcommon import config``) rather than flat top-level modules, so
its module names cannot collide with the other layers' under one pytest process.

This layer carries the domain surface only. The shared control-plane surface comes from the
cpcommon layer, which every verb attaches alongside this one.

It declares no external dependencies. PyJWT and cryptography are declared once, in cpcommon.
polars is absent because every heavy computation is Athena's — the one exception is a separate
polars layer attached to inspect-source alone, which must read Parquet footers, since Athena
needs an explicit column list and does not auto-detect a Parquet schema. There is no Excel
engine: this arc does not support Excel, so convert first and check the resulting Parquet.
"""
