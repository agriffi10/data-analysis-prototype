---
type: Decision
title: "Vitest's module cache stays off, because it freezes the file list of a glob it does not recognise (2026-11-14)"
description: "**`fsModuleCache: false` in `apps/portal/vite.config.ts`, and a test refuses a run that resolved it on.** Vitest 5 skips caching a module whose source holds the literal `import.meta.glob(`, but caches one that spells the call any other way Vite accepts, such as `import.meta.glob<T>(`, with the glob's file list frozen in, so a page added after one run stays invisible to `renderApp` until the cache is cleared. The skip is a substring test, and what it misses fails silently, so do NOT turn the cache back on and rely on how globs are spelled. The cost is measured in the entry."
---

**What happened.** Vitest 5 turned on a file-system module cache by default (`fsModuleCache`,
stored in `node_modules/.vitest-cache`), keyed on a module's own source. A glob depends on other
files, so Vitest bails out of caching any module whose source contains the substring
`import.meta.glob(` (`generateCachePath` in Vitest 5.0.5). `src/test/appRouter.tsx` calls it with a
type argument, `import.meta.glob<{default: ComponentType}>(`, which Vite accepts and the substring
test misses, so its transform was cached with the page list expanded inside it. Measured on the
SPEC-259 branch with a private cache: with the Query page present the test passed; with it deleted it
failed, as it should; with it restored and the same cache, it still failed, because `renderApp`
served `/query` from the catch-all's 404; with the cache cleared it passed. A full-suite run went
nine red that way on byte-identical code. The diff review then probed both spellings with the cache
on: a helper using the typed glob kept its old file list after a file was added, and one using the
plain spelling saw the new file.

**Why the cache is off rather than the spelling fixed.** Every other glob under `src/`, the page
sweep and the record-and-page guard among them, uses the plain spelling and was never frozen.
Dropping the type argument from `appRouter.tsx` would fix this one file. But the next glob written
with a type argument, or with a space before the parenthesis, would freeze just as silently, and the
case it gets wrong is the one an area move creates: a page added after the suite has run once.
Nothing would report it, and CI runs no tests, so the local pre-push run is the only gate. A text
rule covering every spelling Vite accepts is the kind of guard that leaks. Turning the cache off
removes the whole class. The cache directory also travels with `node_modules`: a review worktree
given a symlink to another worktree's `node_modules` shared it, and a page the reviewer planted
leaked into the other session's runs.

**The guard.** `vitest.globalSetup.ts` provides the setting the run resolved, from the configuration
file and from a command-line `--fsModuleCache` alike. It reads the setting in the main process,
because a worker has no public way to read it. `src/test/fsModuleCache.test.ts` fails, naming the
option, unless the setting is `false`. Deleting the global setup fails the same test, since `inject`
then returns nothing. Each of the three cases was mutated once (the setting removed, the flag passed
on the command line, the setup deleted), and each turned the test red. The delete-and-restore case
above, rerun with the cache off, passed at every step.

**What it costs.** Measured on the whole portal suite (about 230 files and 3,700 tests) on a 10-core Mac that
peer sessions were also loading, so every figure carries its load. At a one-minute load average of
12 to 17, the cache on took 48.2 s cold and 40.8 s warm, and the cache off took 50.7 s, with the
load rising to 24 during that run. A second series at a load of 30 to 59 ranged from 77 s to 190 s
with no order between the two settings, and its cache-on runs were forced on from the command line,
so the guard failed in each; it is left out. So the cache saves roughly ten seconds on a warm run of
about fifty. A
quieter measurement may move that figure, but not the decision: what the cache buys is a failure
that reports nothing.

**Do NOT** turn the cache back on to speed up local runs, and do not replace it with "clear the
cache when you add a file", which is a procedure every session must remember for a failure that is
silent. If a later Vitest caches a globbing module by its matched files, or recognises every
spelling, re-run the delete-and-restore case before changing this.

## History

### 2026-11-14

- **Decided:** the SPEC-259 build found the frozen page list while adding the Query page, and the
  Next.js arc's orchestrator asked for the cache to be turned off and guarded before the area moves
  push. The first draft blamed every glob; the diff review found Vitest's substring bail-out, which
  narrowed the cause to the one spelling and is why the entry reasons from the skip.
