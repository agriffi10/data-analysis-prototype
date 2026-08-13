import {describe, expect, it, vi} from 'vitest';
import {screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {RestoreArchiveDialog} from './RestoreArchiveDialog';

const ARCHIVE_ID = '3f8a1c2e-9b4d-4a17-8c65-2e0d7b1f4a93';

function renderDialog(overrides: Partial<Parameters<typeof RestoreArchiveDialog>[0]> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const result = renderWithProviders(
    <RestoreArchiveDialog
      spaceLabel="My Files"
      busy={false}
      submitError={null}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...overrides}
    />
  );
  return {onSubmit, onCancel, ...result};
}

describe('RestoreArchiveDialog', () => {
  it('focuses the id field on open', () => {
    renderDialog();

    expect(screen.getByLabelText('Archive id')).toHaveFocus();
  });

  it('submits a valid id from Enter in the field', async () => {
    // FR-003 AC5: the single-field case `submitOnEnterRef` exists for — and the opposite call
    // from ArchiveDialog, for the opposite reason.
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    await user.type(screen.getByLabelText('Archive id'), `${ARCHIVE_ID}{Enter}`);

    expect(onSubmit).toHaveBeenCalledWith(ARCHIVE_ID);
  });

  it('trims what was pasted, because an id copied from a receipt brings whitespace', async () => {
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    await user.type(screen.getByLabelText('Archive id'), `  ${ARCHIVE_ID}  `);
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    expect(onSubmit).toHaveBeenCalledWith(ARCHIVE_ID);
  });

  it('refuses a malformed id with an inline error naming what a valid one looks like', async () => {
    // FR-003 AC3. The server validates it again before building any key; this exists so a typo
    // costs a sentence now rather than a notification hours later.
    const user = userEvent.setup();
    const {onSubmit} = renderDialog();

    await user.type(screen.getByLabelText('Archive id'), 'not-an-id');
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('alert')).toHaveTextContent(/doesn’t look like an archive id/i);
    expect(screen.getByRole('alert')).toHaveTextContent(/3f8a1c2e/);
  });

  it('says nothing about the id until the user has actually tried', async () => {
    // An id is invalid for every keystroke but the last, so validating as you type makes the
    // field wrong about the user for the whole time they are filling it in.
    const user = userEvent.setup();
    renderDialog();

    await user.type(screen.getByLabelText('Archive id'), 'not-an-id');

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('leaves the submit control REACHABLE rather than disabling it', async () => {
    // SPEC-175's recorded rule: `submitDisabled` never stands in for a refusal. A disabled
    // button explains nothing, and the explanation is the whole point of the check.
    renderDialog();

    expect(screen.getByRole('button', {name: 'Restore'})).toBeEnabled();
  });

  it('names the space the restore lands in', () => {
    // FR-003 AC6. The space comes from the ROUTE (SPEC-113's rule), so the dialog has to say
    // which one — a user browsing a shared space would otherwise assume their own.
    renderDialog({spaceLabel: 'finance'});

    expect(screen.getByText('finance')).toBeInTheDocument();
  });

  it('says a restore takes hours and that a notification will follow', () => {
    renderDialog();

    expect(screen.getByText(/several hours/i)).toBeInTheDocument();
    expect(screen.getByText(/notification/i)).toBeInTheDocument();
  });

  it('says where to find an id', () => {
    renderDialog();

    expect(screen.getByText(/folder named after its id/i)).toBeInTheDocument();
  });

  it('locks while the enqueue is in flight', async () => {
    const user = userEvent.setup();
    const {onCancel} = renderDialog({busy: true});

    expect(screen.getByRole('button', {name: 'Starting…'})).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('renders a submit failure inline and keeps the typed id', async () => {
    const user = userEvent.setup();
    renderDialog({submitError: 'Restoring is not configured'});

    await user.type(screen.getByLabelText('Archive id'), ARCHIVE_ID);

    expect(screen.getByText('Restoring is not configured')).toBeInTheDocument();
    expect(screen.getByLabelText('Archive id')).toHaveValue(ARCHIVE_ID);
  });

  it('has no axe violations with focus in the open dialog', async () => {
    const {container} = renderDialog();

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('has no axe violations while showing its inline error', async () => {
    // The state a user is most likely to be reading with a screen reader, and the one a
    // closed-state re-render would never reach.
    const user = userEvent.setup();
    const {container} = renderDialog();

    await user.type(screen.getByLabelText('Archive id'), 'nope');
    await user.click(screen.getByRole('button', {name: 'Restore'}));

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
