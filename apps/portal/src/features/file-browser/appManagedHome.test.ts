import {describe, expect, it} from 'vitest';
import {archiveRefusal} from '../archive/archiveSelection';
import {
  HIDDEN_BROWSER_FOLDERS,
  isRootFolderNamed,
  PICKER_LOCKED_FOLDERS,
  undeletableRootFolderRefusal
} from './protectedFolders';
import {isWriteLockedPrefix, writeLockRefusal} from './writeLockedPrefix';
import {appManagedPrefixes} from '../../lib/appManagedPaths';

/**
 * Every browser rule that anchors at a space root, asserted at the folder's home AND at the name
 * it left.
 *
 * While both homes were admitted this file asked whether each rule had learned the second one.
 * The narrowing removed the first, so it asks the mirrored question: does the rule follow the
 * folder, and does it let go of the name the folder vacated? The table keeps two rows with
 * opposite expectations rather than collapsing to one, because a single row would pass just as
 * happily against a rule still anchored at depth one — which is the regression the narrowing can
 * introduce, and it fails in the SAFE direction, so nothing else would report it.
 */
const HOMES: ReadonlyArray<readonly [string, boolean]> = [
  ['alice/{}/', false],
  ['alice/system_settings/{}/', true]
];
const at = (template: string, folder: string) => template.replace('{}', folder);

describe('the write lock covers both homes of the receipt folder', () => {
  it.each(HOMES)('%s archive/ is write-locked only where the receipts are', (home, locked) => {
    expect(isWriteLockedPrefix(at(home, 'archive'), 'alice/', 'personal')).toBe(locked);
    const refusal = writeLockRefusal(at(home, 'archive'), 'alice/', 'personal');
    if (locked) {
      expect(refusal).toMatch(/read-only/i);
    } else {
      expect(refusal).toBeNull();
    }
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
  it.each(HOMES)('%s archive/ refuses with the archive wording only at its home', (home, refused) => {
    // The DETAIL matters, not just that something refused: `system_settings` is itself in this
    // list, so a rule that learned only depth one still refuses the nested key — as the settings
    // prefix. Matching on the wording is what tells the two apart.
    for (const action of ['delete', 'move'] as const) {
      const refusal = undeletableRootFolderRefusal(at(home, 'archive'), 'alice/', action);
      if (refused) {
        expect(refusal).toMatch(/receipts/i);
      } else {
        expect(refusal).toBeNull();
      }
    }
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

  it('locks a moving folder at its home and the prefix itself, and releases the old name', () => {
    // athenaresults is the subject because it is one of the two folders that MOVED. shared_tables
    // stays at the space root and is locked there — a separate fact, asserted below, and for a
    // different reason: the share pipeline owns that folder's layout.
    expect(isRootFolderNamed('alice/system_settings/athenaresults/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
    expect(isRootFolderNamed('alice/system_settings/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
    // A user may now make and paste into their own `athenaresults/` at the space root.
    expect(isRootFolderNamed('alice/athenaresults/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(false);
  });

  it('locks shared_tables at its one home, which is the space root', () => {
    expect(isRootFolderNamed('alice/shared_tables/', 'alice/', PICKER_LOCKED_FOLDERS)).toBe(true);
    // And it is NOT inside the app's folder, so nothing there needs locking on its behalf.
    expect(appManagedPrefixes('alice/', 'shared_tables')).toEqual(['alice/shared_tables/']);
  });
});

describe('archiveRefusal names the folder the selection is actually in', () => {
  it.each([
    ['alice/system_settings/archive/', 'archive'],
    ['alice/system_settings/athenaresults/', 'athenaresults'],
    ['alice/system_settings/', 'system_settings'],
    ['alice/system_settings/user_settings/', 'system_settings']
  ])('%s is refused naming %s', (key, named) => {
    expect(archiveRefusal([{kind: 'folder', key}], 'alice/')).toContain(named);
  });

  it('does not refuse the depth-one names the moving folders left', () => {
    // These are ordinary user folders now, and archiving them is exactly what a user would want:
    // the objects that made them reserved were moved out and the fences removed.
    expect(archiveRefusal([{kind: 'folder', key: 'alice/archive/'}], 'alice/')).toBeNull();
    expect(archiveRefusal([{kind: 'folder', key: 'alice/athenaresults/'}], 'alice/')).toBeNull();
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
        {kind: 'folder', key: 'alice/system_settings/athenaresults/'}
      ],
      'alice/'
    );

    expect(refusal).toContain('archive');
    expect(refusal).not.toContain('athenaresults');
  });
});
