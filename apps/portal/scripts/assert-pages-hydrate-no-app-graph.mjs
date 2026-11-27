#!/usr/bin/env node
// Assert that no App Router page hydrates the application graph.
//
// A page's static imports are evaluated in the browser at hydration, before the boot, so a page
// reaches its view, and everything under it, only through `next/dynamic`. What a page's hydration
// chunks may carry of the portal's own source is `src/app/`, `src/lib/`, `src/hooks/`, `src/types/`
// and `src/assets/`; anything else there (`features/`, `components/`, `routes/`, the composition
// files at the top of `src/`) is a finding naming the route and the module. A lazy load of such code
// in a hydration chunk must be a `next/dynamic` one, and lint refuses the import attribute that could
// make any other look like one. The source-text checks hold the same rule on imports; this
// holds it on what the build put in the chunks, which is the only place a resolution rule, a
// comment in an import list or a private folder cannot hide.
//
// WHAT IT READS. Production chunks name modules by number, so the names come from Next's bundle
// analysis: `next build --analyze` writes it, byte-identical static output included (measured),
// and `next analyze export` streams it. The analysis lists each chunk's modules and, through its
// chunk parts, every source file whose code the chunk holds; a module scope-hoisted into another
// appears only in the parts, so both are read. It describes the chunks under names of its own, so
// two checks tie it to the build in `.next`: the build's route statistics must fall between the
// analysis's data and its snapshot, as they do only when one build wrote all three, and each route's
// hydration chunks must hold as many modules, chunk for chunk, as the shipped files do. Next keeps
// `.next/diagnostics` across builds, so a plain build after an analysed one leaves an analysis of
// code that is gone, and `next analyze` writes one of code that was never built.
//
// THE FRAME. The same analysis says what every page loads before its own view: the boot's lazy group
// and the one it loads from `src/AppFrame.tsx`, judged together. A package, a folder of `src/` or a
// feature the shell is not known to use fails at any size, the portal's own source there has a
// budget and a floor, and what cannot be measured is a finding. The set is closed over its lazy
// loads: the only one the boot and the frame may hold is the frame, the only ones every route's
// hydration may hold are the boot and the not-found page, and hydration's packages are named. The
// measure is printed on a passing build.
//
// A MISSING OR STALE ANALYSIS IS A FAILURE, NOT A SKIP. "Did not run" is never "clean".
import {run} from './page-hydration.mjs';

const {findings, routes, chunks, frameBytes} = run(process.cwd());
if (findings.length > 0) {
  for (const finding of findings) console.error(`[pages] ${finding}`);
  if (findings.some((finding) => / hydrates /.test(finding))) {
    console.error(
      '[pages] A page reaches its view only through next/dynamic with ssr: false; what it imports statically'
    );
    console.error(
      '[pages] may reach src/app/, src/lib/, src/hooks/, src/types/ and src/assets/, and nothing else of src/.'
    );
  }
  process.exit(1);
}
console.log(`[pages] ${routes} route(s), ${chunks} hydration chunk(s) checked: none carries the application graph.`);
console.log(`[pages] every page loads ${frameBytes} bytes of the portal's own source before its view.`);
