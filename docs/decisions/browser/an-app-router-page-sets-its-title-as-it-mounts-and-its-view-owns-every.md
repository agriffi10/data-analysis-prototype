---
type: Decision
title: "An App Router page sets its title as it mounts, and its view owns every change after (2026-11-14)"
description: "**Every App Router page whose view loads through `next/dynamic` calls `usePageTitleOnMount` with the name its view titles itself by (the catch-all names its landing and not-found paths), because Next's route announcer reads `document.title` in a passive effect of the commit that changes the router's tree, and on a first visit that commit holds the page but not its view.** Without it a screen reader hears the page the user left, while every test that does not read the stand-in's announcer stays green. The page writes in a layout effect, and never twice for one name, so the view's `usePageTitle`, a passive effect, still wins any commit holding both. A first visit announces that name, so a title the view derives from state (an unread count, a flag that is off) is read when the page is shown again. A `metadata` title does not fix it (measured) and overwrites the page's own. The `routeAnnouncement` tests under `src/app/` hold each page's first visit."
---

Next's `AppRouterAnnouncer` (`next/dist/client/components/app-router-announcer.js`) is rendered
after the page tree. On each new tree it reads `document.title`, or the first `h1` when the title is
empty, in a passive effect, and announces it through an `aria-live="assertive"` region in a shadow
root when it differs from its last reading; it never announces the first load. A router navigation,
a traversal and an external history write each give it a new tree, the last because Next restores
the page it shows.

Each signed-in page reaches its view through `next/dynamic` with `ssr: false`, which wraps the view in
a `Suspense` with a null fallback, and the catch-all page reaches its route table the same way. On
the first visit in a session the chunk is not loaded, so the commit that changes the tree holds the
page and an empty fallback, and the view's `usePageTitle` runs a commit later, after the announcer has
read. A return to a page whose chunk is cached announces correctly, because the view mounts in the
same commit and its passive effect runs before the announcer's.

**Measured** on production builds under `next start`, in headless Chrome driven by Playwright, signed
in with test tokens and every API call answered 404 but the notifications and feature-flag reads a case
needed, by scripts kept outside the repo; the live row in
`docs/testing/e2e.md` §4.1 re-runs the check in a signed-in Chrome. On `main` before this fix: from
Files to Notifications, Query, Explore, Connections and Data quality by their links, to Help by the
help panel's **Open the full guide**, and from Help to Files, every announcement was the page left; so
were Notifications with three unread and Query with its flag off, and, before the catch-all titled
itself, an unknown path and the landing page reached from Files. With the fix each of the seven
announced the page opened, and an unknown path announced "Not Found — Data Quarry". The report page
has no link until a run is listed; the suite visits it.

**The landing page is silent on the first navigation after a document load.** Its title is the
product's alone, "Data Quarry", which is also the root layout's `<title>`; the announcer's first
reading is taken as the document hydrates, before the boot mounts any page, so it read "Data Quarry"
and announces only a change. Measured: from Files loaded by its address, a router push to `/`
announced nothing; from Files to Query by its link and then to `/`, it announced "Data Quarry". Every
other page's title differs from the product's, so only `/` meets it.

**What the page does.** It calls `usePageTitleOnMount(<name>)` (`src/hooks/usePageTitle.ts`) with the
name its view passes to `usePageTitle`. The catch-all's mount names the path as its route table serves
it (`src/app/[[...slug]]/catchAllPageName.ts`): the product alone for `/`, "Not Found" for an unknown
path, and nothing for an area the catch-all serves, whose view titles itself. The page's effect runs
before the announcer's, which Next renders after it. It is a layout effect for the view's sake: in a
commit holding both, it runs before the view's passive `usePageTitle`, so the view's title wins. It
writes only when its name changes, never twice for the same name, because a boundary above that hides
the page and shows it again re-runs layout effects but not the view's passive one; the catch-all,
mounted across navigations between its own paths, writes at each change of name.

