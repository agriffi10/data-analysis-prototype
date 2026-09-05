import {describe, expect, it} from 'vitest';
import {appManagedPrefix, ARCHIVE_FOLDER, ATHENA_RESULTS_FOLDER, SHARED_TABLES_FOLDER} from './appManagedPaths';

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
