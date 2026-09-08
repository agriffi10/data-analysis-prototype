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
  it('gives a moving folder two homes and everything else one', () => {
    // Spelled out as literals. A non-moving name acquiring a phantom second home is the thing
    // the Out of Scope clause forbids, and it would be invisible in every rule that loops a list.
    expect(appManagedPrefixes('alice/', ARCHIVE_FOLDER)).toEqual(['alice/archive/', 'alice/system_settings/archive/']);
    expect(appManagedPrefixes('alice/', 'user_settings')).toEqual(['alice/user_settings/']);
    expect(appManagedPrefixes('alice/', SYSTEM_SETTINGS_FOLDER)).toEqual(['alice/system_settings/']);
    // shared_tables does NOT move — those tables were sent to the space and are the user's to
    // edit — so it has one home, like any folder whose location the app does not manage.
    expect(appManagedPrefixes('alice/', SHARED_TABLES_FOLDER)).toEqual(['alice/shared_tables/']);
    expect(MOVING_FOLDERS).toEqual([ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER]);
  });

  it('normalizes nothing, exactly as the singular does not', () => {
    expect(appManagedPrefixes('', ARCHIVE_FOLDER)).toEqual(['archive/', 'system_settings/archive/']);
    expect(appManagedPrefixes('alice//', ARCHIVE_FOLDER)).toEqual([
      'alice//archive/',
      'alice//system_settings/archive/'
    ]);
  });

  it('does not BUILD either home by calling the singular', () => {
    // The duplication is the point, and the value-level tests above cannot enforce it: a derived
    // second home and a literal one agree exactly while the singular is still depth-one, which is
    // every day until the migration moves it. Derived, it would become
    // `${root}system_settings/system_settings/${folder}/` the moment that happens.
    //
    // A spy cannot see this — the call would be internal to the module, not through its exports —
    // so the guard reads the function's own body instead.
    const body = /export function appManagedPrefixes\([^)]*\)[^{]*\{([\s\S]*?)\n\}/.exec(ownerSource);
    expect(body, 'appManagedPrefixes is no longer a plain function declaration').not.toBeNull();
    expect(body![1]).not.toMatch(/\bappManagedPrefix\s*\(/);
    // Guard the guard: the body must be non-trivial, or a regex that matched nothing would pass.
    expect(body![1]).toContain('system_settings/');
  });

  it('still answers the OLD home the singular has left', () => {
    // This replaces the equality assertion that held the two together while the write was still
    // at depth one. Re-pointing that one would have restored exactly the coupling the literals
    // exist to avoid; what matters now is the opposite property. The first element is still the
    // depth-one path, which is where the objects written before the switch actually are, so every
    // rule built on the plural keeps refusing there until the migration has moved them.
    for (const root of ['', 'alice/', 'finance/']) {
      for (const folder of [ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER]) {
        const homes = appManagedPrefixes(root, folder);
        expect(homes[0]).toBe(`${root}${folder}/`);
        expect(homes[1]).toBe(appManagedPrefix(root, folder));
        expect(homes[0]).not.toBe(homes[1]);
      }
      // shared_tables never moved, so it never gained a second home to answer for.
      for (const stays of ['user_settings', SHARED_TABLES_FOLDER]) {
        expect(appManagedPrefixes(root, stays)).toEqual([appManagedPrefix(root, stays)]);
      }
    }
  });
});
