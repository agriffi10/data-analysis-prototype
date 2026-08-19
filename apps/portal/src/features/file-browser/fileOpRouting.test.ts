import {describe, expect, it} from 'vitest';
import {requiresControlPlane} from './fileOpRouting';
import type {FileOpItem} from './fileOps.types';

const file = (key: string): FileOpItem => ({kind: 'file', key});
const folder = (key: string): FileOpItem => ({kind: 'folder', key});

describe('requiresControlPlane', () => {
  it('keeps exactly one file synchronous', () => {
    expect(requiresControlPlane([file('alice/q1.csv')])).toBe(false);
  });

  it('enqueues a single FOLDER — the case a reader assumes is synchronous', () => {
    // Forced rather than chosen: a folder operation is one CopyObject per contained object, so
    // its cost cannot be bounded without listing the folder first.
    expect(requiresControlPlane([folder('alice/reports/')])).toBe(true);
  });

  it('enqueues a folder RENAME, which is a single-folder move by another name', () => {
    // Named explicitly because "rename" sounds cheap and is not: S3 has no rename, so it is a
    // recursive copy followed by a recursive delete.
    expect(requiresControlPlane([{kind: 'folder', key: 'alice/reports/', targetName: 'q4'}])).toBe(true);
  });

  it('enqueues more than one file', () => {
    // The measured correction to the first draft of this rule: K files is up to 3K sequential
    // round trips from the user's laptop, which is the cost the plane exists to remove.
    expect(requiresControlPlane([file('alice/a.csv'), file('alice/b.csv')])).toBe(true);
  });

  it('enqueues a mixed selection', () => {
    expect(requiresControlPlane([file('alice/a.csv'), folder('alice/reports/')])).toBe(true);
  });

  it('is a property of the SELECTION, not of the operation', () => {
    // There is no operation parameter, so this is true by construction — asserted anyway because
    // the signature is the guarantee, and a later spec adding one would break it silently.
    expect(requiresControlPlane.length).toBe(1);
  });

  it('refuses an empty selection rather than answering for it', () => {
    // Without this, "not exactly one item" would route a zero-item selection to the plane, which
    // refuses an empty source as a request-shape error minutes later by notification.
    expect(() => requiresControlPlane([])).toThrow(/non-empty/);
  });
});

describe('the rule has a single home', () => {
  // A second implementation fails silently: the two disagree about one selection shape, and half
  // the gestures take the wrong path with nothing to report. An AST sweep is deliberately NOT used
  // — a boolean over `kind` and `length` has no recognisable syntactic signature and would fire on
  // every legitimate branch in the file browser — so this counts IMPORTERS instead.
  //
  // Read through Vite's own glob rather than `node:fs`: the sweep needs dynamic paths, and the
  // security lint rightly flags those, so this avoids the escape hatch rather than silencing it.
  const modules = import.meta.glob('../../**/*.{ts,tsx}', {query: '?raw', import: 'default', eager: true}) as Record<
    string,
    string
  >;

  const sources = Object.entries(modules).filter(([file]) => !/\.test\.tsx?$/.test(file));

  const importers = sources.filter(
    ([file, source]) => !file.endsWith('fileOpRouting.ts') && source.includes('requiresControlPlane')
  );

  it('found real modules to sweep', () => {
    // Guard-the-guard, and it is not optional here: with no callers yet the count assertion below
    // passes vacuously, so the only thing distinguishing "nobody imports it" from "the sweep is
    // broken" is this.
    expect(sources.length).toBeGreaterThan(100);
    expect(sources.some(([file]) => file.endsWith('fileOpRouting.ts'))).toBe(true);
  });

  it('is imported by at most one module', () => {
    // At most, not exactly: nothing routes through the plane yet. The spec that switches the
    // browser over raises this to exactly one — the branch has to MOVE rather than be consulted
    // from each of the four confirm paths. Note it is deliberately NOT re-exported from the
    // feature barrel: a barrel re-export is an importer without being a call site, so it would
    // cost this sweep its meaning while adding nothing.
    expect(importers.map(([file]) => file)).toEqual([]);
  });
});
