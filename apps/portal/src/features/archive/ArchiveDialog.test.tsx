import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
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

  it('says the data leaves this space, and that a restore takes hours', () => {
    // FR-002 AC2. Both are consequences of decisions recorded in SPEC-168 and SPEC-171, and
    // neither can be inferred from a button reading "Archive".
    renderDialog([FOLDER]);

    expect(screen.getByText(/removed from this space/i)).toBeInTheDocument();
    expect(screen.getByText(/several hours/i)).toBeInTheDocument();
  });

  it('warns that a folder takes everything inside it', () => {
    renderDialog([FOLDER]);

    expect(screen.getByText(/All files and subfolders it contains/i)).toBeInTheDocument();
  });

  it('does NOT claim the archive cannot be undone', () => {
    // It can — that is what a restore is, and this dialog says how long one takes. Borrowing the
    // delete confirm's "This can't be undone" would be the one sentence here that is false.
    renderDialog([FOLDER]);

    expect(screen.queryByText(/can’t be undone/i)).not.toBeInTheDocument();
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

  it('confirms only when the confirm is actually pressed', async () => {
    const user = userEvent.setup();
    const {onConfirm} = renderDialog([FOLDER]);

    await user.click(screen.getByRole('button', {name: 'Archive'}));

    expect(onConfirm).toHaveBeenCalledTimes(1);
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
