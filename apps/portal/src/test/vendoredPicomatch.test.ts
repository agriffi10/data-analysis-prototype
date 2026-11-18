import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {describe, expect, it} from 'vitest';

/**
 * picomatch carries an unpatched ReDoS (GHSA-fc5q-39xc-vjpf) in two copies: the dev-only package in
 * the lockfile, and a copy `next` vendors into the production server, which `npm audit` cannot see.
 * `docs/security-baseline.md` defers the advisory because neither copy compiles a pattern from
 * outside this repository. These checks fail when either copy changes, which is the moment that
 * note has to be re-read: a picomatch release clears the audit while the shipped copy stays as it
 * was, and only a `next` release that re-vendors it moves the shipped one.
 *
 * The suite runs from apps/portal, and npm hoists both packages to the workspace root.
 */

const REREAD =
  'picomatch changed: re-read the picomatch note in docs/security-baseline.md, update its row, then this pin';

/** The lockfile's picomatch when the advisory was deferred. */
const DEV_VERSION = '4.0.7';

/** SHA-256 of `next/dist/compiled/picomatch/index.js` when the advisory was deferred. */
const VENDORED_SHA256 = '607dc79784c1161c33076903769dba23e63d9d9ccfe3c4695a32ebe3a5ab892d';

describe('the picomatch copies the ReDoS deferral was argued against', () => {
  it('keeps the lockfile copy at the deferred version', () => {
    const {version} = JSON.parse(readFileSync('../../node_modules/picomatch/package.json', 'utf8')) as {
      version: string;
    };

    expect(version, REREAD).toBe(DEV_VERSION);
  });

  it('keeps the copy next vendors into the server byte-identical', () => {
    const source = readFileSync('../../node_modules/next/dist/compiled/picomatch/index.js', 'utf8');

    expect(createHash('sha256').update(source).digest('hex'), REREAD).toBe(VENDORED_SHA256);
  });
});
