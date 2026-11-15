---
type: Decision
title: "One session covers the browser, and the browser holds no token (rewritten 2026-11-15)"
description: "The portal server holds the session, so one sign-in covers every tab and a sign-out in one ends the others at their next request. **A tab never acts as another user**: every API request names the tab's user in `x-dq-user`, and the server refuses one that names nobody or someone else. A 401 under a page re-reads the session and signs the tab out in LOCAL state only — never a logout, because the cookie may already be someone else's."
---

**The browser holds no token at all.** It signs in by visiting the portal server's `/auth/login`,
learns who is signed in from `/auth/session`, and calls the API through its own origin's `/api/`,
where the server attaches the session's ID token. The session lives in the server's store, keyed by
an opaque `HttpOnly` cookie, so a second tab, or a link opened in a new tab, is signed in already,
and a sign-out in one tab signs the others out at their next request.

**One cookie serves every tab, so a tab could act as someone else.** If Alice signs out in one tab
and Bob signs in there, Alice's other tab would send Bob's cookie on its next window-focus refetch or
poll. So `apiRequest` sends the username the tab holds as `x-dq-user` (percent-encoded), and sends
nothing at all when it holds none; the `/api/` route answers 401 before forwarding when the header
is absent or names anyone but the session's `cognito:username`. A missing header is refused rather
than waved through, because that gap is exactly when a request is most likely to be stale, and a
required custom header also refuses a cross-site navigation into `/api/`, which `SameSite=Lax`
admits.

**What a 401 under a page does** (Andrew, 2026-11-13). The auth provider re-reads `/auth/session`,
once however many 401s arrive. A 401 there moves the tab to signed-out **in local state only** — no
`/auth/logout` and no logout navigation, because by then the cookie may belong to whoever signed in
in another tab, and a logout sent on it would end their session; the auth gate has recorded the page,
so the landing page's sign-in returns to it. A 200 naming another user disarms the leave guard and
reloads the document, so one person's page never acts as another's and an upload's prompt cannot
hold the stale page open. A 200 naming the same user leaves the tab signed in.

**A session serves only the client that created it.** A dev server and the deployed portal share the
session table, and a dev server's cookie is unprefixed and not `Secure`, so a session whose ID token
names another client is treated as absent and left alone.

The superseded design held Amplify's tokens in a tab-scoped store: no stay-signed-in, and a second
tab signed in again. Nothing in `helpContent.ts` promised it, and the *Move between pages* guide now
says one sign-in covers every tab.

## History

### 2026-11-15

- **Reversed:** SPEC-262 moved sign-in to the portal server. One session per browser replaces the
  per-tab token store, with `x-dq-user` and the local-only sign-out keeping a tab from acting as
  another user.

### 2026-08-27

- **Settled:** entered the register.
