"""Domain helpers for the data-quality verb Lambdas (SPEC-108).

Published as the data-quality-common Lambda layer and imported as a package
(from dqcommon import config). It is a package — not flat top-level modules — so its
module names don't collide with the other layers' under one pytest process.

This layer carries the DOMAIN surface only. The shared control-plane surface (auth,
clients, config core, errors, registry, s3_listing, notify, messages base, events) comes
from the cpcommon layer (SPEC-107), which every verb attaches alongside this one.

It declares NO external dependencies:
  - no PyJWT / cryptography — declared ONCE in cpcommon (SPEC-107 FR-001);
  - no polars — every heavy computation is Athena's. The ONE exception is a separate
    polars layer attached to inspect-source alone, which must read Parquet footers
    (Athena needs an explicit column list and does not auto-detect a Parquet schema);
  - no Excel engine — this arc does not support Excel. Convert it first, then check the
    resulting Parquet.

Namespaces are stubbed in SPEC-108 and filled by the later specs (config/sql/report by
SPEC-110→112, messages by SPEC-114, index_store by SPEC-123).
"""
