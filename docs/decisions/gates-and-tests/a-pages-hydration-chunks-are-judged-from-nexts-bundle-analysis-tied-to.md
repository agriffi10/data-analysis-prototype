---
type: Decision
title: "A page's hydration chunks are judged from Next's bundle analysis, tied to the build it describes (2026-11-15)"
description: "**`npm run check:pages` fails a build in which a route's hydration chunks carry the portal's own source outside `src/app/`, `src/lib/`, `src/hooks/`, `src/types/` and `src/assets/`, or a lazy load of such source that is not `next/dynamic`.** Production chunks name modules by number, so it reads the analysis `next build --analyze` writes, and `ci.yml`'s build carries the flag. Traps that pass a wrong analysis green: its module list leaves out a module merged into another, which only the chunk parts name, so both are read; Next keeps `.next/diagnostics` across builds and `next analyze` writes an analysis while building nothing, so the build's route statistics must fall between the analysis's data and its snapshot; and it names chunks its own way, so each route's chunks must hold as many modules, chunk for chunk, as the shipped files register, counted by factory. The build cannot tell a hand-written `turbopack-transition` import attribute from `next/dynamic`'s own, so lint refuses every import attribute under `src/`. Do NOT trust the module list alone."
---

**The rule it holds** is the browser area's: a page's static imports are evaluated at hydration,
before the boot, so a page reaches its view only through `next/dynamic` with `ssr: false`
(`docs/decisions/browser/an-app-router-page-sets-its-title-as-it-mounts-and-its-view-owns-every.md`).
The source checks read imports as written, and a reviewer built three escapes into the Files page's
hydration chunk through them. This check reads what the build put there.

**What the build emits, measured on Next 16.4.6 with Turbopack.** A production chunk registers
modules under numeric ids and carries no source path. A page's
`page_client-reference-manifest.js` names its entry chunks, and `.next/diagnostics/route-bundle-stats.json`
names every route's first-load chunks, but neither says what is in them. `next build --analyze`
writes a module graph per route under `.next/diagnostics/analyze/`, and `next analyze export` streams
it as JSON lines: each route's chunk groups (`bootstrap`, `render_dependent`, `async`), each output's
modules and lazy loaders, and each output's chunk parts by source file. The analysed build's
`.next/static` matched a plain build's file for file, by hash, but for the build-id folder's name.

**What counts as hydration.** Every JavaScript output that a route's groups other than `async` list,
including one an `async` group lists as well. A stylesheet is not judged: it is not code, and the
root layout's `src/index.css` is one today.

**Why an allow-list of roots rather than a list of the graph's.** A composition file nobody has
written yet, at the top of `src/`, is refused without anyone naming it. `src/types/` is allowed
because `src/lib/` reads runtime constants from it (`REQUIRED_CONFIG`, `API_ROUTES`), and
`src/assets/` because it is media, not code: a page importing `hero.png` was refused before it was
allowed. Packages and Turbopack's runtime are not judged. Code placed under `src/app/` itself is
allowed by definition; the rule is a directory rule, and that is its edge.

**The module list leaves out merged modules.** Measured on the catch-all: the analysis listed five
modules in the chunk holding the navigation seam, and its parts named 29 source files, among them
`src/lib/navigation/address.ts` and `NavigationProvider.tsx`. The shipped chunk registers one
factory under nine ids, and `address.ts`'s code is in it. A check reading the module list alone
would pass an application module merged the same way. The parts are not whole either: measured, a
sixth of the listed modules had no part in their chunk, Next's externals among them. So the check
reads both, and its corpus has a case for each.

**The analysis is tied to the build in two ways.** Next's build cleans `.next` but keeps
`diagnostics`, so a plain build after an analysed one leaves the old analysis in place, and
`next analyze` writes a fresh one while building nothing (both measured). A build writes the
analysis's data, then its route statistics, then the snapshot `next analyze export` reads; so the
check requires the statistics to fall between the newest data file and the snapshot, which refuses
both sequences. And the analysis names its chunks under names the build never ships, so for each
route the analysed hydration outputs' module counts (modules plus lazy loaders) must equal the
shipped first-load chunks' factory counts, as multisets. Measured, they matched on all ten routes
once factories rather than ids were counted. A Next upgrade that changes how the analysis models
chunks fails here rather than quietly. The count alone would not catch an analysis of other code,
because a module merged into another changes no count; the write order is what does.

**Lazy loads.** A lazy load of the portal's own source outside the allowed roots, in a hydration
chunk, must be a `next/dynamic` entry; a lazy load of a package or of an allowed root is no escape,
and a package that loads lazily inside itself (Monaco's editor does) would otherwise refuse any page
that imported it. A raw `import()` of a feature in the page, or in a hook it calls, is refused. The
analysis knows a `next/dynamic` load only by the `turbopack-transition` import attribute Next's
transform adds, and a hand-written one passed an eager `import()` of a feature as a `next/dynamic`
load, entered in the page's loadable manifest like a real one (measured). Nothing in the build tells
them apart, so `no-restricted-syntax` in `apps/portal/eslint.config.js` refuses every import
attribute in `src/`'s TypeScript and JavaScript; no source needs one.

**Where it runs.** `ci.yml` builds with `npm run build -- --analyze` and runs `npm run check:pages`
after `check:bundle`; a session runs the same before pushing, because it runs whatever `ci.yml` runs.
The image's build stays plain. The checks are `apps/portal/scripts/page-hydration.mjs`, the entry
point `assert-pages-hydrate-no-app-graph.mjs` beside it runs them, and the corpus,
`assert-pages-hydrate-no-app-graph.test.mjs`, runs in the Vitest suite: it asserts every finding by its
text, the silences beside them, the refusal of a missing, unreadable or foreign analysis, and the
entry point's exit codes, by running it. Each check was broken once and reddened it.

**Do NOT read `.next/diagnostics/analyze/data` directly.** `next analyze export` validates the
binary format and its fingerprints, and stops on a mismatch, possibly after writing part of its
output; that is why the check refuses an export that did not exit 0.

## History

### 2026-11-15

- **Decided:** the page rule is held on the build's hydration chunks, read through Next's bundle
  analysis and tied to the build by write order and by module counts; the source sweep's allow-list
  and the lint fence stay as early warnings, and lint refuses import attributes, the one forgery the
  build cannot see.
