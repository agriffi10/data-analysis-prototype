---
type: Decision
title: "The restore guard, and the four choices that make it safe to start a bill (SPEC-170)"
description: "A restore checks every destination before any billed `RestoreObject`, using heads inside the client's pool, destinations derived from the keys, and authorization from the route's space."
---

This heading grouped the decisions below when one file held the area. Each now has a file of its own:

- [The guard is absolute, and it runs before the retrieval](the-guard-is-absolute-and-it-runs-before-the-retrieval.md)
- [The bound is botocore's connection pool, not the thread count](the-bound-is-botocores-connection-pool-not-the-thread-count.md)
- [The lookup reads the KEYS; the record is a cross-check it can do without](the-lookup-reads-the-keys-the-record-is-a-cross-check-it-can-do-without.md)
- [The space comes from the request, and the two ids are different things](the-space-comes-from-the-request-and-the-two-ids-are-different-things.md)
- [One front door, one `Validated` Pass, and two message prefixes](one-front-door-one-validated-pass-and-two-message-prefixes.md)
- [This spec adds no IAM, and that is asserted rather than assumed](this-spec-adds-no-iam-and-that-is-asserted-rather-than-assumed.md)
- [Review closed two holes, and one of them was a silent, unrecoverable deletion](review-closed-two-holes-and-one-of-them-was-a-silent-unrecoverable.md)

## History

### 2026-08-10

- **Settled:** SPEC-170.
