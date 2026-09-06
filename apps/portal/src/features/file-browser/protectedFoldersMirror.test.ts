import {describe, expect, it} from 'vitest';
// The plane's own lists, read as data through Vite's `?raw` — `node:fs` is unavailable here,
// because the app tsconfig carries no node types and `tsc -b` is the only typecheck CI runs.
import appManaged from '../../../../../lambdas/control-plane-common/cpcommon/app_managed.py?raw';
import focommonConfig from '../../../../../lambdas/file-ops-common/focommon/config.py?raw';
import {PICKER_LOCKED_FOLDERS, UNDELETABLE_ROOT_FOLDERS} from './protectedFolders';

/**
 * The browser's protected-folder lists against the file-operations plane's, held equal as sets.
 *
 * `focommon/config.py` said in prose that "a test reads both files and holds the memberships
 * together; that is the only thing keeping the two runtimes' answers the same". No such test
 * existed in either tree. The two lists are duplicated because Python and TypeScript cannot share
 * one, and a divergence is a folder the browser offers as a paste target that the plane then
 * refuses — a request the user watches fail for a rule the app itself wrote.
 *
 * The resolver is three-shaped, which is why this is not a copy of `archiveSelection.test.ts`.
 * That file's members are all bare imported names of owner literals; these are a mix of quoted
 * literals, attribute references (`_app_managed.SHARED_TABLES_FOLDER`) and locally-declared
 * aliases (`ARCHIVE_FOLDER = _app_managed.RECEIPT_FOLDER`), so a member needs up to one hop
 * through the plane's own module before it reaches a string.
 */
function planeTuple(name: string): string[] {
  const block = new RegExp(`^${name} = \\(([^)]*)\\)`, 'm').exec(focommonConfig);
  expect(block, `focommon.config no longer declares ${name} as a tuple literal`).not.toBeNull();
  return block![1]
    .split(',')
    .map((member) => member.trim())
    .filter((member) => member !== '')
    .map((member) => resolve(member));
}

/** A member as the string it denotes: a literal, an owner attribute, or a local alias of one. */
function resolve(member: string, hops = 1): string {
  const literal = /^"([^"]+)"$/.exec(member);
  if (literal) return literal[1];

  // `_app_managed.RECEIPT_FOLDER` — the owner declares it. Escape before interpolating, or the
  // `.` in the attribute reference becomes a wildcard and matches the wrong declaration.
  const attribute = /^_app_managed\.(\w+)$/.exec(member);
  if (attribute) {
    const declared = new RegExp(`^${escape(attribute[1])} = "([^"]+)"$`, 'm').exec(appManaged);
    expect(declared, `cpcommon.app_managed does not declare ${attribute[1]}`).not.toBeNull();
    return declared![1];
  }

  // A bare name declared locally in focommon.config, which may itself be an alias of an owner
  // attribute. One hop only: a chain longer than that is a shape this resolver should be told
  // about rather than silently follow.
  const local = new RegExp(`^${escape(member)} = (.+)$`, 'm').exec(focommonConfig);
  expect(local, `${member} is not a literal and focommon.config does not declare it`).not.toBeNull();
  expect(hops, `${member} resolves through more than one alias`).toBeGreaterThan(0);
  return resolve(local![1].trim(), hops - 1);
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

describe('the browser and the file-operations plane refuse the same folders', () => {
  it('locks the same folders out of the picker', () => {
    // SET equality, not a spot check: the failure is a folder one side offers and the other
    // refuses, and it surfaces as a paste that fails after the user has chosen a destination.
    const plane = planeTuple('PICKER_LOCKED_FOLDERS');

    expect(plane.length).toBeGreaterThan(0);
    expect([...PICKER_LOCKED_FOLDERS].sort()).toEqual([...plane].sort());
  });

  it('refuses to destroy the same folders', () => {
    const plane = planeTuple('UNDELETABLE_ROOT_FOLDERS');

    expect(plane.length).toBeGreaterThan(0);
    expect([...UNDELETABLE_ROOT_FOLDERS].sort()).toEqual([...plane].sort());
  });

  it('resolves every member to a string, rather than skipping one it cannot read', () => {
    // A member that failed to resolve would otherwise shrink the plane's set silently and make
    // both assertions above pass over a divergence — the shape that makes a mirror vacuous.
    for (const member of [...planeTuple('PICKER_LOCKED_FOLDERS'), ...planeTuple('UNDELETABLE_ROOT_FOLDERS')]) {
      expect(member).toMatch(/^[\w-]+$/);
    }
  });
});
