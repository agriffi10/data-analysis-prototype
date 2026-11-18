#!/usr/bin/env node
// Assert that the build defines no server action.
//
// The guard the image starts ahead of Next (`server-guard.cjs`) refuses every request Next would
// treat as a server action, because the portal has none and each such request is a probe. The guard
// runs only in the image, so a server action added to the code works under `next dev` and is refused
// in production. This fails the build first: Next lists every action the build defines in the server
// reference manifest, under its `node` and `edge` runtimes, and that list must be empty.
//
// A MISSING OR UNREADABLE MANIFEST IS A FAILURE, NOT A SKIP. "Did not run" is never "clean".
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const MANIFEST = '.next/server/server-reference-manifest.json';

/**
 * What is wrong with a server reference manifest: one finding per action it lists, or one saying it
 * is not a manifest at all.
 *
 * @param {string | undefined} text - The manifest's text, or undefined when it could not be read.
 * @returns {string[]} The findings, empty when the build defines no action.
 */
export function serverActionFindings(text) {
  if (text === undefined) return [`${MANIFEST} does not exist — run \`npm run build\` first.`];
  let manifest;
  try {
    manifest = JSON.parse(text);
  } catch {
    return [`${MANIFEST} is not JSON.`];
  }
  const findings = [];
  for (const runtime of ['node', 'edge']) {
    const actions = manifest?.[runtime];
    if (actions === null || typeof actions !== 'object' || Array.isArray(actions)) {
      findings.push(`${MANIFEST} has no \`${runtime}\` map, so it cannot say the build defines no action.`);
      continue;
    }
    for (const id of Object.keys(actions)) findings.push(`the build defines a server action (${runtime}, ${id}).`);
  }
  return findings;
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  let text;
  try {
    text = readFileSync(MANIFEST, 'utf8');
  } catch {
    text = undefined;
  }
  const findings = serverActionFindings(text);
  if (findings.length > 0) {
    for (const finding of findings) console.error(`[actions] ${finding}`);
    console.error('[actions] The image refuses every server-action request ahead of Next (server-guard.cjs),');
    console.error('[actions] so an action would work under next dev and be refused in production.');
    process.exit(1);
  }
  console.log('[actions] the build defines no server action.');
}
