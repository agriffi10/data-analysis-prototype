import {describe, expect, it, vi, beforeEach} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {CreateTableFromSpaceDialog, type BuildableSpace} from './CreateTableFromSpaceDialog';
import {createTableRefusal} from './createTableRefusal';
import {suggestedNameFor} from './useCreateTableFromSpace';

vi.mock('../file-browser', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../file-browser')>())
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

beforeEach(() => vi.clearAllMocks());

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
