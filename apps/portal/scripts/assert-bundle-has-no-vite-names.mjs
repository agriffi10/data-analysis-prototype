#!/usr/bin/env node
// Assert that the browser bundle carries no `VITE_` variable NAME.
//
// WHAT THIS DETECTS, AND WHAT IT DOES NOT. A bundler replaces `import.meta.env.VITE_X` with the
// variable's value or with `undefined` (Turbopack supplies no custom `VITE_` names at all), so an
// unported call site leaves no name behind and this script cannot see one. What it detects is the
// test fallback's key tables surviving: `readEnv`'s object literal and `VITE_NAME` are tables of
// `VITE_` names as strings, and they only disappear if every reference to them sits inside a
// branch the production build eliminates. That elimination is the property a promotable artifact
// rests on: a bundle that still carries them can still read build-time configuration. The call
// sites are guarded by the `?raw` sweep in `src/lib/runtimeConfig.test.ts`, not here.
//
// It reads `.next/static`, everything Next serves to the browser, recursively: Next nests its
// chunks below `chunks/` and its worker bootstraps below `media/`.
//
// A MISSING BUNDLE IS A FAILURE, NOT A SKIP. "Did not run" is never "clean".
import {readFileSync, readdirSync} from 'node:fs';
import {join} from 'node:path';

const STATIC = '.next/static';

let files;
try {
  files = readdirSync(STATIC, {recursive: true})
    .map(String)
    .filter((name) => name.endsWith('.js'));
} catch {
  console.error(`[bundle] ${STATIC} does not exist — run \`npm run build\` first.`);
  process.exit(1);
}

if (files.length === 0) {
  console.error(`[bundle] ${STATIC} holds no .js files — the build produced nothing to check.`);
  process.exit(1);
}

const offenders = [];
for (const name of files) {
  const source = readFileSync(join(STATIC, name), 'utf8');
  const found = [...new Set(source.match(/VITE_[A-Z0-9_]+/g) ?? [])];
  if (found.length > 0) offenders.push({name, found});
}

if (offenders.length > 0) {
  for (const {name, found} of offenders) {
    console.error(`[bundle] ${name} carries ${found.length} VITE_ name(s): ${found.join(', ')}`);
  }
  console.error('[bundle] The test fallback survived the production build. Every reference to');
  console.error('[bundle] `devFallbackValue`, `readEnv` or `VITE_NAME` must sit inside an');
  console.error("[bundle] `import.meta.env.MODE === 'test'` branch so the bundler can eliminate it.");
  process.exit(1);
}

console.log(`[bundle] ${files.length} file(s) checked, no VITE_ names present.`);
