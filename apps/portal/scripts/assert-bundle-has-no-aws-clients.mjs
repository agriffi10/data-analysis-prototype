#!/usr/bin/env node
// Assert that the browser bundle carries no AWS client: neither the server's DynamoDB client nor
// Amplify's Cognito client.
//
// The session store's client is the one @aws-sdk package the portal may hold, and only the server
// may load it. Three things keep it there: the lint rule that admits it under `src/server/` alone,
// the lint fence that keeps browser layers out of `src/server/`, and `server-only`, which fails the
// build when a client module imports a server one. Amplify left the portal when the browser began
// signing in through the server, and the manifest sweep keeps it out of `package.json`. This checks
// the result rather than any of them.
//
// EACH MARKER IS A PROTOCOL TARGET, which every request the client sends names and its own code
// holds, so a bundle carrying the client carries the string. A package name would not do: a bundle
// names packages only in comments a minifier may drop, and a client can arrive vendored under
// another package's name.
//
// A MISSING BUNDLE IS A FAILURE, NOT A SKIP, as it is for the VITE_ check beside this one.
import {readFileSync, readdirSync} from 'node:fs';
import {join} from 'node:path';

const STATIC = '.next/static';
const MARKERS = [
  {
    marker: 'DynamoDB_20120810',
    client: 'the DynamoDB client',
    advice: [
      'A browser module reached the server session store. Import src/server/ only',
      "from the server, and begin every src/server/ module with import 'server-only'."
    ]
  },
  {
    marker: 'AWSCognitoIdentityProviderService',
    client: "Amplify's Cognito client",
    advice: [
      'A browser module reached Cognito directly. The browser signs in through the',
      "server's /auth/ routes and holds no token; nothing in it may call Cognito."
    ]
  }
];

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

const sources = files.map((name) => ({name, text: readFileSync(join(STATIC, name), 'utf8')}));
let failed = false;
for (const {marker, client, advice} of MARKERS) {
  const offenders = sources.filter(({text}) => text.includes(marker));
  if (offenders.length === 0) continue;
  failed = true;
  for (const {name} of offenders) console.error(`[bundle] ${name} carries ${client} (${marker}).`);
  for (const line of advice) console.error(`[bundle] ${line}`);
}
if (failed) process.exit(1);

console.log(`[bundle] ${files.length} file(s) checked, no AWS client present.`);
