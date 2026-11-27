---
type: Decision
title: "The frame every page loads is kept small by a `sideEffects` list, and two gates hold the list and the frame (2026-11-27)"
description: "**`apps/portal/package.json` declares `sideEffects`, and that list is why a feature's page stays out of what every page loads**: the shell imports one hook through a feature's barrel, and without the list Turbopack keeps nearly every module the barrel re-exports. The list is a claim about every module, so one that acts as it is imported and is not named is dropped from a production build while Vitest, which shakes no tree, stays green. `src/lib/sideEffects.guard.test.ts` is a tripwire for the plain shapes of that, not a proof: it does not see code nested inside a declaration. **Naming a module is necessary and not sufficient**: one re-exported through an unnamed barrel is still dropped. `npm run check:pages` holds the boot's lazy group and the frame's together, and **closes that set over its lazy loads**, because each time it only named the groups to read, the next one was missed: a package, a folder or a feature the shell is not known to use fails at any size, any lazy load there but the frame fails, the portal's own source has a budget and a floor, and what it cannot measure is a failure. Do NOT raise the budget to admit a feature's page, and do NOT answer the floor by lowering both numbers before checking that code did not simply move."
---

**What was wrong.** The boot (`src/PortalBoot.tsx`) loads `src/AppFrame.tsx` on every page, the
signed-out landing page included, and with it the chrome and the signed-in shell.
`components/ProtectedLayout.tsx` and `components/Header.tsx` take a hook, a provider or a link from
a feature through its barrel (`features/data-explorer`, `features/file-browser`, `features/help`).
With no `sideEffects` in `package.json`, Turbopack keeps every module it cannot infer to be free of
effects, which is nearly all of what a barrel re-exports. Measured by the check below: 581,804 bytes
of the portal's own source loaded before any page's view at `9e3b68331`, the commit before the list,
and 235,917 with it. The Data Explorer's workspace, the file browser and the data-quality report
page were there; the Explore page's own lazy chunk added 19 KB, so its split bought nothing. No test
could notice: Vitest bundles nothing, and `check:pages` judged a route's hydration chunks, which
these are not.

**The list.** Stylesheets, everything under `src/app/` (entry points, kept regardless), the two
server entry files, and `src/features/query/SqlEditor.tsx`, the one module in `src/` with
module-scope statements that act on something outside it (Monaco's worker environment and loader).

**An entry is necessary and not sufficient.** Measured in builds: an effectful module named in the
list, re-exported through a barrel that is not, was dropped with the barrel; naming the barrel too
kept it. The bundler skips a barrel it has been told is free of effects, which is the same
mechanism that shrank the frame. A module's import-time code runs only when the module is imported
for an export that is used, or by a bare import from a module that is kept. `SqlEditor.tsx` runs
because `QueryWorkspace` imports its component, not because of its entry; the entry is the honest
declaration. In the other direction, an import of that module from the shell's graph carries Monaco
onto every page: planted in the header, about four megabytes of `monaco-editor` arrived while the
portal's own source rose by six kilobytes, which is why the check below names packages.

**The guard on the list** parses every shipped module under `src/` with typescript-eslint's parser
(`typescript` 7 ships no API before 7.1). At module scope it names, in a file no entry names: a
statement that is not an import, an export or a declaration; a default export that is not a name, a
function or a class; a class with a static block or a decorator. It names an import made for its
effects alone whose target no entry names, an entry that matches no file, and an entry in a shape
it does not model. Its matcher is a second copy of the bundler's, which reads entries as globs, so
it models three shapes (an exact path, a folder and everything under it, an extension anywhere),
refuses any other, and refuses a path holding a glob character.

**Its one exemption is by name**: `Name.displayName = 'text'`, for a name the module declares. An
earlier form reasoned about which bindings were the module's own, and three reviews each walked
around it: through an alias (`const w = window`), an ambient declaration (`declare const self`), and
a conditional. Each was dropped from a real build with the guard green. A rule that names one
property has nothing to walk around; a compound component (`Menu.Item = Item`) is refused, and is
better written inside the declaration than named in the list, since naming a module stops it being
shaken.

**It is a tripwire, not a proof.** Code nested inside a declaration passes: an initializer
(`export const x = register()`), a static field, a call in a class's heritage. The corpus pins each
as silence. A namespace or an enum with code passes the guard and is refused by `tsc`
(`erasableSyntaxOnly`), as is an unused named import; a bare import by a non-relative path passes,
and resolves to nothing only while `tsconfig` declares no path alias.

**The frame check** (`frameFindings` in `apps/portal/scripts/page-hydration.mjs`, run by
`check:pages`) reads, on each route that boots the portal, the lazy group whose trigger MODULE is
`src/PortalBoot.tsx` and the one whose trigger is `src/AppFrame.tsx`, as one set. It counts what the
browser is served, and a part the analysis lists twice for one file once. What it refuses:

- a package outside `FRAME_PACKAGES`, at any size, named by the innermost `node_modules` folder;
- a top-level folder of `src/` outside `FRAME_FOLDERS`, at any size: a page lives under `routes/`,
  and nothing loaded on every page may import one;
- a feature outside `FRAME_FEATURES`, at any size;
- the portal's own source over `FRAME_BUDGET_BYTES`, naming the largest folders, or under
  `FRAME_FLOOR_BYTES`;
- something it cannot measure: a route with one of the two groups and not the other, a file whose
  coverage is not exact, a file with no source or a size that is not a count, a file that is neither
  a script nor a stylesheet.

**The set is closed over its lazy loads, and that is the part that holds.** The first form read the
frame's group and missed a page imported from the boot's graph. The second read both and missed a
`void import()` of a page in the boot, which makes a third group on every page, with every gate
green. Naming groups to read fails open for the group nobody named. So the check also refuses any
lazy load that could make one: inside the boot's and the frame's files the only lazy load allowed is
the frame itself, and from every route's hydration the only own modules loaded lazily are the boot
and the not-found page. A route's own view is loaded from that route alone, so the second rule needs
two routes to compare and says nothing about a build with one. Hydration's packages are named too
(`HYDRATION_PACKAGES`), since a package a page imports through `src/lib/` is on every page before
any of this runs. Each of these escapes was built, seen to pass, and is now a corpus case and a
finding in a real build.

**The two numbers follow one rule**, written beside them: the measure `check:pages` prints on a
passing build, plus a sixth and less a sixth, rounded to the nearest thousand. A budget fires only
for something larger than its headroom, so the floor is what says the budget has gone quiet. It has
two causes, and the finding names both: the frame shrank, or code moved somewhere the check does not
read.

**What it does not hold.** A lazy load shared by several routes and not by all is not judged. A
package the lists allow is not budgeted, so anything under `node_modules/next` passes at any size. A
feature that IS named can bring more of itself inside the headroom when it is small: measured, a
hook the shell already uses importing one constant from a dialog file brought that feature's dialogs
along and passed. And the help text is still loaded on every page: the
header reads the whole of `features/help/helpContent.ts` to decide whether a route's section is
visible. Loading it on demand puts the measure under the floor, which is the floor doing its job.

**Not done, and why.** The inner `lazy` in `routes/areas/query.tsx`, `explore.tsx` and
`connections.tsx` stays. A page under `src/app/` may not import `components/`, so `next/dynamic` has
no fallback to show, and that inner boundary is what renders the loading state while the page's
chunk arrives, and what catches a chunk that fails to load.

## History

### 2026-11-27

- **Settled:** a review of the portal's code after the move to Next.js; no spec.
