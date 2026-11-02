---
type: Decision
title: "The API reads the same claims and assumes the same role with the same tag set (SPEC-196)"
description: "**The API assumes the SAME role with the SAME tags from the SAME claims** — one computation over one input, which is why no policy is rewritten. The role is **reused, never minted** (`aws:PrincipalArn` resolves to the *role's* ARN, so the hand-maintained bucket-policy allowlist stays correct), `DurationSeconds` 3600 is a ceiling **both ways** — shorter caps every presigned link, longer is refused as role chaining — and tag-key agreement is **asserted, not structural** — the trust statement's `sts:TagKeys` is a ceiling that **cannot require a tag was stamped**."
---

> **AMENDED since SPEC-202 retired the Identity Pool.** `identity-pool.tf` and its map are gone, so
> there is one credential path, and `lambdas/api/apicommon/identity.py` is the only declaration of
> which claim feeds which tag. The equivalence below is the record of why no policy was rewritten.
> The tag-key paragraph's population has moved too: only `portal-role-permissions.json.tftpl`
> hard-codes `username` now, and `var.principal_tag_key` reaches the trust statement's key list
> and the API's environment as well as the analytics module. The guard is no longer a read-back
> against a declaration AWS applies. It is a pinned copy of the retired map in
> `test_identity_apicommon.py`, the trust-to-template key comparison in
> `test_portal_role_preservation.py`, and the `validation` on the variable.

**The equivalence is not an analogy — it is the same computation over the same input.** `identity-pool.tf` declares which claim feeds which tag: `username` from `cognito:username`, `shared_space_k` from `custom:shared_space_k`, merged into one map because there is only one per (pool, provider). AWS applies that map to the ID token the browser presents. The API is handed **that same token**, verified against the provider's JWKS on every request, and applies **the same map**. Same token, same claims, same tag names, **the same role** — which is why nothing downstream can tell the two credential paths apart, and why **not one IAM policy, bucket policy or Lake Formation grant is rewritten**. A policy sees a session tag, not who stamped it.

**The claim names are the only thing copied from the Identity Pool, and copying them is what makes the preservation provable.** Sourcing the membership tags from the shared-space registry instead would be defensible in isolation and would **break the equivalence**, turning a provable preservation into an argument. What else would break it, precisely: taking a tag value from a header, a query parameter, a body field, an unverified JWT, or a username re-derived from a path segment — and any route that accepts a username or space name and uses it to *select* credentials rather than to *scope* a call made with the caller's own.

**The tag set is the WHOLE tag set, and stamping only `username` fails silently.** Omit the ten slot tags and personal S3, personal Glue, notifications and the file browser all keep working; only shared spaces refuse — for which the app already has a "Refresh access" recovery built for a documented propagation delay, so a missing tag *presents as that delay*. **An unoccupied slot contributes NO tag**, never one with an empty value: an empty value makes a shared-space ARN resolve to the bucket followed by a bare slash, which is a live grant on every key beginning with one, and S3 permits such a key.

**The role is REUSED rather than minted, and that is the single strongest reason.** The user-space bucket policy Denies every principal whose `aws:PrincipalArn` is not on a hand-maintained allowlist that already names this role, and `aws:PrincipalArn` resolves an assumed-role request to the **role's** IAM ARN rather than the session ARN. Assuming the same role keeps the same entry valid; a new role would need a new entry, and this repo has already been bitten by a principal missing from that list.

**`DurationSeconds` is 3600 and it is a ceiling in BOTH directions.** Shorter caps every presigned download link and every multipart upload window at the shorter value — a user-visible regression with no failing test, because a presigned URL dies with the credential that signed it. Longer is refused outright: the function runs on an assumed-role session of its own, so this call is **role chaining**, which AWS caps at one hour and fails rather than clamps.

**A claim set is exactly as fresh as its token, and that is not a new defect.** A membership change takes effect on the next **token refresh** — SPEC-056's documented behaviour, unchanged, because the carrier is unchanged. If anything the new path is marginally fresher: the credential cache is keyed on the tag set, so a refreshed token whose slots changed is a cache miss on the very next request, where Amplify's own credential cache can hold the old credentials for the rest of the hour.

**Agreement between the tag key the API stamps and the key the policies expand is ASSERTED, not structural, and the reason matters.** `var.principal_tag_key` reaches only the analytics module; `portal-role-permissions.json.tftpl`, `portal-role-shared-space.json.tftpl` and `identity-pool.tf` all hard-code the literal. "One variable feeds both, therefore they cannot drift" is **false**, and threading the variable through those templates to make it true would edit templates the preservation claim forbids touching. So the guard is a read-back against the declaration AWS actually applies, plus a `validation` pinning the variable — because a default guards nothing on its own: an empty `TF_VAR` satisfies a required variable *and* overrides a default. A wrong value produces a session whose tags match no statement, which reads as `AccessDenied` everywhere and names nothing.

**The trust statement's conditions are a ceiling, never a floor, and the limit is stated rather than implied.** `ForAllValues:StringEquals` on `sts:TagKeys` bounds which keys may appear; it is satisfied by a subset **and equally by a request carrying none**, so it cannot require that `username` was stamped. It constrains keys and **not values**, and IAM offers no way to constrain a value. The unspoofability argument rests entirely on the value coming from a claim of a signature-verified token. Both actions — `sts:AssumeRole` **and** `sts:TagSession` — are required in the same statement: either alone renders, plans, applies and unit-tests green, then fails at runtime with a refusal naming neither the tag nor the missing action.

## History

### 2026-08-27

- **Settled:** SPEC-196.
