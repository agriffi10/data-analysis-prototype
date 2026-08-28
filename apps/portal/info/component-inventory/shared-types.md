# Shared types (`apps/portal/src/types/`)

Part of the component inventory (`INDEX.md`, beside this file, is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.


| Symbol | File | Purpose |
|---|---|---|
| `API_ROUTES`, `API_ERROR_CODES`, `ApiRouteId`, `RequestOf<R>`, `ResponseOf<R>` | `types/apiContract.generated.ts` | GENERATED from `lambdas/api/apicommon/contract.py` — do not edit. CI refuses a regeneration diff and `tsc -b` fails at every call site on a changed type. Prettier-ignored, ESLint-ignored and coverage-excluded, because a formatter reformatting a file no human wrote is a diff the regeneration gate then rejects. |
| `ServiceResult<T>` | `types/service.types.ts` | The canonical discriminated-union result for every service fn (success/data \| error). |
| `S3FileItem`, `S3FolderItem`, `S3Item` | `types/s3.types.ts` | Listing row shapes. |
| `FileList`, `FileListPage` | `types/s3.types.ts` | Listing + one paginated page (with `isTruncated`/`nextContinuationToken`). |
| `RuntimeConfigDocument`, `RuntimeConfigKey`, `RuntimeConfigLoad` (+ `REQUIRED_CONFIG` / `OPTIONAL_CONFIG`) | `types/runtimeConfig.types.ts` | The `/config.json` shape and the 20-key classification that decides what boots. Deliberately NOT a `ServiceResult`: the loader returns a machine reason, and the boot failure's wording comes from `toUserMessage` at the render site (SPEC-192). |
