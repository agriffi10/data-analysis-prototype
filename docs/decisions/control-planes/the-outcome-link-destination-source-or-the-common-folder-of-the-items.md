---
type: Decision
title: "The outcome link: destination, source, or the common folder of the items' PARENTS (SPEC-191)"
description: "A copy or move that landed anything, `duplicate` included, links to the destination and anything else to the source; a `delete` links to the deepest folder its items' PARENTS share, and the prefix is percent-encoded at mint."
---

A copy or move that landed anything links to the **destination**; anything else links to the
**source**, because that is where the items still are. One message per run means one link, so the
rule is about the run rather than about an item — and a `duplicate` counts as landed, since its
objects *are* at the destination and that is exactly where the user has to look to choose which copy
to keep.

**A `delete` links to the deepest folder its items shared, computed over the items' PARENTS.** Over
the keys themselves, a single-item delete yields the item — linking the user into the folder that
was just removed, an empty listing where a folder used to be. Taking parents first makes the
one-item and many-item cases the same computation. A common prefix is also cut back to its last
slash: two siblings named `report-a` and `report-b` share `report-`, which names no folder.

~~**`?space=` is minted FIRST, and that is not cosmetic.** `NotificationRow` gates the shared-space
variant on the literal `?space=`; the other parameter order slips the gate, the route never reads
the space, resolves the personal one, discards a prefix that does not start with it, and lands the
user in their own files with no banner while the message names a shared space.~~ **— superseded
2026-09-25 by the derived link gate (`docs/decisions/browser/`, *A link is gated by its destination's flags*):**
the row now parses the link, so parameter order no longer decides whether the gate sees the space.
The failure described is still what an ungated space link does; `?space=` still comes first.

**This is the fleet's first link built from an arbitrary KEY**, so the prefix is **percent-encoded**
at mint — every other plane interpolates catalog-constrained names. An unencoded `?`, `#` or `&`
truncates the link into one that resolves elsewhere, and the browser's `isSafeInAppPath` cannot see
it: that guard inspects only the first two characters.

## History

### 2026-09-25

- **Changed:** The derived link gate superseded the rule that `?space=` must come first: the row parses the link, so parameter order no longer decides whether the gate sees the space.

### 2026-08-17

- **Settled:** SPEC-191.
