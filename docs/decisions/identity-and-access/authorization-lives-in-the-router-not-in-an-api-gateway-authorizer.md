---
type: Decision
title: "Authorization lives in the router, not in an API Gateway authorizer (SPEC-193)"
description: "Authorization lives in the router behind one `$default` route, with no API Gateway authorizer, so one reader judges the token; the API resolves a principal before dispatch and an unidentified caller gets 401 whatever the path."
---

The API serves every path through one `$default` route and one integration. A per-route authorizer
would have to duplicate the route table before it could say anything at all — and, more decisively, it
would be a **second reader of the same token**, able to disagree with the router about the claim the
role assumption is scoped by, with no arbiter between them.

**SHIPPED (SPEC-195, 2026-08-27); the "nothing to authorize" reasoning below is past tense.** The
API resolves a principal before dispatch and refuses any undeclared route — an unidentified caller
gets 401, not 404, whatever path they ask for. The disposition is unchanged and now load-bearing:
the verifier is a module the router calls. The disposition
for `CKV_AWS_309` in `security-baseline.md` is the audit-trail wording, and it rests on the bearer
token — never on the session cookie the arc's re-scope removed.

Detail: `spec-delivery/SPEC-193`.

## History

### 2026-08-27

- **Changed:** SPEC-195 shipped the verifier, so the original nothing-to-authorize reasoning is past tense and the disposition is load-bearing.

### 2026-08-26

- **Settled:** SPEC-193.
