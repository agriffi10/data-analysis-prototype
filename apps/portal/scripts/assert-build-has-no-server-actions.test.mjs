import {spawnSync} from 'node:child_process';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {afterEach, describe, expect, it} from 'vitest';
import {serverActionFindings} from './assert-build-has-no-server-actions.mjs';

/**
 * The server-action check's corpus: a manifest as Next writes it for a build with no action, one
 * listing an action under each runtime, and the shapes that cannot vouch for anything.
 */

const EMPTY = JSON.stringify({node: {}, edge: {}, encryptionKey: 'k'});
const ACTION = {workers: {'app/page': {moduleId: 1, async: false}}, layer: {'app/page': 'action-browser'}};
const SCRIPT = resolve(import.meta.dirname, 'assert-build-has-no-server-actions.mjs');

describe('the server-action check', () => {
  it('is silent on a build that defines no action', () => {
    expect(serverActionFindings(EMPTY)).toEqual([]);
  });

  it.each([
    ['node', {node: {'7f00aa': ACTION}, edge: {}}],
    ['edge', {node: {}, edge: {'7f00aa': ACTION}}]
  ])('names an action the build defines for the %s runtime', (runtime, manifest) => {
    expect(serverActionFindings(JSON.stringify(manifest))).toEqual([
      `the build defines a server action (${runtime}, 7f00aa).`
    ]);
  });

  it.each([
    ['a missing manifest', undefined, /does not exist/],
    ['a manifest that is not JSON', '{', /is not JSON/],
    ['a manifest with no edge map', JSON.stringify({node: {}}), /has no `edge` map/],
    ['a manifest whose node entry is a list', JSON.stringify({node: [], edge: {}}), /has no `node` map/]
  ])('fails on %s rather than passing it', (_, text, reason) => {
    const findings = serverActionFindings(text);
    expect(findings).toHaveLength(1);
    expect(findings[0]).toMatch(reason);
  });
});

describe('the server-action check run as a script', () => {
  const dirs = [];
  afterEach(() => {
    for (const dir of dirs.splice(0)) rmSync(dir, {recursive: true, force: true});
  });

  /** Runs the script in a fresh directory holding the given manifest, or none. */
  function runIn(manifest) {
    const dir = mkdtempSync(join(tmpdir(), 'actions-check-'));
    dirs.push(dir);
    if (manifest !== undefined) {
      mkdirSync(join(dir, '.next/server'), {recursive: true});
      writeFileSync(join(dir, '.next/server/server-reference-manifest.json'), manifest);
    }
    return spawnSync(process.execPath, [SCRIPT], {cwd: dir, encoding: 'utf8'});
  }

  it('exits 0 on a build with no action', () => {
    const result = runIn(EMPTY);
    expect(result.status).toBe(0);
    expect(result.stdout).toContain('the build defines no server action');
  });

  it('exits 1 naming the action, and on a build it cannot find', () => {
    const defined = runIn(JSON.stringify({node: {'7f00aa': ACTION}, edge: {}}));
    const missing = runIn(undefined);

    expect([defined.status, missing.status]).toEqual([1, 1]);
    expect(defined.stderr).toContain('[actions] the build defines a server action (node, 7f00aa).');
    expect(missing.stderr).toContain('server-reference-manifest.json does not exist');
  });
});
