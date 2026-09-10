import {describe, expect, it} from 'vitest';
// The owner read as text, because the invariant below is about what the SOURCE does, not what
// the function returns — and the two are indistinguishable by value while the singular is depth-one.
import ownerSource from './appManagedPaths?raw';
import {
  appManagedPrefix,
  appManagedPrefixes,
  ARCHIVE_FOLDER,
  ATHENA_RESULTS_FOLDER,
  MOVING_FOLDERS,
  SHARED_TABLES_FOLDER,
  SYSTEM_SETTINGS_FOLDER
} from './appManagedPaths';

describe('appManagedPaths', () => {
  it('declares the three moving folders by their current names', () => {
    expect([ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER, SHARED_TABLES_FOLDER]).toEqual([
      'athenaresults',
      'archive',
      'shared_tables'
    ]);
  });

  it('anchors a MOVING folder under system_settings, and leaves every other name alone', () => {
    expect(appManagedPrefix('alice/', ARCHIVE_FOLDER)).toBe('alice/system_settings/archive/');
    expect(appManagedPrefix('finance/', ATHENA_RESULTS_FOLDER)).toBe('finance/system_settings/athenaresults/');
    // The guard on the branch. The fleet's twin takes this argument from a domain list whose
    // members mostly do not move, so unconditional it would build a prefix nothing is stored
    // under — and the caller's second leg would keep the refusal working by accident.
    expect(appManagedPrefix('finance/', 'user_settings')).toBe('finance/user_settings/');
  });
});

describe('appManagedPrefixes', () => {
  it('gives every folder exactly one home', () => {
    // Spelled out as literals. The old homes are gone — their objects were copied under
    // `system_settings/` and the sources deleted — so no name has a second location left.
    expect(appManagedPrefixes('alice/', ARCHIVE_FOLDER)).toEqual(['alice/system_settings/archive/']);
    expect(appManagedPrefixes('alice/', 'user_settings')).toEqual(['alice/user_settings/']);
    expect(appManagedPrefixes('alice/', SYSTEM_SETTINGS_FOLDER)).toEqual(['alice/system_settings/']);
    // shared_tables never moved — those tables were sent to the space and are the user's to
    // edit — so it keeps the depth-one home it always had.
    expect(appManagedPrefixes('alice/', SHARED_TABLES_FOLDER)).toEqual(['alice/shared_tables/']);
    expect(MOVING_FOLDERS).toEqual([ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER]);
  });

  it('normalizes nothing, exactly as the singular does not', () => {
    expect(appManagedPrefixes('', ARCHIVE_FOLDER)).toEqual(['system_settings/archive/']);
    expect(appManagedPrefixes('alice//', ARCHIVE_FOLDER)).toEqual(['alice//system_settings/archive/']);
  });

  it('now DOES build its one home by calling the singular', () => {
    // The inverse of what this asserted before the narrowing. While both homes were admitted the
    // plural spelled its elements out, so that moving the singular could not drag every rule's
    // second home to a third location. With one home left, two literals a few characters apart
    // is a rule written twice — the shape where one copy drifts and nothing notices.
    //
    // A spy cannot see the call — it is internal to the module, not through its exports — so the
    // guard reads the function's own body, exactly as its predecessor did.
    const body = /export function appManagedPrefixes\([^)]*\)[^{]*\{([\s\S]*?)\n\}/.exec(ownerSource);
    expect(body, 'appManagedPrefixes is no longer a plain function declaration').not.toBeNull();
    expect(body![1]).toMatch(/\bappManagedPrefix\s*\(/);
    // Guard the guard: a body that no longer built anything would satisfy a `toMatch` on its own.
    expect(body![1]).toContain('return');
  });

  it('answers exactly what the singular answers, for every name', () => {
    // This replaces the assertion that pinned the plural's FIRST element to the depth-one path
    // while the objects were still there. They have moved, the old prefixes are proved empty and
    // their fences are gone, so a depth-one `alice/archive/` is an ordinary user folder.
    for (const root of ['', 'alice/', 'finance/']) {
      for (const folder of [
        ATHENA_RESULTS_FOLDER,
        ARCHIVE_FOLDER,
        SHARED_TABLES_FOLDER,
        'user_settings',
        SYSTEM_SETTINGS_FOLDER
      ]) {
        expect(appManagedPrefixes(root, folder)).toEqual([appManagedPrefix(root, folder)]);
      }
    }
  });
});
