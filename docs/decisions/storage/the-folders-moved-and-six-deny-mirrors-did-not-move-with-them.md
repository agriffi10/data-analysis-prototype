---
type: Decision
title: "The folders moved, and six Deny mirrors did not move with them (SPEC-220)"
description: "**A rule that mirrors a SHARED-bucket Deny scans segments, and it must scan for the folder's segments rather than its NAME.** The shared Denies put a wildcard where the space name goes and an S3 resource wildcard matches `/`, so they reach the folder at any depth — which is why these rules exist. Six of them were written as `name in segments`, fed by no builder, and every one silently outlived the move: the Deny became `*/system_settings/archive/*` while they went on refusing `finance/archive/`, a folder that is now the user's. **This class fails SAFE**, which is what let it sit unnoticed behind a green suite — a pair test that only asserts the refusal cannot see it, and only a row expecting `null` at the retired name can. They all read `app_managed_segments` now."
---

`athenaresults/` and the receipt folder now sit under `system_settings/`; their objects were copied
and the sources deleted (`finish` run `34415666578`, 788 deleted, 0 refused; `prove-empty`
`34415782105`), and the old-anchor statements came out. `shared_tables/` did **not** move — those
tables were sent to the space and are the user's to edit — so it keeps its depth-one anchors and the
`system_settings/shared_tables/` ones SPEC-219 added additively came out instead. A depth-one
**Allow** came out too: results-conversion held `s3:GetObject` on `*/athenaresults/*`, and every
other anchor removed was a Deny, so that one's survival would have been an escalation over a path
the narrowing makes ordinary rather than a de-restriction.

**The builders carried the anchored rules; they did not carry the any-depth ones.** A rule mirroring
a SHARED-bucket Deny cannot compare a prefix — the Deny's wildcard sits where the space name goes and
matches `/`, so it reaches the folder at any depth — so it scans segments instead. Six did, and all
six scanned for the bare folder NAME, fed by no builder: `writeLockedPrefix.ts`,
`focommon.protected._is_at_or_below`, `focommon.delete.assert_item_deletable`,
`apicommon.protected._is_write_locked`, `arcommon.plan._assert_deletable_folder` and
`rccommon.paths.protected_refusal`. After the move each refused writes, deletes and archives IAM
permits, in a folder the user made and called `archive`.

**Five were found by chasing one reviewer finding through the tree; the sixth was found by a
security review AFTER the count had been written down.** It was the worst of them: `results-conversion`
refused a destination the browser's picker had just started offering, so *Save results* could send a
user to a folder the plane would reject. Enumerate such a population from the tree, never from the
instances that happen to redden a test — the safe-failing ones redden nothing.

**The reason it survived a green suite is the direction it fails in.** Over-refusal produces no
error anyone reports — a control greys out — and every pair test asserted only that the refusal
happened. So the pair tests were **inverted rather than collapsed**: each keeps two rows, and the
retired home's row expects `null`. A single row would pass just as happily against a rule still
anchored at depth one, which is the regression the narrowing can introduce. `app_managed_segments`
is now the one home for the segment form, as `app_managed_prefixes` is for the prefix form.

Do **NOT** re-reserve the two moved names at a space root: after the narrowing `alice/athenaresults/`
is an ordinary user path, and the dialogs' refusal of those names *directly inside* `system_settings/`
is partial by construction — uploads, pastes and plane-side moves create folders without the
validator. A root-aware, all-paths guard is its own spec. `shared_tables`, the third name when this
was written, never left the root, and the dialogs now refuse it there — see *A folder name that
lands on an app-managed folder's home is refused where it is typed*. `scripts/migrate_system_settings.py` stays
and every mode now refuses `narrowing_already_merged`, which is what makes the destructive workflow
inert rather than merely un-dispatched. Full write-up:
`docs/spec-delivery/SPEC-220-move-the-app-managed-folders-then-narrow.md`.

The shared Deny became `*/system_settings/archive/*` while the six rules went on refusing `finance/archive/`, a folder that is now the user's.

## History

### 2026-09-09

- **Settled:** SPEC-220.
