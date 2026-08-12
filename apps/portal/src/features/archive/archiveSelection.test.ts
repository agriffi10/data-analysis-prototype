import {describe, expect, it} from 'vitest';
// The plane's own list, read as data. A hand-copied array here would be a second declaration of
// the same rule — and a divergence shows up as a request the browser sends and the plane refuses.
import arcommonConfig from '../../../../../lambdas/archive-common/arcommon/config.py?raw';
import {ARCHIVE_RESERVED_ROOTS, archiveRefusal} from './archiveSelection';
import type {ArchiveItem} from '../../types/archive.types';

const folder = (key: string): ArchiveItem => ({kind: 'folder', key});
const file = (key: string): ArchiveItem => ({kind: 'file', key});

describe('the browser and the plane refuse the same folders', () => {
  it('names exactly what arcommon.config.RESERVED_SOURCE_ROOTS names', () => {
    // FR-001 AC5. Not a spot check: SET EQUALITY, because the failure this guards against is a
    // folder the browser lets you select and the plane then refuses, hours of confusion later.
    const block = /RESERVED_SOURCE_ROOTS = \(([^)]*)\)/.exec(arcommonConfig);
    expect(block, 'arcommon no longer declares RESERVED_SOURCE_ROOTS as a tuple literal').not.toBeNull();
    const plane = [...block![1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);

    expect(plane.length).toBeGreaterThan(0);
    expect([...ARCHIVE_RESERVED_ROOTS].sort()).toEqual([...plane].sort());
  });
});

describe('archiveRefusal', () => {
  it('allows an ordinary selection', () => {
    expect(archiveRefusal([folder('alice/reports/'), file('alice/notes.txt')], 'alice/')).toBeNull();
  });

  it('refuses the reserved folder itself, named in the message', () => {
    expect(archiveRefusal([folder('alice/athenaresults/')], 'alice/')).toContain('athenaresults');
    expect(archiveRefusal([folder('alice/archive/')], 'alice/')).toContain('archive');
  });

  it('refuses anything BENEATH a reserved folder', () => {
    expect(archiveRefusal([file('alice/athenaresults/q1.csv')], 'alice/')).not.toBeNull();
  });

  it('refuses an ANCESTOR that contains one — the third case, and the one authors miss', () => {
    // Selecting the space root passes both obvious checks, and the plane expands a folder by
    // LISTING its prefix — so it would carry `alice/user_settings/` out with everything else and
    // then delete it (`arcommon.authz.assert_not_reserved` records exactly this).
    expect(archiveRefusal([folder('alice/')], 'alice/')).not.toBeNull();
  });

  it('leaves a file whose name merely starts the same way alone', () => {
    // `alice/archived-notes.txt` against `alice/archive/` is an ordinary file. Comparing the raw
    // key rather than its trailing-slash form is what gets this wrong.
    expect(archiveRefusal([file('alice/archived-notes.txt')], 'alice/')).toBeNull();
    expect(archiveRefusal([folder('alice/archived/')], 'alice/')).toBeNull();
  });

  it('anchors at the SPACE ROOT, so a user’s own nested folder of that name is archivable', () => {
    expect(archiveRefusal([folder('alice/backups/archive/')], 'alice/')).toBeNull();
    expect(archiveRefusal([folder('alice/reports/shared_tables/')], 'alice/')).toBeNull();
  });

  it('refuses the WHOLE selection when one item is reserved', () => {
    // Archiving deletes the source, so a selection with one bad row in it must not become a
    // partial archive whose refused row was silently dropped — the plane's own rule.
    expect(archiveRefusal([folder('alice/reports/'), folder('alice/archive/')], 'alice/')).not.toBeNull();
  });

  it('holds identically in a shared space', () => {
    expect(archiveRefusal([folder('finance/athenaresults/')], 'finance/')).not.toBeNull();
    expect(archiveRefusal([folder('finance/reports/')], 'finance/')).toBeNull();
  });
});
