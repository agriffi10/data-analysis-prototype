import {describe, expect, it} from 'vitest';
import {archiveRefusal} from '../archive/archiveSelection';
import {
  HIDDEN_BROWSER_FOLDERS,
  isRootFolderNamed,
  PICKER_LOCKED_FOLDERS,
  undeletableRootFolderRefusal
} from './protectedFolders';
import {partitionSystemFolders, SYSTEM_FOLDER_GROUP_NAME} from './systemFolders';
import {isWriteLockedPrefix, writeLockRefusal} from './writeLockedPrefix';
import type {S3FolderItem} from '../../types/s3.types';

/**
 * Every browser rule that anchors at a space root, asserted at BOTH homes of a moving folder.
 *
 * The failure this guards against is a rule that learned one location and not the other: it reads
 * as working code, and it refuses nothing where the data will actually be. The pairs are written
 * over the two prefixes rather than as separate cases so they cannot drift apart.
 */
const BOTH_HOMES = ['alice/{}/', 'alice/system_settings/{}/'];
const at = (template: string, folder: string) => template.replace('{}', folder);

describe('the write lock covers both homes of the receipt folder', () => {
  it.each(BOTH_HOMES)('%s archive/ is write-locked in a personal space', (home) => {
    expect(isWriteLockedPrefix(at(home, 'archive'), 'alice/', 'personal')).toBe(true);
    expect(writeLockRefusal(at(home, 'archive'), 'alice/', 'personal')).toMatch(/read-only/i);
  });

  it('does NOT lock the settings prefix itself, because no Deny names it', () => {
    // The browser offers writes wherever IAM permits them. Nothing denies PutObject on
    // `{root}system_settings/` in a personal space, so refusing here would disable an upload
    // that would have worked — the inverse of the failure this predicate exists to prevent.
    expect(isWriteLockedPrefix('alice/system_settings/', 'alice/', 'personal')).toBe(false);
  });

  it('still leaves a user’s own nested archive folder writable in a personal space', () => {
    expect(isWriteLockedPrefix('alice/backups/archive/', 'alice/', 'personal')).toBe(false);
  });
});

describe('the undeletable rule names the folder, at either home', () => {
  it.each(BOTH_HOMES)('%s archive/ refuses with the archive wording', (home) => {
    // The DETAIL matters, not just that something refused: `system_settings` is itself in this
    // list, so a rule that learned only depth one still refuses the nested key — as the settings
    // prefix. Matching on the wording is what tells the two apart.
    expect(undeletableRootFolderRefusal(at(home, 'archive'), 'alice/', 'delete')).toMatch(/receipts/i);
    expect(undeletableRootFolderRefusal(at(home, 'archive'), 'alice/', 'move')).toMatch(/receipts/i);
  });

  it('gives the settings prefix its own wording rather than borrowing one', () => {
    expect(undeletableRootFolderRefusal('alice/system_settings/', 'alice/', 'delete')).toMatch(/manages for you/i);
    expect(undeletableRootFolderRefusal('alice/system_settings/', 'alice/', 'move')).toMatch(/moved or renamed/i);
  });
});

describe('a folder that is not moving gains no phantom home', () => {
  it('does not hide alice/system_settings/user_settings/', () => {
    // The Out of Scope promise, executable. `user_settings` is not a moving folder, so the plural
    // builder gives it exactly one location and nothing treats the nested path as that folder.
    expect(isRootFolderNamed('alice/system_settings/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
    expect(isRootFolderNamed('alice/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
  });

  it('locks both homes of a moving folder out of the picker, and the prefix itself', () => {
    expect(isRootFolderNamed('alice/system_settings/shared_tables/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
    expect(isRootFolderNamed('alice/system_settings/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
  });
});

describe('archiveRefusal names the folder the selection is actually in', () => {
  it.each([
    ['alice/system_settings/archive/', 'archive'],
    ['alice/system_settings/athenaresults/', 'athenaresults'],
    ['alice/system_settings/', 'system_settings'],
    ['alice/system_settings/user_settings/', 'system_settings'],
    ['alice/archive/', 'archive']
  ])('%s is refused naming %s', (key, named) => {
    expect(archiveRefusal([{kind: 'folder', key}], 'alice/')).toContain(named);
  });

  it('runs both passes PER ITEM, so a mixed selection answers as it always did', () => {
    // The item loop stays outermost. Hoisting it inside the two passes lets a later item's direct
    // hit outrank an earlier item's ancestor hit: this selection reported `archive` before the
    // restructure and must still, and the whole-selection shape reports `athenaresults` instead.
    // Measured by planting the hoist: exactly one test in the suite fails, and it is this one.
    // No count is written down here — it would go stale the next time anyone adds a test, and the
    // property worth keeping is that this case is the ONLY thing standing between the two shapes.
    const refusal = archiveRefusal(
      [
        {kind: 'folder', key: 'alice/'},
        {kind: 'folder', key: 'alice/athenaresults/'}
      ],
      'alice/'
    );

    expect(refusal).toContain('archive');
    expect(refusal).not.toContain('athenaresults');
  });
});

describe('the group row keeps standing in for the folder until the folder is real', () => {
  const folder = (prefix: string): S3FolderItem => ({type: 'folder', prefix, name: prefix});

  it('groups the three at a space root, and the row is named for the prefix they move into', () => {
    const {ordinary, grouped} = partitionSystemFolders(
      [folder('alice/athenaresults/'), folder('alice/reports/'), folder('alice/archive/')],
      'alice/'
    );

    expect(grouped.map((f) => f.prefix)).toEqual(['alice/athenaresults/', 'alice/archive/']);
    expect(ordinary.map((f) => f.prefix)).toEqual(['alice/reports/']);
    expect(SYSTEM_FOLDER_GROUP_NAME).toBe('system_settings');
  });

  it('groups a moving folder’s SECOND home too, which is inherited rather than chosen', () => {
    // `partitionSystemFolders` shares `isRootFolderNamed` with the four rules above, so widening
    // that predicate widened this. Unobservable until the prefix is real — nothing writes there —
    // but pinned here rather than left to be discovered, because the module's own docstring says
    // the grouped list comes back empty below the space root, and this is the one prefix where it
    // no longer does.
    const {grouped} = partitionSystemFolders([folder('alice/system_settings/archive/')], 'alice/');

    expect(grouped.map((f) => f.prefix)).toEqual(['alice/system_settings/archive/']);
  });
});
