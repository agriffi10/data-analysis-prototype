import {describe, expect, it, vi} from 'vitest';
import {createEvent, fireEvent, render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {USER_EVENT_OPTIONS} from '../../test/renderWithProviders';
import {SaveQueryDialog} from './SaveQueryDialog';
import type {QuerySpace} from '../catalog/catalog.types';

describe('SaveQueryDialog', () => {
  const mine: QuerySpace = {
    id: 'personal',
    label: 'alice',
    bucket: 'user-space',
    rootPrefix: 'alice/',
    rootLabel: 'My Files'
  };
  const team: QuerySpace = {
    id: 'project_alpha',
    label: 'project_alpha',
    bucket: 'shared-space',
    rootPrefix: 'project_alpha/',
    rootLabel: 'project_alpha'
  };

  function setup(over: Partial<Parameters<typeof SaveQueryDialog>[0]> = {}) {
    const onSave = vi.fn();
    const onCancel = vi.fn();
    const user = userEvent.setup(USER_EVENT_OPTIONS);
    const view = render(
      <SaveQueryDialog
        initialName=""
        spaces={[mine, team]}
        initialSpace={mine}
        busy={false}
        onSave={onSave}
        onCancel={onCancel}
        {...over}
      />
    );
    return {onSave, onCancel, view, user};
  }

  const save = () => screen.getByRole('button', {name: 'Save'});

  it('lists exactly the spaces it is given, personal first, and submits the chosen one', async () => {
    // SPEC-175 FR-001. The list is the CALLER's — already `sharedWorkspaces`-gated — so
    // the dialog neither adds a space nor drops one.
    const {onSave, user} = setup();
    const select = screen.getByLabelText('Space');
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent)
    ).toEqual(['alice', 'project_alpha']);

    await user.selectOptions(select, 'project_alpha');
    await user.type(screen.getByLabelText('Name'), '  Quarterly  ');
    await user.click(save());

    expect(onSave).toHaveBeenCalledWith({space: team, name: 'Quarterly'});
  });

  it('opens on the space it is handed, not always on personal', () => {
    setup({initialSpace: team});
    expect(screen.getByLabelText('Space')).toHaveValue('project_alpha');
  });

  it('falls back to personal when the handed space is not in the list (membership revoked)', () => {
    // FR-001 AC4: a linked tab whose space the user has left still opens a working dialog.
    setup({initialSpace: null, spaces: [mine]});
    expect(screen.getByLabelText('Space')).toHaveValue('personal');
    expect(screen.queryByText(/project_alpha/)).not.toBeInTheDocument();
  });

  it('ASKS on a re-save too, pre-filled with the linked file’s name (SPEC-173)', async () => {
    // A change from SPEC-043's silent write-back: a user about to overwrite a file
    // should be told which file, in which space, before it happens.
    const {onSave, user} = setup({initialName: 'Monthly revenue'});
    expect(screen.getByLabelText('Name')).toHaveValue('Monthly revenue');
    expect(screen.getByText(/saved_queries/)).toBeInTheDocument();

    await user.click(save());
    expect(onSave).toHaveBeenCalledWith({space: mine, name: 'Monthly revenue'});
  });

  it('says a re-save replaces the linked file — only while the key still matches it', async () => {
    // FR-004's no-second-confirm case, in words. The sentence tracks the KEY: changing
    // either the name or the space makes it a different file and the promise goes away.
    const linked = {spaceId: 'personal', bucket: 'user-space', key: 'alice/saved_queries/Monthly.sql', name: 'Monthly'};
    const {user} = setup({initialName: 'Monthly', linked});
    expect(screen.getByText(/replacing the file this tab was opened from/)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Space'), 'project_alpha');
    expect(screen.queryByText(/replacing the file this tab was opened from/)).not.toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Space'), 'personal');
    await user.type(screen.getByLabelText('Name'), '-v2');
    expect(screen.queryByText(/replacing the file this tab was opened from/)).not.toBeInTheDocument();
  });

  it('refuses an invalid name ON SUBMIT — the control is reachable, not disabled', async () => {
    // FR-002 AC5 / SPEC-167: `submitDisabled` in place of a refusal makes the message dead
    // code, and an "it's disabled" assertion passes straight over the acceptance criterion.
    const {onSave, user} = setup();
    expect(save()).toBeEnabled();

    await user.type(screen.getByLabelText('Name'), 'a/b');
    expect(save()).toBeEnabled();
    await user.click(save());

    expect(screen.getByText(/cannot contain/i)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('refuses an EMPTY name on submit the same way', async () => {
    const {onSave, user} = setup();
    await user.click(save());
    expect(screen.getByText(/cannot be empty/i)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('renders the host’s mapped write failure on the field, and keeps what was chosen', () => {
    // FR-006: the message is `toUserMessage`'s, rendered inline rather than as a toast, and
    // the destination control stays interactive so another space is one click away.
    setup({error: 'You don’t have access to that space.', initialSpace: team, initialName: 'Quarterly'});
    expect(screen.getByText('You don’t have access to that space.')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Quarterly');
    expect(screen.getByLabelText('Space')).toHaveValue('project_alpha');
    expect(screen.getByLabelText('Space')).toBeEnabled();
  });

  it('locks submit while a write is in flight', () => {
    setup({busy: true, initialName: 'Quarterly'});
    expect(screen.getByRole('button', {name: 'Saving…'})).toBeDisabled();
  });

  it('EXPLAINS itself when there is nowhere to save, rather than being a disabled button', () => {
    // FR-007. The banner is the refusal and it is in the DOM; asserting a disabled
    // attribute instead is the SPEC-167 mistake this criterion exists to prevent.
    const {onSave} = setup({spaces: [], initialSpace: null});
    expect(screen.getByText(/There’s nowhere to save this query/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Space')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Name')).not.toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('Enter submits from the NAME field only, never from the space control (SPEC-155)', async () => {
    // ASSERTED VIA `defaultPrevented`, NOT VIA "onSave was not called". jsdom implements no
    // implicit form submission, so `expect(onSave).not.toHaveBeenCalled()` on the select
    // holds whatever `FormDialog` does — measured: deleting its target guard entirely left
    // that assertion green. A browser DOES submit on Enter in a closed select, so what has
    // to be true is that the event was suppressed before it could (FR-004 AC8).
    const {onSave, user} = setup({initialName: 'Quarterly'});

    // `createEvent` + `fireEvent` stay here on purpose: `defaultPrevented` is only readable off
    // the event object, and `userEvent` never hands it back.
    const onSelect = createEvent.keyDown(screen.getByLabelText('Space'), {key: 'Enter'});
    fireEvent(screen.getByLabelText('Space'), onSelect);
    expect(onSelect.defaultPrevented).toBe(true);
    expect(onSave).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText('Name'), '{Enter}');
    expect(onSave).toHaveBeenCalledWith({space: mine, name: 'Quarterly'});
  });

  it('drops the host’s failure message once the user changes what it judged (FR-006)', async () => {
    // The message names a destination the user has since abandoned; the dialog cannot clear
    // a prop it does not own, so it stops rendering it instead.
    const {user} = setup({error: 'You don’t have permission to do that.', initialName: 'Quarterly'});
    expect(screen.getByText('You don’t have permission to do that.')).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('Space'), 'project_alpha');
    expect(screen.queryByText('You don’t have permission to do that.')).not.toBeInTheDocument();
  });

  it('Cancel closes the dialog', async () => {
    const {onCancel, user} = setup();
    await user.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
