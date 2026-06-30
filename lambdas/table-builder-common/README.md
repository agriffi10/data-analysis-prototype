# table-builder-common

Shared helpers for the table-builder verb Lambdas (offline JWT verify, AWS clients,
the shared-spaces registry read, and the best-effort notifications `emit_notification`
helper). **Empty in SPEC-066** — this directory is a placeholder so the module layout
exists; it is filled in by SPEC-067+ as the verb logic lands:

- SPEC-067 — `auth.py` (offline ID-token → actor), `registry.py` (shared-spaces
  membership read)
- SPEC-068 — `s3_listing.py` (paginated list + ignore-rules)
- SPEC-072 — `notify.py` (best-effort `create` emit to the notifications queue)

When this holds production modules, deploy-lambdas.yml will publish them as a
`table-builder-common` Lambda layer (mirroring `shared-space-common`), separate from
the `table-builder-polars` layer that carries polars for `infer-schema`.
