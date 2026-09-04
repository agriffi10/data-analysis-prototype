import {describe, it, expect} from 'vitest';
import {partitionSystemFolders, SYSTEM_FOLDER_GROUP_NAME, SYSTEM_GROUPED_FOLDERS} from './systemFolders';
import {validateFolderName} from './fileBrowser.service';
import {HIDDEN_BROWSER_FOLDERS} from './protectedFolders';
import type {S3FolderItem} from '../../types/s3.types';

const folder = (prefix: string): S3FolderItem => ({
  type: 'folder',
  prefix,
  name: prefix.replace(/\/$/, '').split('/').pop() ?? ''
});

describe('validateFolderName reserves the group name', () => {
  it('refuses the name the listing spends on the group row', () => {
    expect(validateFolderName(SYSTEM_FOLDER_GROUP_NAME)).toMatch(/name the file list uses/);
  });

  it('leaves ordinary names, and near-misses, alone', () => {
    // Exact match only: a differently-cased or suffixed name is a distinct row and reads as one.
    expect(validateFolderName('reports')).toBeNull();
    expect(validateFolderName('System_Settings')).toBeNull();
    expect(validateFolderName('system_settings_old')).toBeNull();
  });
});

describe('partitionSystemFolders', () => {
  it('groups the app-managed roots and leaves the rest in listing order', () => {
    const listing = [
      folder('alice/archive/'),
      folder('alice/athenaresults/'),
      folder('alice/reports/'),
      folder('alice/saved_queries/'),
      folder('alice/shared_tables/')
    ];

    const {ordinary, grouped} = partitionSystemFolders(listing, 'alice/');

    // `saved_queries/` stays ordinary: the user curates what is in it, which is the line the
    // request itself drew.
    expect(ordinary.map((f) => f.name)).toEqual(['reports', 'saved_queries']);
    expect(grouped.map((f) => f.name)).toEqual(['archive', 'athenaresults', 'shared_tables']);
  });

  it('anchors at the space root, so a user’s own folder of the same name is ordinary', () => {
    const nested = [folder('alice/projects/archive/'), folder('alice/projects/notes/')];

    const {ordinary, grouped} = partitionSystemFolders(nested, 'alice/');

    expect(grouped).toEqual([]);
    expect(ordinary.map((f) => f.name)).toEqual(['archive', 'notes']);
  });

  it('reads the root it is given, so a shared space groups its own folders', () => {
    const listing = [folder('finance/athenaresults/'), folder('finance/ledgers/')];

    const {ordinary, grouped} = partitionSystemFolders(listing, 'finance/');

    expect(grouped.map((f) => f.name)).toEqual(['athenaresults']);
    expect(ordinary.map((f) => f.name)).toEqual(['ledgers']);
  });

  it('groups nothing that is hidden outright — a hidden folder never reaches a row', () => {
    // The two lists must not overlap: a folder in both would be filtered out before the
    // partition ran, and the group's count would then promise a row nobody can open.
    expect(SYSTEM_GROUPED_FOLDERS.filter((n) => (HIDDEN_BROWSER_FOLDERS as readonly string[]).includes(n))).toEqual([]);
  });
});