**An area the catch-all serves is left to its view**, so its first visit there is announced a commit
late, as before this fix: the catch-all's mount cannot name an area's view without the application
graph. Every area's record names the App Router, so no production path reaches it; it holds for any
area moved back, and for every area in the test harness's default.

**What the view does.** It keeps `usePageTitle`, for two reasons. An area whose record names the
catch-all is rendered by it, and there the view is the only thing naming it: every area in the test
harness's default, and any area moved back. And a view that changes its title in place (Notifications'
unread count) owns that change. With no data and every flag on, as the announcement test renders it,
each view's title is its page's name; a page naming anything else fails that test.

**What a first visit announces is the page's name, not a title the view derives from state.** The
page file cannot compute it: its static imports run before the boot, so it cannot read the flags or
the unread count. Measured: Notifications with three unread announced "Notifications — Data Quarry"
and settled on "Notifications (3) — Data Quarry"; Query with its flag off announced "Query — Data
Quarry" and settled on "Query unavailable — Data Quarry". The view's own title is read when the page
is shown again, by a return to it or a navigation in place. `src/app/routeAnnouncement.state.test.tsx`
holds both, so a change to either is a decision, not a drift.

**Do NOT give a page a `metadata` title instead.** Measured with a server `layout.tsx` beside Help
exporting one: the first visit still announced the page left, and the document gained a second
`<title>` beside the root layout's. The page sweep already refuses a `metadata` export, for the reason
the root layout records: Next reapplies a `metadata` title after an App Router navigation, over the
page's own.

**Do NOT make `usePageTitle` a layout effect.** In a commit holding both, a child's layout effect runs
before its parent's, so the page's mount title would overwrite the view's count.

**A page now imports a hook statically, so what it may import is fenced one layer further.** What a
page imports is evaluated at hydration, before the boot. `src/app/pageSweep.test.ts` allows a page
and the files beside it only packages, each other, `src/lib/` and `src/hooks/`; lint keeps `src/lib/`
and `src/hooks/` off `components/` and `routes/` as well as `features/`, type-only imports aside
(`src/lib/eslintPageFence.test.ts`). That holds every shape a reviewer planted against those three
roots. It does NOT hold the whole graph, and a reviewer built each of these into a page's hydration
chunk through both gates: a hook or lib file importing a top-level composition file (`AppFrame`,
`AppChrome`, `PortalBoot`), a file in a folder under the page's directory, and a comment inside an
import list, which the sweep's regex reads past. Nested layouts, root special files, `.mts` files,
directory barrels and a dynamic `import()` inside lib/ or hooks/ are not held either. Most of these
predate the hook; the check that holds them all reads the built page's entry chunks rather than the
source. Do NOT answer them with more patterns: a hand-written walk over each page's imports was tried
first and missed a trailing slash, a `.js` specifier and a `'.'` import of an index, and refused a
type-only import, each a resolution rule the bundler already owns.

**Where it is held.** The Vitest stand-in (`src/test/nextNavigation.ts`, behaviour 9) models the
announcer: rendered after the page, reading in a passive effect on each new tree, and never on the
first load. `src/app/routeAnnouncement.test.tsx` visits every signed-in page once from a page the
catch-all serves, so each view's chunk is still loading when the router commits, and asserts the
announcement is the title the view then sets; `routeAnnouncement.catchAll.test.tsx` does the same for
an unknown path, holds the landing page's silence, and renders each path the route table names to hold
the mount's name to the title the table's element sets. The stand-in's first reading is the root
layout's `<title>`, as Next's is. `src/hooks/usePageTitle.test.tsx` holds the order between the two hooks and the single
write. A page that replaces the catch-all, the landing page or the not-found page, calls the hook with
its name, and the announcement tests' page list widens to take it in.

## History

### 2026-11-14

- **Decided:** a first visit to every signed-in App Router page, and to the catch-all, announced the
  page left, measured on the production build; each page now sets its view's name as it mounts, and
  the Vitest stand-in models the announcer so the suite fails when a page does not.
