---
type: Decision
title: "The error shape: a machine code, and operator text nobody renders (SPEC-197)"
description: "A failure body is `{\"error\": {code, requestId, detail?}}` with `code` from a closed enum; the browser chooses every user-facing sentence from the code, `detail` is rendered nowhere, and no API code may share a passthrough rule."
---

A failure body is `{"error": {code, requestId, detail?}}` — the only wrapped shape in the API, since
a success body is the payload itself and a `{data: …}` level is one every ported service would strip
forever. `code` is drawn from a closed enum; `detail` is operator text authored at the raise site,
read in a devtools panel and in `logs/`, and **rendered nowhere**.

The browser chooses every user-facing sentence from the code, through `lib/errorMessages.ts`. An API
that returned a sentence for the SPA to display would reverse that quietly, because the sentence
would look fine in every screenshot.

**The trap is a rule written to uphold it.** `CODE_RULES` contains eight `passthrough` rules whose
whole behaviour is *return the service's message unchanged*. If the API ever returned one of those
codes, server text would reach a user through one of the rules protecting against exactly that. The
guard intersects `API_ERROR_CODES` (generated from the Python contract) with `PASSTHROUGH_CODES`
(computed from the rules) — **two derived sets, never two lists** — and covers the two codes the
client mints as a third. Verified by adding a passthrough code to the Python contract and watching
it redden.

**An unrecognised code resolves to the generic sentence, and that is the deploy-skew case rather
than a fallback nobody meets:** the API deploys before the SPA image, so an old bundle *will* meet a
new code. A missing rule is not a crash — it is the generic wording, which is right for an unknown
code and wrong for a known one, and only a guard tells them apart.

One collision surfaced on the way: `InvalidRequest` is both an API code and a code two browser
services already mint. Both resolve to the same generic sentence, so nothing changed for them — but
a **code** rule wins over an engine-message **match** rule, so a fixture sending `InvalidRequest`
with Athena text stopped reaching the column-name hint. The fixture now sends Athena's real
`InvalidRequestException`, which carries no code rule.

## History

### 2026-08-18

- **Settled:** SPEC-197.
