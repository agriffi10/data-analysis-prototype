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

  it('anchors a folder directly under the space root, in either bucket', () => {
    expect(appManagedPrefix('alice/', ARCHIVE_FOLDER)).toBe('alice/archive/');
    expect(appManagedPrefix('finance/', ATHENA_RESULTS_FOLDER)).toBe('finance/athenaresults/');
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
    expect(MOVING_FOLDERS).toEqual([ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER, SHARED_TABLES_FOLDER]);
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

  it('agrees with the singular on its first element TODAY — SPEC-220 FR-001 deletes this', () => {
    // The plural spells both homes as literals precisely so the singular can move without
    // dragging them. This pins that they agree while the write still goes to depth one; when the
    // singular moves, this is the assertion expected to fail, and deleting it is the right
    // response rather than re-pointing it, which would restore the coupling the literals avoid.
    for (const root of ['', 'alice/', 'finance/']) {
      for (const folder of [ATHENA_RESULTS_FOLDER, ARCHIVE_FOLDER, SHARED_TABLES_FOLDER, 'user_settings']) {
        expect(appManagedPrefixes(root, folder)[0]).toBe(appManagedPrefix(root, folder));
      }
    }
  });
});
