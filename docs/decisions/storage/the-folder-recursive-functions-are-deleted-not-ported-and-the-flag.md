---
type: Decision
title: "The folder-recursive functions are deleted, not ported, and the flag stops being a fallback (SPEC-198)"
description: "**The four folder-recursive browser functions are DELETED, not ported** — that loop belongs on the plane. So `asyncFileOperations` off makes a folder **unavailable** — and any multi-item selection too, since the gate refuses every shape the routing rule sends to the plane — refused **at the control**: Copy, Move and Delete are `aria-disabled` with the reason. The services' **per-item** `PlaneRequired` refusal, which lets the files beside a folder go through, is reachable only past the control: a copy or move whose destination resolves to no known space, or any gesture confirmed after the flag turned off while its dialog was open — the control decides when it renders, `dispatch` when it runs."
---

`deleteObjects`, `deleteFolder`, `moveFolder` and `copyFolder` are **gone from the browser**, along
with `listAllKeysUnderPrefix`, `deleteInBatches` and their `onProgress(processed, total)` shape.
Arc A moved every operation whose cost grows with object count onto a control plane; porting these
would have recreated that loop inside a Lambda under a 29-second integration ceiling, and it would
have worked — for small folders, in every test anyone writes.

**`asyncFileOperations` therefore switches a capability off rather than to a slower route.** It used
to be a fallback: with it off, a folder copy, move or delete ran in the browser instead. With the
browser's recursive primitives gone there is nothing to fall back to, so a folder operation is now
~~**refused per item**, with the files selected alongside it still going through~~ **— corrected:
the same change refuses it at the control.** With the flag off, a folder or any multi-item
selection leaves Copy, Move and Delete `aria-disabled` with a reason that does not promise "later"
(`planeReasonFor` in `useFileBrowserDialogs`, pinned for a folder Delete by
`fileOpsDispatch.test.tsx`). The multi-item half is not the deletion's doing: it is the gate
refusing every shape the routing rule sends to the plane. `deleteObjects` went with the recursive
functions, so a multi-file delete is a loop of single deletes — which is what copy and move already
were — though a gesture reaches it with more than one item only through the race below: the
control refuses such a selection with the flag off, and the plane takes it with the flag on.

~~**The refusal is per item, not per request, and that is the whole design of it.** A whole-selection
refusal would lose the files a user picked beside the folder.~~ **— corrected:** the per-item refusal
is the services' half, and the control refuses the whole selection before it when the flag is off —
a folder delete that reached the confirm would ask *"Delete the folder “…” and everything inside
it?"* and then delete nothing. Where the per-item refusal is reached, it still keeps the files picked
beside the folder. The message names the folders that did not move; the code is `PlaneRequired`,
which is authored wording rather than passthrough, because every occurrence says the same thing.

~~**Two paths reach it, and the second is easy to miss.** `useFileBrowserDialogs`'s `routesToPlane`
returns false when the flag is off *and* when a chosen destination resolves to no known space — so
the refusal is reachable with the flag ON.~~ **— corrected: two paths reach it, and neither goes
through the control** — a copy or move whose chosen destination resolves to no known space, which
`dispatch` runs in the browser with the flag ON; and any gesture confirmed after the flag turned
off while its dialog was open, because the control decides when it renders and `dispatch` reads
the flag again when it runs. Recorded because a reader checking only the flag would conclude the
path is dead in production.

## History

### 2026-08-29

- **Settled:** SPEC-198.
