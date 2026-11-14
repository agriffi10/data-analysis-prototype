#!/usr/bin/env node
// Assert that the browser bundle carries none of the server's DynamoDB client.
//
// The session store's client is the one @aws-sdk package the portal may hold, and only the server
// may load it. Three things keep it there: the lint rule that admits it under `src/server/` alone,
// the lint fence that keeps browser layers out of `src/server/`, and `server-only`, which fails the
// build when a client module imports a server one. This checks the result rather than any of them.
//
// IT LOOKS FOR `DynamoDB_20120810`, the protocol target every DynamoDB request carries, which the
// client's own code holds. Not for `@aws-sdk`: Amplify vendors its own copies of SDK packages into
// the browser bundle, so that string is there by design until Amplify retires.
//
// A MISSING BUNDLE IS A FAILURE, NOT A SKIP, as it is for the VITE_ check beside this one.
import {readFileSync, readdirSync} from 'node:fs';
import {join} from 'node:path';

const STATIC = '.next/static';
const MARKER = 'DynamoDB_20120810';

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

const offenders = files.filter((name) => readFileSync(join(STATIC, name), 'utf8').includes(MARKER));
if (offenders.length > 0) {
  for (const name of offenders) console.error(`[bundle] ${name} carries the DynamoDB client (${MARKER}).`);
  console.error('[bundle] A browser module reached the server session store. Import src/server/ only');
  console.error("[bundle] from the server, and begin every src/server/ module with import 'server-only'.");
  process.exit(1);
}

console.log(`[bundle] ${files.length} file(s) checked, no DynamoDB client present.`);
