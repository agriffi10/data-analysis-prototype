import { describe, it, expect } from 'vitest';
import { HIDDEN_BROWSER_FOLDERS, PICKER_LOCKED_FOLDERS, isRootFolderNamed } from './protectedFolders';

describe('protectedFolders', () => {
  it('hides user_settings/ from the browser; locks athenaresults/ + user_settings/ from the picker', () => {
    expect(HIDDEN_BROWSER_FOLDERS).toContain('user_settings');
    expect(HIDDEN_BROWSER_FOLDERS).not.toContain('athenaresults');
    expect(PICKER_LOCKED_FOLDERS).toEqual(expect.arrayContaining(['athenaresults', 'user_settings']));
  });

  it('matches a named folder only at the user root', () => {
    expect(isRootFolderNamed('alice/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(true);
    // A nested folder that merely shares the name is a normal user folder.
    expect(isRootFolderNamed('alice/docs/user_settings/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
    // Unrelated folders are untouched.
    expect(isRootFolderNamed('alice/photos/', 'alice/', HIDDEN_BROWSER_FOLDERS)).toBe(false);
  });
});
