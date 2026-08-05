import {describe, expect, it, vi, beforeEach} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {TableShareDialog} from './TableShareDialog';
import {getUserDirectory} from '../user-directory';

// The user-kind entry is now a `UsernameCombobox`, so this suite renders through the provider
// stack and mocks the ONE service boundary the field reaches (SPEC-148). Every behaviour the
// SPEC-093 suite pinned is preserved below, updated rather than replaced — a case this spec did
// not intend to change should fail loudly.
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

const SOURCE = {database: 'alice', table: 'orders'};

const directory = (usernames: string[] = ['bob', 'bob_smith', 'cara', 'alice']) => ({
  success: true as const,
  data: {usernames, generatedAt: '2026-08-05T04:00:11Z'}
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUserDirectory).mockResolvedValue(directory());
});

function renderDialog(over: Partial<React.ComponentProps<typeof TableShareDialog>> = {}) {
  const onSubmit = vi.fn();
  const onCancel = vi.fn();
  const rendered = renderWithProviders(
    <TableShareDialog
      source={SOURCE}
      onSubmit={onSubmit}
      onCancel={onCancel}
      {...over}
    />
  );
  return {onSubmit, onCancel, user: rendered.user};
}

const entryInput = () => screen.getByLabelText(/Usernames|Space names/) as HTMLInputElement;
const addButton = () => screen.getByRole('button', {name: 'Add'});
const shareButton = () => screen.getByRole('button', {name: /Share|Submitting/});
const chipList = () => screen.getByRole('list', {name: 'Recipients'});

async function addRecipients(user: ReturnType<typeof renderDialog>['user'], raw: string) {
  await user.click(entryInput());
  await user.keyboard(raw);
  await user.click(addButton());
}

describe('TableShareDialog', () => {
  it('shows the fully-qualified source read-only and defaults the result name to the source table', () => {
    renderDialog();
    expect(screen.getByText('alice.orders')).toBeInTheDocument();
    expect(screen.getByLabelText('Table name for recipients')).toHaveValue('orders');
  });

  it('adds comma/space-separated names as removable chips tagged with the selected kind', async () => {
    // THE USER ENTRY IS STILL A BULK FIELD. `bob, cara` in one go must still produce two chips —
    // that is what `onCommitMany` is for, and losing it would be a silent regression.
    const {user} = renderDialog();
    await addRecipients(user, 'bob, cara');

    expect(within(chipList()).getAllByRole('listitem')).toHaveLength(2);
    expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    // The entry box clears after an add.
    expect(entryInput()).toHaveValue('');

    await user.click(within(chipList()).getByRole('button', {name: 'Remove user bob'}));
    expect(within(chipList()).queryByRole('button', {name: 'Remove user bob'})).not.toBeInTheDocument();
    expect(within(chipList()).getByRole('button', {name: 'Remove user cara'})).toBeInTheDocument();
  });

  it('tags entries added under "Shared spaces" as spaces (a mixed list is allowed)', async () => {
    const {user} = renderDialog();
    await addRecipients(user, 'bob');
    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await addRecipients(user, 'salesteam');

    expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    expect(within(chipList()).getByRole('button', {name: 'Remove space salesteam'})).toBeInTheDocument();
  });

  it('keeps committed recipients of both kinds when the toggle is switched', async () => {
    const {user} = renderDialog();
    await addRecipients(user, 'bob');
    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await addRecipients(user, 'salesteam');
    await user.click(screen.getByRole('radio', {name: 'Users'}));

    expect(within(chipList()).getAllByRole('listitem')).toHaveLength(2);
  });

  it('Enter in the recipient input adds names instead of submitting', async () => {
    const {onSubmit, user} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bob{Enter}');

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
  });

  it('dedupes an already-added name of the same kind', async () => {
    const {user} = renderDialog();
    await addRecipients(user, 'bob');
    await addRecipients(user, 'bob');

    expect(within(chipList()).getAllByRole('listitem')).toHaveLength(1);
  });

  it('SURFACES malformed tokens rather than dropping them (SPEC-148 FR-003)', async () => {
    // A deliberate behaviour change from SPEC-093, where `parseMemberInput` dropped them without
    // comment and the user watched half their entry disappear.
    const {user} = renderDialog();
    await addRecipients(user, 'bob 1bad -x');

    expect(within(chipList()).getAllByRole('listitem')).toHaveLength(1);
    expect(entryInput()).toHaveValue('1bad -x');
    expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();
  });

  it('disables Share until there is at least one recipient and a valid name', async () => {
    const {onSubmit, user} = renderDialog();
    expect(shareButton()).toBeDisabled();

    await addRecipients(user, 'bob');
    expect(shareButton()).toBeEnabled();

    const nameInput = screen.getByLabelText('Table name for recipients');
    await user.clear(nameInput);
    await user.type(nameInput, 'Bad-Name');
    expect(screen.getByText(/Use 3–63 characters/)).toBeInTheDocument();
    expect(shareButton()).toBeDisabled();

    await user.clear(nameInput);
    await user.type(nameInput, 'orders_copy');
    await user.click(shareButton());

    // FIELD-BY-FIELD, the same payload SPEC-093 sent for the same recipients.
    expect(onSubmit).toHaveBeenCalledWith({
      tableName: 'orders_copy',
      recipients: [{kind: 'user', name: 'bob'}]
    });
  });

  it('locks the form while busy and surfaces a submit error inline', () => {
    renderDialog({busy: true, submitError: 'Failed to submit the request'});
    expect(screen.getByRole('button', {name: 'Submitting…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    expect(entryInput()).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to submit the request');
  });

  it('Cancel invokes onCancel', async () => {
    const {onCancel, user} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Cancel'}));
    expect(onCancel).toHaveBeenCalled();
  });
});

describe('TableShareDialog — suggestions', () => {
  it('suggests usernames under the Users kind', async () => {
    const {user} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bob');

    await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['bob', 'bob_smith']));
  });

  it('offers NO suggestions under the Shared spaces kind', async () => {
    // Space names are not in the user directory; offering usernames here would be actively wrong.
    const {user} = renderDialog();
    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await user.click(entryInput());
    await user.keyboard('bob');

    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('does NOT exclude the current user', async () => {
    // Sharing a table into your own database is something the pipeline allows; the field must
    // not invent a restriction the control plane does not have.
    const {user} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('alice{Enter}');

    expect(within(chipList()).getByRole('button', {name: 'Remove user alice'})).toBeInTheDocument();
  });

  it('stays fully usable when the directory is unavailable', async () => {
    vi.mocked(getUserDirectory).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {onSubmit, user} = renderDialog();

    await addRecipients(user, 'someone_new');
    await user.click(shareButton());

    expect(onSubmit).toHaveBeenCalledWith({
      tableName: 'orders',
      recipients: [{kind: 'user', name: 'someone_new'}]
    });
    expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
  });

  it('commits a valid unlisted name with a neutral note when the directory IS ready', async () => {
    const {user} = renderDialog();
    await addRecipients(user, 'someone_new');

    expect(within(chipList()).getByRole('button', {name: 'Remove user someone_new'})).toBeInTheDocument();
    expect(await screen.findByText(/not in the directory/i)).toBeInTheDocument();
    expect(shareButton()).toBeEnabled();
  });
});
