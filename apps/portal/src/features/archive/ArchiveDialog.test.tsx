import {describe, expect, it, vi} from 'vitest';
import {fireEvent, screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {ArchiveDialog} from './ArchiveDialog';
import type {ArchiveItem} from '../../types/archive.types';

const FOLDER: ArchiveItem = {kind: 'folder', key: 'alice/reports/2026/'};
const FILE: ArchiveItem = {kind: 'file', key: 'alice/notes.txt'};

function renderDialog(items: ArchiveItem[], overrides: Partial<Parameters<typeof ArchiveDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <ArchiveDialog
      items={items}
      rootPrefix="alice/"
      busy={false}
      submitError={null}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />
  );
  return {onConfirm, onCancel, ...result};
}

describe('ArchiveDialog', () => {
  it('names a single folder by its path within the space', () => {
    renderDialog([FOLDER]);

    expect(screen.getByRole('heading', {name: /reports\/2026\//})).toBeInTheDocument();
    // The space root is stripped: `alice/` means nothing to the person who owns it.
    expect(screen.getByRole('heading', {name: /Archive the folder/})).not.toHaveTextContent('alice/reports');
  });

  it('names a single file, and a multi-item selection by its count', () => {
    renderDialog([FILE]);
    expect(screen.getByRole('heading', {name: 'Archive “notes.txt”?'})).toBeInTheDocument();

    renderDialog([FOLDER, FILE]);
    expect(screen.getByRole('heading', {name: 'Archive 2 items?'})).toBeInTheDocument();
  });

  it('says where the data goes, where a restore puts it, what stops one, how long, what it costs and how to find it', () => {
    // The six facts the outside reviewers asked for, each by the phrase that carries it. None of
    // them can be inferred from a button reading "Archive".
    const {baseElement} = renderDialog([FOLDER]);
    const text = baseElement.textContent ?? '';

    for (const phrase of [
      /long-term archive storage/,
      /same folder/,
      /overwrites nothing/,
      /move or rename/,
      /folder you create with the same name/,
      /re-create folders/,
      /several hours/,
      /90 days/,
      /Restore Archived Data/
    ]) {
      expect(text).toMatch(phrase);
    }
  });

  it('never tells the user to destroy a file to make a restore fit', () => {
    // The files in a restore's way can be the only copy left, so the remedy is to move them.
    const {baseElement} = renderDialog([FOLDER, FILE]);

    expect(baseElement.textContent).not.toMatch(/delete|trash|overwrite it|replace/i);
  });

  it('warns that a folder takes everything inside it', () => {
    renderDialog([FOLDER]);

    expect(screen.getByText(/All files and subfolders it contains/i)).toBeInTheDocument();
  });

  it('does NOT claim the archive cannot be undone', () => {
    // It can — that is what a restore is, and this dialog says how long one takes. Borrowing the
    // delete confirm's "This can't be undone" would be the one sentence here that is false.
    renderDialog([FOLDER]);

    expect(screen.queryByText(/can’t be undone|cannot be undone/i)).not.toBeInTheDocument();
  });

  it('focuses Cancel, not the confirm', async () => {
    // FR-002 AC3. The one dialog in this app where the confirm is deliberately not the default:
    // archiving deletes the user's data, and a keystroke should not do that.
    renderDialog([FOLDER]);

    expect(screen.getByRole('button', {name: 'Cancel'})).toHaveFocus();
  });

  it('does not submit on Enter', async () => {
    // Built on ConfirmDialog rather than FormDialog precisely because FormDialog HAS an
    // Enter-to-submit affordance. Enter lands on the focused Cancel, which cancels.
    const user = userEvent.setup();
    const {onConfirm, onCancel} = renderDialog([FOLDER]);

    await user.keyboard('{Enter}');

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('confirms only when the confirm is actually pressed, with the name normalised', async () => {
    const user = userEvent.setup();
    const {onConfirm} = renderDialog([FOLDER]);

    await user.type(screen.getByLabelText('Name (optional)'), '  Q1   reports ');
    await user.click(screen.getByRole('button', {name: 'Archive'}));

    expect(onConfirm).toHaveBeenCalledWith('Q1 reports');
  });

  it.each([
    ['a right-to-left override', 'Q1\u202ereports'],
    ['a tab', 'Q1\treports']
  ])('refuses a name holding %s, says why, and archives nothing', async (_label, name) => {
    const user = userEvent.setup();
    const {onConfirm} = renderDialog([FOLDER]);
    const field = screen.getByLabelText('Name (optional)');

    fireEvent.change(field, {target: {value: name}});
    await user.click(screen.getByRole('button', {name: 'Archive'}));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(field).toHaveAccessibleDescription(/can’t contain tabs, line breaks or other control characters/);
  });

  it('keeps Enter in the Name field from archiving, because the field is in no form', async () => {
    const user = userEvent.setup();
    const {onConfirm} = renderDialog([FOLDER]);
    const field = screen.getByLabelText<HTMLInputElement>('Name (optional)');

    await user.type(field, 'Q1{Enter}');

    expect(field.form).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'Archive'})).toBeInTheDocument();
  });

  it('locks both controls and dismissal while the enqueue is in flight', async () => {
    // FR-002 AC4: Escape must not close a half-submitted request.
    const user = userEvent.setup();
    const {onCancel} = renderDialog([FOLDER], {busy: true});

    expect(screen.getByRole('button', {name: 'Starting…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancels on Escape when it is not busy', async () => {
    const user = userEvent.setup();
    const {onCancel} = renderDialog([FOLDER]);

    await user.keyboard('{Escape}');

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('renders a submit failure inline and stays open', () => {
    // FR-002 AC6. The message is already through `toUserMessage` by the time it arrives — raw
    // AWS text never reaches a user (SPEC-106) — so what is asserted here is that it is SHOWN.
    renderDialog([FOLDER], {submitError: 'Archiving is not configured'});

    expect(screen.getByRole('alert')).toHaveTextContent('Archiving is not configured');
    expect(screen.getByRole('button', {name: 'Archive'})).toBeEnabled();
  });

  it('lists the first few names and says how many more there are', () => {
    const many: ArchiveItem[] = Array.from({length: 8}, (_, i) => ({kind: 'file', key: `alice/f${i}.csv`}));
    renderDialog(many);

    expect(screen.getByText('f0.csv')).toBeInTheDocument();
    expect(screen.getByText(/and 3 more/)).toBeInTheDocument();
  });

  it('has no axe violations with focus in the open dialog', async () => {
    // Against the DRIVEN container, not a re-render of the closed state: a helper that renders
    // the element again checks a dialog nobody has opened and focus nobody has moved.
    const {container} = renderDialog([FOLDER, FILE]);

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
