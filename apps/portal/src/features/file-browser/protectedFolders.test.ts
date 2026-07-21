import {describe, it, expect} from 'vitest';
import {HIDDEN_BROWSER_FOLDERS, PICKER_LOCKED_FOLDERS, isRootFolderNamed} from './protectedFolders';

describe('protectedFolders', () => {
  it('hides user_settings/ from the browser; locks athenaresults/ + user_settings/ from the picker', () => {
    expect(HIDDEN_BROWSER_FOLDERS).toContain('user_settings');
    expect(HIDDEN_BROWSER_FOLDERS).not.toContain('athenaresults');
    expect(PICKER_LOCKED_FOLDERS).toEqual(expect.arrayContaining(['athenaresults', 'user_settings']));
  });

  it('hides _data-quality-reports/ from BOTH the browser and the picker (SPEC-113 FR-004)', () => {
    // Both lists, not one: hidden-but-pasteable would be a folder the user can't
    // see and can still drop files into. Nothing else hides it — the leading `_`
    // is a Lambda-side convention the SPA never learned.
    expect(HIDDEN_BROWSER_FOLDERS).toContain('_data-quality-reports');
    expect(PICKER_LOCKED_FOLDERS).toContain('_data-quality-reports');
    expect(isRootFolderNamed('alice/_data-quality-reports/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
    // Shared spaces keep their reports at the space root, so the same match holds there.
    expect(isRootFolderNamed('team-data/_data-quality-reports/', 'team-data/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
  });

  it('matches a named folder only at the user root', () => {
    expect(isRootFolderNamed('alice/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
    // A nested folder that merely shares the name is a normal user folder.
    expect(isRootFolderNamed('alice/docs/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
    // Unrelated folders are untouched.
    expect(isRootFolderNamed('alice/photos/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
  });
});
