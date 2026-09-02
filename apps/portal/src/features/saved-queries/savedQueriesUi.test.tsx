import {describe, expect, it, vi} from 'vitest';
import {createEvent, fireEvent, render, screen, within} from '@testing-library/react';
import {SaveQueryDialog} from './SaveQueryDialog';
import type {QuerySpace} from '../catalog/catalog.types';

describe('SaveQueryDialog', () => {
  const mine: QuerySpace = {
    id: 'personal',
    label: 'My files',
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
    return {onSave, onCancel, view};
  }

  const save = () => screen.getByRole('button', {name: 'Save'});

  it('lists exactly the spaces it is given, personal first, and submits the chosen one', () => {
    // SPEC-175 FR-001. The list is the CALLER's — already `sharedWorkspaces`-gated — so
    // the dialog neither adds a space nor drops one.
    const {onSave} = setup();
    const select = screen.getByLabelText('Space');
    expect(
      within(select)
        .getAllByRole('option')
        .map((o) => o.textContent)
    ).toEqual(['My files', 'project_alpha']);

    fireEvent.change(select, {target: {value: 'project_alpha'}});
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: '  Quarterly  '}});
    fireEvent.click(save());

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

  it('ASKS on a re-save too, pre-filled with the linked file’s name (SPEC-173)', () => {
    // A change from SPEC-043's silent write-back: a user about to overwrite a file
    // should be told which file, in which space, before it happens.
    const {onSave} = setup({initialName: 'Monthly revenue'});
    expect(screen.getByLabelText('Name')).toHaveValue('Monthly revenue');
    expect(screen.getByText(/saved_queries/)).toBeInTheDocument();

    fireEvent.click(save());
    expect(onSave).toHaveBeenCalledWith({space: mine, name: 'Monthly revenue'});
  });

  it('says a re-save replaces the linked file — only while the key still matches it', () => {
    // FR-004's no-second-confirm case, in words. The sentence tracks the KEY: changing
    // either the name or the space makes it a different file and the promise goes away.
    const linked = {spaceId: 'personal', bucket: 'user-space', key: 'alice/saved_queries/Monthly.sql', name: 'Monthly'};
    setup({initialName: 'Monthly', linked});
    expect(screen.getByText(/replacing the file this tab was opened from/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Space'), {target: {value: 'project_alpha'}});
    expect(screen.queryByText(/replacing the file this tab was opened from/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Space'), {target: {value: 'personal'}});
    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'Monthly-v2'}});
    expect(screen.queryByText(/replacing the file this tab was opened from/)).not.toBeInTheDocument();
  });

  it('refuses an invalid name ON SUBMIT — the control is reachable, not disabled', () => {
    // FR-002 AC5 / SPEC-167: `submitDisabled` in place of a refusal makes the message dead
    // code, and an "it's disabled" assertion passes straight over the acceptance criterion.
    const {onSave} = setup();
    expect(save()).toBeEnabled();

    fireEvent.change(screen.getByLabelText('Name'), {target: {value: 'a/b'}});
    expect(save()).toBeEnabled();
    fireEvent.click(save());

    expect(screen.getByText(/cannot contain/i)).toBeInTheDocument();
    expect(onSave).not.toHaveBeenCalled();
  });

  it('refuses an EMPTY name on submit the same way', () => {
    const {onSave} = setup();
    fireEvent.click(save());
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

  it('Enter submits from the NAME field only, never from the space control (SPEC-155)', () => {
    // ASSERTED VIA `defaultPrevented`, NOT VIA "onSave was not called". jsdom implements no
    // implicit form submission, so `expect(onSave).not.toHaveBeenCalled()` on the select
    // holds whatever `FormDialog` does — measured: deleting its target guard entirely left
    // that assertion green. A browser DOES submit on Enter in a closed select, so what has
    // to be true is that the event was suppressed before it could (FR-004 AC8).
    const {onSave} = setup({initialName: 'Quarterly'});

    const onSelect = createEvent.keyDown(screen.getByLabelText('Space'), {key: 'Enter'});
    fireEvent(screen.getByLabelText('Space'), onSelect);
    expect(onSelect.defaultPrevented).toBe(true);
    expect(onSave).not.toHaveBeenCalled();

    fireEvent.keyDown(screen.getByLabelText('Name'), {key: 'Enter'});
    expect(onSave).toHaveBeenCalledWith({space: mine, name: 'Quarterly'});
  });

  it('drops the host’s failure message once the user changes what it judged (FR-006)', () => {
    // The message names a destination the user has since abandoned; the dialog cannot clear
    // a prop it does not own, so it stops rendering it instead.
    setup({error: 'You don’t have permission to do that.', initialName: 'Quarterly'});
    expect(screen.getByText('You don’t have permission to do that.')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Space'), {target: {value: 'project_alpha'}});
    expect(screen.queryByText('You don’t have permission to do that.')).not.toBeInTheDocument();
  });

  it('Cancel closes the dialog', () => {
    const {onCancel} = setup();
    fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
