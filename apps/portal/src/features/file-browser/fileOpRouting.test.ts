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

  it('takes no operation parameter', () => {
    // `Function.prototype.length` counts formals up to the first defaulted or rest parameter, so
    // this catches `(items, operation)` and NOT `(items, operation = 'copy')` — which is the shape
    // someone would reach for to add one compatibly. Narrow, but not nothing: it pins the arity a
    // reader sees, and the property it stands for is the absence of an operation in the signature.
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
    // A count alone does not prove the glob reaches the whole tree: narrowing it by one segment
    // still matches ~300 files, all of them under `features/`, while silently dropping `lib/`,
    // `components/` and `App.tsx` — where a future second call site is at least as likely to live.
    expect(sources.some(([file]) => file.includes('/lib/'))).toBe(true);
    expect(sources.some(([file]) => file.includes('/components/'))).toBe(true);
  });

  it('is imported by EXACTLY ONE module, and it is the dispatcher', () => {
    // Exactly, not at most: the browser now routes through the plane, so a count of zero would
    // mean the switchover had been unwired rather than that nothing uses it yet.
    //
    // `useFileBrowserDialogs` is that module because the FIVE submission points live there — the
    // four confirms and the same-folder prompt's confirm, which was moved out of
    // `FileBrowserDialogs.tsx` for exactly this reason. Consulting the predicate from each of
    // them separately is the shape this sweep exists to prevent.
    //
    // It is deliberately NOT re-exported from the feature barrel: a barrel re-export is an
    // importer without being a call site, so it would cost this sweep its meaning while adding
    // nothing. And one false negative to know about: a RENAMED re-export
    // (`export {requiresControlPlane as routesToPlane}`) is caught here, but its consumers are
    // not — so the single allowed importer must not be one.
    expect(importers.map(([file]) => file)).toEqual(['./useFileBrowserDialogs.ts']);
  });

  it('is consulted from exactly one call site inside that module', () => {
    // The sweep above proves one MODULE. This proves one CALL — five submission points reaching
    // the same imported predicate five times would satisfy the first and defeat the point of it,
    // because the routing rule is then five rules that happen to agree today.
    const dispatcher = sources.find(([file]) => file.endsWith('useFileBrowserDialogs.ts'));
    expect(dispatcher).toBeDefined();
    const calls = [...(dispatcher as [string, string])[1].matchAll(/requiresControlPlane\(/g)];
    expect(calls).toHaveLength(1);
  });
});
