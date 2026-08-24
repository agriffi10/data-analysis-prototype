#!/usr/bin/env node
// Assert that the built bundle carries no `VITE_` variable NAME.
//
// WHAT THIS DETECTS, AND WHAT IT DOES NOT. Vite replaces `import.meta.env.VITE_X` with
// the variable's VALUE (or with `undefined` when it is unset), so an unported call site
// leaves no name behind and this script cannot see one. What it detects is the dev
// fallback's key tables surviving — `readEnv`'s object literal and `VITE_NAME` are
// tables of `VITE_` names as strings, and they only disappear if every reference to them
// sits inside a branch the production build eliminates. That elimination is the property
// a promotable artifact rests on: a bundle that still carries them is a bundle that can
// still read build-time configuration. The call sites are guarded by the `?raw` sweep in
// `src/lib/runtimeConfig.test.ts`, not here.
//
// A MISSING BUNDLE IS A FAILURE, NOT A SKIP. "Did not run" is never "clean".
import {readFileSync, readdirSync} from 'node:fs';
import {join} from 'node:path';

const ASSETS = 'dist/assets';

let files;
try {
  files = readdirSync(ASSETS).filter((name) => name.endsWith('.js'));
} catch {
  console.error(`[bundle] ${ASSETS} does not exist — run \`npm run build\` first.`);
  process.exit(1);
}

if (files.length === 0) {
  console.error(`[bundle] ${ASSETS} holds no .js files — the build produced nothing to check.`);
  process.exit(1);
}

const offenders = [];
for (const name of files) {
  const source = readFileSync(join(ASSETS, name), 'utf8');
  const found = [...new Set(source.match(/VITE_[A-Z0-9_]+/g) ?? [])];
  if (found.length > 0) offenders.push({name, found});
}

if (offenders.length > 0) {
  for (const {name, found} of offenders) {
    console.error(`[bundle] ${name} carries ${found.length} VITE_ name(s): ${found.join(', ')}`);
  }
  console.error('[bundle] The dev fallback survived the production build. Every reference to');
  console.error('[bundle] `devFallbackValue`, `readEnv` or `VITE_NAME` must sit inside an');
  console.error('[bundle] `import.meta.env.DEV` branch so the bundler can eliminate it.');
  process.exit(1);
}

console.log(`[bundle] ${files.length} chunk(s) checked, no VITE_ names present.`);
