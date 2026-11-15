---
type: Decision
title: "An App Router page sets its title as it mounts, and its view owns every change after (2026-11-14)"
description: "**Every signed-in App Router page calls `usePageTitleOnMount` with the name its view titles itself by, because Next's route announcer reads `document.title` in a passive effect of the commit that changes the router's tree, and on a first visit that commit holds the page but not its `next/dynamic` view.** Without it a screen reader hears the page the user left, while every test that does not read the stand-in's announcer stays green. The page writes once, in a layout effect, so the view's `usePageTitle`, a passive effect, still wins any commit holding both. A first visit announces that name, so a title the view derives from state (an unread count, a flag that is off) is read at the next navigation. A `metadata` title does not fix it (measured) and overwrites the page's own. `src/app/routeAnnouncement.test.tsx` visits every signed-in page once."
---

Next's `AppRouterAnnouncer` (`next/dist/client/components/app-router-announcer.js`) is rendered
after the page tree. On each new tree it reads `document.title`, or the first `h1` when the title is
empty, in a passive effect, and announces it through an `aria-live="assertive"` region in a shadow
root when it differs from its last reading; it never announces the first load.

Each signed-in page reaches its view through `next/dynamic` with `ssr: false`, which wraps the view in
a `Suspense` with a null fallback. On the first visit in a session the view's chunk is not loaded, so
the commit that changes the tree holds the page and an empty fallback, and the view's `usePageTitle`
runs a commit later, after the announcer has read. Measured on the production build under
`next start` in Chrome, signed in, in a fresh tab for each visit: from Files to five pages by their
links and to Help by the help panel's **Open the full guide**, and from Help to Files. Every
announcement was the previous page's title. The report page has no link until a run is listed; it
loads its view the same way, and the Vitest test visits it. A return to a page whose chunk is cached
announces correctly, because the view mounts in the same commit and its passive effect runs before
the announcer's.

**What the page does.** It calls `usePageTitleOnMount(<name>)` (`src/hooks/usePageTitle.ts`) with the
name its view passes to `usePageTitle`. The hook is a layout effect, so the title is in place before
any passive effect of the commit, the announcer's among them, and it writes once per mount, because a
boundary above that hides the page and shows it again re-runs layout effects but not the view's
passive one. With it, the same seven visits each announced the page just opened.

**What the view does.** It keeps `usePageTitle`, for two reasons. The catch-all still renders the
views of any area whose record names it, and there the view is the only thing setting the title. And
a view that changes its title in place (Notifications' unread count) owns that change: in a commit
holding both, the page's layout effect runs first and the view's passive effect after, so the page
never overwrites it. A page naming a different title from its view's fails the announcement test,
which compares what was announced with what the view settled on.

**What a first visit announces is the page's name, not a title the view derives from state.** The
page file cannot compute it: its static imports run before the boot, so it cannot read the flags or
the unread count. Measured on the production build: Notifications with three unread announced
"Notifications — Data Quarry" and settled on "Notifications (3) — Data Quarry", and Query with its flag
off announced "Query — Data Quarry" and settled on "Query unavailable — Data Quarry". Next reads the
view's own title at the next tree it sees, a return to the page or a navigation in place among them.
`src/app/routeAnnouncement.state.test.tsx` holds both, so a change to either is a decision, not a
drift. By the same mechanism `main` announced the page left in both; that was not measured.

**Do NOT give a page a `metadata` title instead.** Measured with a server `layout.tsx` beside Help
exporting one: the first visit still announced the page left, and the document gained a second
`<title>` beside the root layout's. The page sweep already refuses a `metadata` export, for the reason
the root layout records: Next reapplies a `metadata` title after an App Router navigation, over the
page's own.

**Do NOT make `usePageTitle` a layout effect.** In a commit holding both, a child's layout effect runs
before its parent's, so the page's mount title would overwrite the view's count.

**Where it is held.** The Vitest stand-in (`src/test/nextNavigation.ts`, behaviour 9) models the
announcer: rendered after the page, reading in a passive effect on each new tree, a router
navigation, a traversal or an external history write (Next restores the page it shows, as a new
tree), and never on the first load. `src/app/routeAnnouncement.test.tsx` visits every signed-in page once from a page the
catch-all serves, so each view's chunk is still loading when the router commits, and asserts the
announcement is the title the view then sets. `src/hooks/usePageTitle.test.tsx` holds the order
between the two hooks and the single write. A live session reads the announcer itself (`docs/testing/e2e.md` §4.1).

## History

### 2026-11-14

- **Decided:** a first visit to every signed-in App Router page announced the page left, measured on
  the production build; each page now sets its view's title as it mounts, and the Vitest stand-in
  models the announcer so the suite fails when a page does not.
