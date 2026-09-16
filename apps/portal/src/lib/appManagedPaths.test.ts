import {describe, expect, it} from 'vitest';
// The owner read as text, because the invariant below is about what the SOURCE does, not what
// the function returns — and the two are indistinguishable by value while the singular is depth-one.
import ownerSource from './appManagedPaths?raw';
import {
  appManagedPrefix,
  appManagedPrefixes,
  appManagedSegments,
  segmentsHoldAppManaged,
  ARCHIVE_FOLDER,
  ATHENA_RESULTS_FOLDER,
  DATA_QUALITY_REPORTS_FOLDER,
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

  it('declares the data-quality reports folder, which stays at the space root', () => {
    // A literal, because every refusal in the browser now follows this constant: a rename here
    // would move all of them together, and only this row can say the value is still the one the
    // plane writes.
    expect(DATA_QUALITY_REPORTS_FOLDER).toBe('_data-quality-reports');
    expect(appManagedPrefix('alice/', DATA_QUALITY_REPORTS_FOLDER)).toBe('alice/_data-quality-reports/');
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

  it('answers the one literal location, for every name and every root', () => {
    // Spelled out rather than compared against `appManagedPrefix`. The plural's body IS
    // `[appManagedPrefix(...)]`, so an equality against it cannot fail for ANY implementation of
    // the singular — it would go green with the singular returning the empty string. The
    // delegation is guarded by the body-reading test above; what this asserts is the VALUE.
    expect(appManagedPrefixes('', ARCHIVE_FOLDER)).toEqual(['system_settings/archive/']);
    expect(appManagedPrefixes('alice/', ATHENA_RESULTS_FOLDER)).toEqual(['alice/system_settings/athenaresults/']);
    expect(appManagedPrefixes('finance/', ARCHIVE_FOLDER)).toEqual(['finance/system_settings/archive/']);
    expect(appManagedPrefixes('finance/', SHARED_TABLES_FOLDER)).toEqual(['finance/shared_tables/']);
    expect(appManagedPrefixes('alice/', 'user_settings')).toEqual(['alice/user_settings/']);
    expect(appManagedPrefixes('alice/', SYSTEM_SETTINGS_FOLDER)).toEqual(['alice/system_settings/']);
  });

  // ─── the segment builder, which five rules across two trees delegate to ───

  it('pairs only the folders that moved', () => {
    expect(appManagedSegments(ARCHIVE_FOLDER)).toEqual([SYSTEM_SETTINGS_FOLDER, 'archive']);
    expect(appManagedSegments(ATHENA_RESULTS_FOLDER)).toEqual([SYSTEM_SETTINGS_FOLDER, 'athenaresults']);
    expect(appManagedSegments(SHARED_TABLES_FOLDER)).toEqual(['shared_tables']);
    expect(appManagedSegments('user_settings')).toEqual(['user_settings']);
  });

  it.each([
    // [segments, folder, held, why this row is here]
    [[], ARCHIVE_FOLDER, false, 'an empty list — the scan must not read past the end'],
    [['system_settings', 'archive'], ARCHIVE_FOLDER, true, 'the pair, exactly'],
    [['a', 'system_settings', 'archive'], ARCHIVE_FOLDER, true, 'the pair, below a user folder'],
    [['system_settings', 'archive', 'b'], ARCHIVE_FOLDER, true, 'the pair, above a user folder'],
    [['archive'], ARCHIVE_FOLDER, false, 'the NAME the folder left — the whole narrowing'],
    [['a', 'archive', 'b'], ARCHIVE_FOLDER, false, 'the name it left, nested'],
    [['system_settings'], ARCHIVE_FOLDER, false, 'the parent alone is not the folder'],
    [['system_settings', 'x', 'archive'], ARCHIVE_FOLDER, false, 'a SPLIT pair is not the folder'],
    [['archive', 'system_settings'], ARCHIVE_FOLDER, false, 'the pair reversed is not the pair'],
    [['system_settings', 'system_settings', 'archive'], ARCHIVE_FOLDER, true, 'a doubled parent'],
    [['archived'], ARCHIVE_FOLDER, false, 'segment equality, never a substring'],
    [['user_settings'], 'user_settings', true, 'a folder that did not move, at depth one'],
    [
      ['system_settings', 'user_settings'],
      'user_settings',
      true,
      'and at any depth, since its Deny did not move either'
    ]
  ])('segmentsHoldAppManaged(%j, %s) === %s — %s', (segments, folder, held) => {
    // This twin had NO test when it landed, and no key anywhere in the app exercised a split
    // pair. Five rules across the two trees delegate here; a caller's suite tests the caller.
    expect(segmentsHoldAppManaged(segments as string[], folder as string)).toBe(held);
  });
});
