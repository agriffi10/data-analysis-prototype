# User-directory feature (`apps/portal/src/features/user-directory/`)

Part of the component inventory (`docs/component-inventory.md` is the router).
Public surface only — the code is the source of truth; verify signatures before relying on them.

> **The directory is ADVISORY.** It is up to a day stale, it misses users not yet provisioned, and it
> is never an authorization input — the control plane is the authority and already reports an unknown
> name by notification. Nothing here may be used to refuse a name (SPEC-147 FR-005).

| Symbol | File | Purpose |
|---|---|---|
| `getUserDirectory()` | `userDirectory.service.ts` | Reads `_directory/usernames.json` from `userSpaceBucket()` via `withCredentialRetry` + `GetObjectCommand`. FORGIVING: missing, corrupt, unsupported `version` and non-array `usernames` all return an EMPTY success — an unavailable suggestion list means no suggestions, never an error banner. Re-checks every entry against `CATALOG_IDENTIFIER_RE` (the array is rendered into the DOM and used for keys). `ServiceResult<UserDirectory>`, never throws (SPEC-147). |
| `useUserDirectory()` | `useUserDirectory.ts` | `{status, search, generatedAt}`. `search` is a STABLE CALLBACK, not the index — it builds on first call and memoises, so no consumer holds a half-built structure. `staleTime` 1h, `retry: false`, gated on a signed-in user. `status` is `'loading' \| 'ready' \| 'unavailable'`, with errored and empty COLLAPSED into `'unavailable'` so no consumer has to handle both. Returns `[]` unless ready (SPEC-147). |
| `buildIndex(usernames)` / `search(index, query, limit?)` | `usernameTrie.ts` | Pure. One walk builds a character trie (prefix band) plus the flat ordered array the substring band scans. Ranking: exact, then prefix asc, then substring asc; each name once, in its strongest band. The PREFIX band walks and stops early; the SUBSTRING band is a linear scan, short-circuited at `limit` and skipped when the prefix band filled it. Capped at `MAX_INDEXED_USERNAMES` (20,000) with `truncated` set (SPEC-147). |
| `searchWithCost(index, query, limit?)` | `usernameTrie.ts` | `search` + `{nodesVisited, namesScanned}`. Exists so the cost claims are pinned with numbers rather than comments — used by the trie's own tests and nothing else (SPEC-147). |
| `UserDirectory`, `UserDirectoryStatus`, `UsernameSearchResult`, `UsernameIndex`, `UserDirectoryDocument` | `userDirectory.types.ts` | The document shape SPEC-146's builder publishes, what the service returns, and what consumers branch on (SPEC-147). |
| `userDirectoryKeys` | `userDirectoryKeys.ts` | TanStack key factory. ONE key, no arguments — the document is bucket-wide, so nothing about the session changes what is fetched (SPEC-147). |
