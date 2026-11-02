---
type: Decision
title: "User-facing error messaging (SPEC-106)"
description: "**Raw AWS/Cognito text is NEVER shown, and Athena's only as a failed query's closed Details.** `lib/errorMessages.ts` is the single source of wording; never render `error.message`. The Details come from a CLOSED list of user-SQL error classes, refused on any locator — a class pattern would admit `HIVE_*` split errors, which name S3 objects. Three classes quote cell values, safe only while grants are table- or column-grained: **revisit them before any row filter ships.**"
---

> **Superseded in part:** a query that failed on the user's own SQL now shows Athena's message
> beneath the sentence, in a closed Details disclosure. The amendment below this entry.

Raw AWS/Cognito/Athena text is **never** shown to a user. One SPA mapping module (`lib/errorMessages.ts` `toUserMessage`) is the single source of error wording — app code → AWS/Cognito name → Athena pattern → generic "Contact the Administrator" fallback; never render `error.message` directly (route it through the mapper at the code-in-scope boundary). App-level `ToastProvider`/`useToast` + `ErrorBanner` replace per-page toasts; dev-only original-error log (`import.meta.env.DEV`). Lambda control planes (tb/tscommon, shared-space create/delete) emit friendly failure notifications + cache `reason`, keeping raw text in logs + the SFN/registry record. Detail: `spec-delivery/SPEC-106`.

**Amended: a query that failed on the user's own SQL shows Athena's message, behind Details.**
Testers could not tell what was wrong: a syntax error lost its line and column, and a type mismatch
or an unknown function fell to "Contact the Administrator", the sentence reserved for what a user
cannot act on. An error in the user's own SQL describes what they typed, not AWS, so `toUserMessage`
returns it as `detail` for a `FAILED` execution, and the banner shows it in a closed Details
disclosure beneath the unchanged sentence. What keeps it safe is a **closed list** of Trino classes
(`SYNTAX_ERROR`, `COLUMN_NOT_FOUND`, `TYPE_MISMATCH` and the rest) plus a bare `line N:M:` parse
position, then a second, fail-closed check over the whole text before a 500-character cap, refusing
any `s3://`, `arn:`, 12-digit number, `Service:`, `Request ID` or permission wording. A class pattern
would admit `HIVE_*` split errors, which name S3 objects, and `NOT_SUPPORTED` stays out as the
connectors' catch-all. Athena appends "or requester is not authorized to access requested resources"
to every `COLUMN_NOT_FOUND`; that clause is removed before the permission check, or every missing
column would lose its Details. A statement refused at submit (`QuerySyntaxError`) has none, since the
API does not relay the engine's text for it, and toasts (create view, drop, View DDL) render none.
`INVALID_CAST_ARGUMENT`, `INVALID_FUNCTION_ARGUMENT` and `NUMERIC_VALUE_OUT_OF_RANGE` quote the cell
value that failed. That is data the caller can already select while Lake Formation grants are per
table or column, but a data cell filter with a row predicate would change it: if the engine
evaluated the user's predicate before the row filter, Details would print a value from a row the
user cannot see. Not verified either way, so it is a precondition on that work, not a defect today.

## History

### 2026-07-08

- **Settled:** SPEC-106.
