---
type: Decision
title: "Two credential planes, declared per route, defaulting to the user plane (SPEC-196)"
description: "**Two credential planes, user by default, declared ON THE ROUTE — the failure fails OPEN.** A wrong client *succeeds* against the wrong identity. The plane is a **required field** on the contract's `Route`, a value that is neither of the two **raises**, and the route is set on the way **IN**: a warm container has no fresh context, so cleanup-on-exit alone lets the next request inherit a declaration. **An assume failure is a FAULT, never a denial** — STS says `AccessDenied` for a wrong trust policy, so the layer *wraps* it."
---

> **AMENDED by SPEC-197 (2026-08-27) — the registry became a FIELD, and the guard's teeth moved.**
> `ROUTE_PLANES` is gone. The plane is declared on the route itself (`Route.plane`) in the transport
> contract, and `planes.planes_for()` derives it per call. The decision below is unchanged in every
> respect that matters — two planes, the user plane by default, the dangerous direction one-way —
> but the *mechanism* named in it is not what ships.
>
> The set-equality guard between the table and the dispatch table becomes a **tautology** once one
> derives from the other, so it is retained as a labelled regression tripwire rather than as the
> guard. What carries the guarantee instead: `plane` is a **required** `Literal` field, so a route
> cannot be declared without choosing; and a value that is neither of the two **raises at
> derivation**. That last half is one the set equality could never carry — a typo resolving quietly
> to user-only is indistinguishable from a correct user-only route, and the fail-closed guarantee
> would be gone with nothing to show for it.

**The failure mode fails OPEN, which is the whole reason this is machinery rather than convention.** A helper handing back the wrong client does not error — the call **succeeds**, against the wrong identity, returning right-looking data. There is no symptom to wait for. So: every AWS client comes from exactly one of two constructors, the **user plane** (the caller's assumed session) or the **API plane** (the execution role); the user plane is the default, because the dangerous direction is a user-scoped call escaping onto the execution role; and a route reaches the API plane only by being named in a registry whose keys are guarded for **set equality** against the router's dispatch table, because a hand-maintained list rots.

**The enumeration is an AST sweep, not review.** It forbids `boto3.client`/`resource`/`Session` and any import of `cpcommon.clients` — the second half matters as much as the first, because that module is a cache of *default-credential* clients, exactly the shape that works in every single-user test and serves the execution role's identity in production. The sweep **counts**: the package holds exactly one construction site, since "none outside the layer" is satisfied by a layer building six. It also closes the doors *around* the doors — a private import from the identity layer, and a `UserIdentity` minted anywhere but its own module, which would assume the role as somebody else and pass every test supplying a matching token. Every exemption is by **exact module path**, never a pattern: a pattern exemption silently exempts the next module named similarly.

**The route is set on the way IN, and this is the ordering that fails open when reversed.** The Python runtime does not hand each Lambda invocation a fresh context, so cleanup-on-exit is skipped by any path that does not reach the cleanup — and a route key left behind means the next request on a user-only route reaches the execution role and succeeds. The router sets a sentinel that authorizes nothing as its first statement, before even the public-route check; the exit reset is a second line, not the load-bearing one. The test that catches this is a **sequence** with the exit reset neutered, because while cleanup always runs the two are indistinguishable.

**An assume failure is a FAULT, never a denial, and the wrap is what makes that true.** STS answers `AccessDenied` when the trust policy is wrong — a missing `sts:TagSession` renders, plans, applies and unit-tests green — so an unwrapped error reaching the failure mapping carries that service code and is indistinguishable from the isolation model working. Every user would be told they lack a permission only an operator can restore. The identity layer wraps every STS failure before it leaves, which strips the service response so the failure can only be classified by what it is. **Measured**: swapping the classifier's two branches changes no outcome; removing the wrap changes two.

## History

### 2026-08-27

- **Settled:** SPEC-196.
- **Changed:** SPEC-197 replaced the `ROUTE_PLANES` registry with a required `Route.plane` field that raises on any other value; the decision is unchanged.
