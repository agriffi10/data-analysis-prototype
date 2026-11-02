---
type: Decision
title: "Control-plane table creation = TBAC (SPEC-070/111 correction)"
description: "LF admin status does not grant `CREATE_TABLE`: control-plane roles create tables through the `portal-managed` LF-Tag on every database plus one tag-policy grant per role, with a static per-bucket `DATA_LOCATION_ACCESS` grant for locations."
---

Supersedes "execution role = LF admin ⇒ catalog-wide create". LF data-lake **admin status does NOT grant `CREATE_TABLE`** on a database the admin didn't create — so table-builder/table-share/data-quality (all admins) silently failed to create tables in user/shared DBs. Fix: a single **`portal-managed` LF-Tag** stamped on **every** personal + shared DB at provision time (`post_confirmation.py` / `create_space.py` call `AddLFTagsToResource`; backfill existing DBs via `scripts/backfill-portal-managed-tag.sh`), with **one tag-policy grant per execution role** (DB `CREATE_TABLE`… + inherited table perms) — **not** per-DB named grants. Locations (which LF-Tags can't express) get a **static per-bucket `DATA_LOCATION_ACCESS`** grant (3 roles × user-space + shared buckets). The portal role keeps its named per-DB grant (per-user isolation needs the named ARN). Not-in-scope-to-change: the "per-user isolation = username IAM principal tag, not LF-Tags" decision — that's a *different, per-user* tag. Detail: `infra/modules/analytics/lakeformation.tf`.

## History

### 2026-06-30

- **Settled:** SPEC-070/111 correction.
