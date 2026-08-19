import {describe, expect, it, vi, beforeEach} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {CreateTableFromSpaceDialog, type BuildableSpace} from './CreateTableFromSpaceDialog';
import {createTableRefusal} from './createTableRefusal';
import {suggestedNameFor} from './useCreateTableFromSpace';
import {listFiles} from '../file-browser/fileBrowser.service';

// Integration style: the REAL dialog → real `DestinationPicker` → real `useFileBrowser`,
// mocking only the AWS boundary.
vi.mock('../file-browser/fileBrowser.service', async (importActual) => {
  const actual = await importActual<typeof import('../file-browser/fileBrowser.service')>();
  return {...actual, listFiles: vi.fn()};
});
vi.mock('../../lib/awsCredentials', () => ({
  getSessionCredentials: vi.fn().mockResolvedValue({success: true, data: {}})
}));

const PERSONAL: BuildableSpace = {
  id: 'personal',
  label: 'My files',
  bucket: 'dat-prod-user-space',
  rootPrefix: 'alice/',
  kind: 'personal'
};
const SHARED: BuildableSpace = {
  id: 'teamspace',
  label: 'teamspace',
  bucket: 'dat-prod-shared-space',
  rootPrefix: 'teamspace/',
  kind: 'shared'
};

const ok = <T,>(data: T) => ({success: true as const, data});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listFiles).mockResolvedValue(
    ok({files: [], folders: [{type: 'folder' as const, prefix: 'teamspace/sales/', name: 'sales'}], isTruncated: false})
  );
});

/**
 * The Files toolbar's Create table needs no folder step — the folder in view IS the answer.
 * From the Data Explorer there is no folder in view, so the same build needs one chosen first.
 * What these hold is that the extra step did not become a second set of RULES.
 */
describe('choosing a folder to build a table from', () => {
  it('opens on the space root with the build refused there, saying why', async () => {
    renderWithProviders(
      <CreateTableFromSpaceDialog
        spaces={[PERSONAL]}
        onChoose={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', {name: 'Create table from a folder'});
    await waitFor(() => expect(within(dialog).getByRole('button', {name: 'Choose this folder'})).toBeDisabled());
    // The SAME sentence the Files toolbar shows, and the picker's OWN reason slot rather than
    // a second status line under it: its default wording is move/copy's ("These items are
    // already here"), which says nothing about why a table cannot be built here.
    expect(within(dialog).getByRole('status').textContent).toBe(createTableRefusal('alice/', 'alice/'));
    expect(within(dialog).queryByText('These items are already here.')).not.toBeInTheDocument();
  });

  it('offers no space selector when there is only one space', async () => {
    renderWithProviders(
      <CreateTableFromSpaceDialog
        spaces={[PERSONAL]}
        onChoose={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    await screen.findByRole('dialog', {name: 'Create table from a folder'});
    // A one-option control is the shape the gating rule declines to render.
    expect(screen.queryByLabelText('Space')).not.toBeInTheDocument();
  });

  it('offers the selector when there is more than one, shared spaces marked', async () => {
    renderWithProviders(
      <CreateTableFromSpaceDialog
        spaces={[PERSONAL, SHARED]}
        onChoose={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const select = await screen.findByLabelText('Space');
    expect(within(select).getByRole('option', {name: 'My files'})).toBeInTheDocument();
    expect(within(select).getByRole('option', {name: 'teamspace (shared)'})).toBeInTheDocument();
  });

  it('hands back the folder AND the space\u2019s own database once one is chosen', async () => {
    const onChoose = vi.fn();
    const {user} = renderWithProviders(
      <CreateTableFromSpaceDialog
        spaces={[SHARED]}
        onChoose={onChoose}
        onCancel={vi.fn()}
      />
    );

    const dialog = await screen.findByRole('dialog', {name: 'Create table from a folder'});
    // Into a real folder — the root is refused, so the confirm is dead until the user moves.
    await user.click(await within(dialog).findByRole('button', {name: /sales/}));
    const confirm = within(dialog).getByRole('button', {name: 'Choose this folder'});
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);

    // The database is the space's own root segment, which is the space NAME for a shared space
    // and the username for a personal one — not the folder, and not the label.
    expect(onChoose).toHaveBeenCalledWith({
      spaceKind: 'shared',
      bucket: 'dat-prod-shared-space',
      database: 'teamspace',
      prefix: 'teamspace/sales/',
      rootPrefix: 'teamspace/'
    });
  });
});

describe('the name a chosen folder suggests', () => {
  it('is the folder’s own last segment', () => {
    expect(
      suggestedNameFor({
        spaceKind: 'personal',
        bucket: 'b',
        database: 'alice',
        prefix: 'alice/sales/2026/',
        rootPrefix: 'alice/'
      })
    ).toBe('2026');
  });

  it('is empty before a folder is chosen, rather than guessing', () => {
    expect(suggestedNameFor(null)).toBe('');
  });
});
