---
type: Decision
title: "The URL transformer's encoding is position-dependent, and both simple rules are wrong"
description: "A URL transformer substitutes raw at the template's leading position and encoded everywhere later, and the resolved URL must pass an `https:` allowlist; `isSafeInAppPath` does not apply."
---

Encoding the value **unconditionally** is right inside a path or a query — a value must not climb
out of its segment, add a parameter or graft a fragment on — and wrong at the **start** of the
template, where `${value}` is the natural template for a column that already holds links: encoding
turns every legitimate `https://…` into `https%3A%2F%2F…`, so that column can never link at all. It
also makes FR-006 AC2's own worked example unreachable, since a `javascript:` cell would then fail
as "not a URL" rather than at the scheme check. Not encoding at all is the other wrong rule.

So the **leading** position substitutes raw and every later one is encoded, and the `https:`
allowlist — judged on the **resolved** URL, never the template — is what guards the leading case.
An allowlist rather than a blocklist, because the blocklist is the one that has to be complete.

The substitution is assembled part by part rather than with `String.replace`, whose replacement
string reads `$&`, `$'` and `` $` `` as patterns: a cell holding one would be expanded into
something other than itself *before* anything parsed it. Anchors carry `rel="noopener noreferrer"`
and `target="_blank"`; a refused scheme renders as plain text with its reason reachable.

**`isSafeInAppPath` is deliberately not used, and the call site records why.** That rule
(SPEC-061/167) governs IN-APP paths — it asks whether a link is a route inside this application and
answers by refusing anything not root-relative. Every URL here is external and absolute, so it
would reject all of them, and loosening it would have it answering a question it was never written
for. Reaching for a rule that sounds adjacent is how a confident category error ships.

## History

### 2026-08-14

- **Settled:** entered the register.
