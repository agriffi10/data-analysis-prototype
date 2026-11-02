---
type: Decision
title: "A route may carry PATH parameters, and a value that is not one segment is refused in the browser (SPEC-199)"
description: "A route may carry path templates: the browser encodes each segment and the server never unquotes, a value that is not one segment is refused client-side as `UnsendableParameter`, and a missing parameter is a compile error."
---

Four of the six catalog routes name a resource in the path, and the transport could not address one —
`route_for` was a string comparison and `apiRequest` used the generated path verbatim. SPEC-198
sidestepped it by flattening identifiers into the query string; this declares templates, and
SPEC-200/201 inherit the mechanism.

**API Gateway hands the function a percent-decoded path**, measured against the deployed API rather
than assumed (`GET /health%7A` answers 200 — it matched `/healthz`; `GET /healthz%20` answers 401). So
the browser encodes each segment and the server never unquotes.

**A parameter must be ONE segment, and two unrelated mechanisms at two different layers turn a value
into extra structure:** `a/b` survives `encodeURIComponent` as `%2F`, reaches the wire intact and is
decoded by the gateway; `.` and `..` are not encoded at all and never reach the wire, because the URL
parser collapses dot segments when `fetch` reads the string. Either one addresses a template the
caller did not name — `athena.status` asked for `abc/results`, or for `.`, arrives as
`athena.results`. Both answer **200, with a body of the wrong shape, typed as the right one**; a 404
would have been survivable. A first version of the guard refused only the slash, which is the same
defect it was written to prevent.

**The refusal is client-side, and that is about where the check can work rather than about safety.**
The server cannot tell such a path from one a caller legitimately typed — by the time it matches, the
separator is a separator. Both siblings sit on the user plane under the same assumed identity, so a
caller reaches nothing a direct request would not give them. Whether `rawPath` preserves the encoding
and would allow the same check server-side is **not measured**, and the comment says so rather than
implying it was ruled out. It mints its own `UnsendableParameter` code, deliberately not the server's
`InvalidRequest`: reusing that would make a refusal of ours indistinguishable from the API's own, in
the one case where the difference is the whole diagnosis.

**A missing parameter is a COMPILE error, through a conditional rest tuple** rather than an optional
field. As an optional field the omission compiles and the literal `/v1/queries/{queryExecutionId}/stop`
goes on the wire — where the gateway decodes the braces, the matcher **matches**, and Athena is handed
`{queryExecutionId}` as an execution id. A generic wrapper must forward `...args` rather than take an
options object: with the route id still a type variable, TypeScript cannot pick an arm of the
conditional. **Both silent failures of a templated matcher are refused at declaration time** — a
segment carrying a brace that is not a well-formed placeholder (which would 404 every caller while
every type check stayed green, and silently publish no parameters) and two overlapping templates
(which would resolve by declaration order). There is deliberately no literal-beats-template precedence
rule: it would be a second thing to reason about at every future declaration and only ever fires in
the case the refusal makes unreachable.

## History

### 2026-08-29

- **Settled:** SPEC-199.
