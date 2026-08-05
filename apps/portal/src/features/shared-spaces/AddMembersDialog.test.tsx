import {describe, it, expect, vi, beforeEach} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {AddMembersDialog} from './AddMembersDialog';
import {parseMemberInput} from './memberInput';
import {getUserDirectory} from '../user-directory';

// The dialog's field is now a `UsernameChipsField`, so this suite renders through the provider
// stack and mocks the one service boundary it reaches. Every SPEC-053 behaviour below is
// preserved and updated rather than replaced (SPEC-148 FR-007).
vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

const DIRECTORY = ['bob', 'cara', 'dave', 'owner'];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUserDirectory).mockResolvedValue({
    success: true,
    data: {usernames: DIRECTORY, generatedAt: '2026-08-05T04:00:11Z'}
  });
});

// `parseMemberInput` itself is now pinned directly in memberInput.test.ts; these three cases
// stay because they are the ones SPEC-053 wrote, and this spec did not intend to change them.
describe('parseMemberInput (SPEC-053 FR-002)', () => {
  it('splits on commas/whitespace/newlines, trims, lowercases, de-dupes', () => {
    expect(parseMemberInput('Bob, cara\n  bob   DAVE')).toEqual(['bob', 'cara', 'dave']);
  });

  it('drops tokens that fail the catalog-safe username rule', () => {
    // 'x' too short, 'No-Dashes' has a dash, '1leading' starts with a digit.
    expect(parseMemberInput('x, no-dashes, 1leading, validname')).toEqual(['validname']);
  });

  it('returns an empty list for blank input', () => {
    expect(parseMemberInput('   \n  ')).toEqual([]);
  });
});

function renderDialog(over: Partial<React.ComponentProps<typeof AddMembersDialog>> = {}) {
  const onAdd = vi.fn();
  const onCancel = vi.fn();
  const {user} = renderWithProviders(
    <AddMembersDialog
      existing={[]}
      onAdd={onAdd}
      onCancel={onCancel}
      {...over}
    />
  );
  return {onAdd, onCancel, user};
}

const field = () => screen.getByRole('combobox', {name: 'Usernames'});
const addButton = () => screen.getByRole('button', {name: /Add|Adding/});
const chips = () => screen.queryByRole('list', {name: 'Members to add'});

