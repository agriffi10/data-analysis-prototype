# table-share-common

Shared helpers for the table-share verb Lambdas, published as the
`table-share-common` Lambda layer (the `tscommon` package) and attached to all five
verbs by deploy-lambdas.yml — mirroring `table-builder-common`/`tbcommon`.

**Stubbed in SPEC-088** — the namespaces exist so the layer/package layout is stable;
they are filled in as the verb logic lands:

- SPEC-089 — `auth.py` (offline ID-token → actor), `registry.py` (shared-spaces
  registry read: source membership + recipient-space existence), `config.py` env
  validation
- SPEC-090 — source listing/caps helpers in `copy.py` (reusing the tbcommon
  s3-listing approach)
- SPEC-091 — `copy.py` parallel server-side CopyObject (multipart > 5 GiB)
- SPEC-094 — `notify.py` (best-effort `create` emit to the notifications queue)

Decision record: `docs/architecture.md` → *Control Planes → Table Share*.
