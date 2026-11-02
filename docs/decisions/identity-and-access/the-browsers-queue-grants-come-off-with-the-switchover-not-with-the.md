---
type: Decision
title: "The browser's queue grants come off with the switchover, not with the trust flip (SPEC-200)"
description: "The browser's `sqs:SendMessage` grants had to come off before the trust flip, because once `identity.actor` is authoritative any tab able to write a queue could name any actor; the grants are gone and recovery from here is forward."
---

The rollout is two specs. SPEC-200 has the API write **both** the token and the identity block,
changes no plane's trust, and leaves every `verified_username` call working on the field it already
reads. SPEC-201 flips the planes onto `identity.actor` and only then — as its own second step, after
that flip is deployed — stops the token being sent. Collapsing either boundary fails all eight planes
closed on the first request after deploy.

**The eight `sqs:SendMessage` grants come off in SPEC-200, and that ordering is separate from the
trust flip.** The Identity Pool survived until SPEC-202 — it is retired now — so at the moment
`identity.actor` became authoritative, any signed-in tab that could still write a queue could have
named any actor. "201 before the grant removal" would have been a real impersonation window rather
than a theoretical one.

The recovery consequence was worth writing down and the revert it protected has since expired: the
eight `VITE_*_QUEUE_URL` repository variables were left in place until SPEC-202, because a revert of
the switchover needed them and re-reading eight values from `tofu output` was the only step of that
recovery which was not `git revert`. SPEC-202 removed the credentials that revert would have used,
so recovery from here is forward. The variables themselves are still **set** in the repository and
read by nothing — their deletion is one line of SPEC-215's owed ledger entry, not something this
arc closed.

## History

### 2026-08-29

- **Settled:** SPEC-200.