describe('AddMembersDialog', () => {
  it('sends the parsed list, excluding usernames already in the space', async () => {
    // The `existing` prop already includes the OWNER, and it is passed straight through as the
    // field's `exclude` — a like-for-like translation of the filter the textarea applied, not a
    // new restriction.
    const {onAdd, user} = renderDialog({existing: ['owner', 'cara']});
    await user.click(field());
    await user.keyboard('bob, cara, dave{Enter}');

    await user.click(addButton());

    expect(onAdd).toHaveBeenCalledWith(['bob', 'dave']);
  });

  it('refuses an existing member by name rather than silently dropping them', async () => {
    const {user} = renderDialog({existing: ['cara']});
    await user.click(field());
    await user.keyboard('cara{Enter}');

    expect(screen.getByRole('alert')).toHaveTextContent('cara is already a member of this space.');
    expect(chips()).not.toBeInTheDocument();
  });

  it('excludes existing members from the suggestions', async () => {
    const {user} = renderDialog({existing: ['bob']});
    await user.click(field());
    await user.keyboard('b');

    await waitFor(() => expect(field()).toHaveValue('b'));
    expect(screen.queryAllByRole('option')).toHaveLength(0);
  });

  it('disables Add until there is at least one valid new username', async () => {
    const {user} = renderDialog();
    expect(addButton()).toBeDisabled();

    await user.click(field());
    await user.keyboard('bob{Enter}');

    expect(addButton()).toBeEnabled();
  });

  it('keeps the empty-state sentence exactly as it reads', async () => {
    // This sentence is what tells a user their input did not take.
    const {user} = renderDialog();
    expect(screen.getByText('No valid new usernames yet.')).toBeInTheDocument();

    await user.click(field());
    await user.keyboard('bob{Enter}');

    expect(screen.queryByText('No valid new usernames yet.')).not.toBeInTheDocument();
    expect(screen.getByText('1 username to add.')).toBeInTheDocument();
  });

  it('renders committed names as removable chips', async () => {
    const {user} = renderDialog();
    await user.click(field());
    await user.keyboard('bob, cara{Enter}');

    expect(within(chips()!).getAllByRole('listitem')).toHaveLength(2);
    await user.click(screen.getByRole('button', {name: 'Remove bob'}));
    expect(within(chips()!).getAllByRole('listitem')).toHaveLength(1);
  });

  it('surfaces invalid tokens instead of swallowing them', async () => {
    const {user} = renderDialog();
    await user.click(field());
    await user.keyboard('bob 1bad no-dashes{Enter}');

    expect(within(chips()!).getAllByRole('listitem')).toHaveLength(1);
    expect(field()).toHaveValue('1bad no-dashes');
    expect(screen.getByRole('alert')).toHaveTextContent('Use 3–63 characters');
  });

  it('focuses the field on open', () => {
    // `Modal` passes `initialFocus: false` and defers to each consumer's own focus effect, so a
    // field that does not ask for focus leaves it on the trigger OUTSIDE the modal — a screen
    // reader is never moved into the dialog. axe cannot see this; only this test can.
    renderDialog();
    expect(document.activeElement).toBe(field());
  });

  it('handles a mix of valid, invalid, duplicate and excluded names in one entry (FR-003)', async () => {
    // The combination matters: an earlier version reported ONLY the rule sentence whenever
    // there was malformed input, so the excluded name vanished with no chip and no explanation
    // — the exact silent drop this spec exists to remove, one branch deeper.
    const {user} = renderDialog({existing: ['cara']});
    await user.click(field());
    await user.keyboard('bob bob dave cara 1bad{Enter}');

    expect(
      within(chips()!)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
    ).toEqual(['bob', 'dave']);
    expect(field()).toHaveValue('1bad');
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('Use 3–63 characters');
    expect(alert).toHaveTextContent('cara is already a member of this space.');
  });

  it('tells the user how to commit while text is uncommitted', async () => {
    // Add is gated on committed chips, so without this the button is disabled and nothing says
    // why. The hint deliberately names no token — it cannot promise what any given one will do.
    const {user} = renderDialog();
    expect(screen.queryByText(/Press Enter/)).not.toBeInTheDocument();

    await user.click(field());
    await user.keyboard('bo');

    expect(screen.getByText('Press Enter to add the name you typed.')).toBeInTheDocument();
    expect(addButton()).toBeDisabled();
  });

  it('no longer claims unknown usernames are ignored', async () => {
    // The copy said "Unknown usernames are ignored." — the same false claim SPEC-146 corrected
    // in two docstrings, and the only place a USER read it.
    renderDialog();
    expect(screen.queryByText(/ignored/i)).not.toBeInTheDocument();
    expect(screen.getByText(/reported back to you as a notification/i)).toBeInTheDocument();
  });

  it('locks the field and both buttons while busy', () => {
    renderDialog({busy: true});
    expect(field()).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Adding…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
  });

  it('cancels without sending', async () => {
    const {onAdd, onCancel, user} = renderDialog();
    await user.click(screen.getByRole('button', {name: 'Cancel'}));

    expect(onCancel).toHaveBeenCalled();
    expect(onAdd).not.toHaveBeenCalled();
  });
});

describe('AddMembersDialog — directory states', () => {
  it('commits a valid unlisted name and notes it neutrally when the directory is ready', async () => {
    const {onAdd, user} = renderDialog();
    await user.click(field());
    await user.keyboard('someone_new{Enter}');

    expect(await screen.findByText(/not in the directory/i)).toBeInTheDocument();
    expect(addButton()).toBeEnabled();

    await user.click(addButton());
    expect(onAdd).toHaveBeenCalledWith(['someone_new']);
  });

  it('stays fully usable when the directory is unavailable, with no note and no banner', async () => {
    vi.mocked(getUserDirectory).mockResolvedValue({success: false, error: {message: 'boom'}});
    const {onAdd, user} = renderDialog();
    await user.click(field());
    await user.keyboard('someone_new{Enter}');

    await user.click(addButton());

    expect(onAdd).toHaveBeenCalledWith(['someone_new']);
    expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('commits with no note while the directory is still loading', async () => {
    // A note that arrives a second after the name was accepted reads as a delayed rejection.
    let release: (value: unknown) => void = () => {};
    vi.mocked(getUserDirectory).mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }) as never
    );
    const {onAdd, user} = renderDialog();
    await user.click(field());
    await user.keyboard('someone_new{Enter}');

    expect(screen.queryByText(/not in the directory/i)).not.toBeInTheDocument();
    await user.click(addButton());
    expect(onAdd).toHaveBeenCalledWith(['someone_new']);
    release({success: true, data: {usernames: DIRECTORY, generatedAt: null}});
  });
});
