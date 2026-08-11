import {beforeEach, describe, expect, it, vi} from 'vitest';
import {screen, waitFor, within} from '@testing-library/react';
import {createTestQueryClient, renderWithProviders} from '../../test/renderWithProviders';
import {FEATURE_FLAG_DEFAULTS, featureFlagKeys} from '../feature-flags';
import {authenticated} from '../../test/authFixtures';
import {COMPONENT_AXE_OPTIONS, expectContainerHasNoA11yViolations} from '../../test/axe';
import {getUserDirectory} from '../user-directory';
import {readSharedConnectionsCache} from '../shared-spaces/sharedSpaces.service';
import {SendFilesDialog} from './SendFilesDialog';
import type {SendItem} from './fileSend.types';

vi.mock('../user-directory/userDirectory.service', () => ({
  getUserDirectory: vi.fn(),
  DIRECTORY_KEY: '_directory/usernames.json'
}));

vi.mock('../shared-spaces/sharedSpaces.service', () => ({
  readSharedConnectionsCache: vi.fn(),
  enqueueSharedSpaceRequest: vi.fn()
}));

const spacesCache = (names: string[]) => ({
  success: true as const,
  data: {
    version: 1 as const,
    connections: names.map((name) => ({name, role: 'member' as const, status: 'active' as const}))
  }
});

describe('SendFilesDialog', () => {
  const ITEMS: SendItem[] = [
    {kind: 'folder', key: 'alice/reports/'},
    {kind: 'file', key: 'alice/notes.txt'}
  ];

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getUserDirectory).mockResolvedValue({
      success: true,
      data: {usernames: ['bob', 'bob_smith', 'cara', 'alice'], generatedAt: '2026-08-11T04:00:00Z'}
    });
    vi.mocked(readSharedConnectionsCache).mockResolvedValue(spacesCache(['salesteam', 'finance']));
  });

  function renderDialog(
    over: Partial<React.ComponentProps<typeof SendFilesDialog>> = {},
    options: Parameters<typeof renderWithProviders>[1] = {}
  ) {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    const rendered = renderWithProviders(
      <SendFilesDialog
        items={ITEMS}
        onSubmit={onSubmit}
        onCancel={onCancel}
        {...over}
      />,
      {auth: authenticated('alice'), ...options}
    );
    /** Re-render the SAME dialog with `busy` flipped, keeping its committed state. */
    const rerender = (busy: boolean) =>
      rendered.rerender(
        <SendFilesDialog
          items={ITEMS}
          busy={busy}
          onSubmit={onSubmit}
          onCancel={onCancel}
          {...over}
        />
      );
    return {onSubmit, onCancel, user: rendered.user, container: rendered.container, rerender};
  }

  const entryInput = () => screen.getByRole('combobox') as HTMLInputElement;
  const addButton = () => screen.getByRole('button', {name: 'Add'});
  const sendButton = () => screen.getByRole('button', {name: /^Send$|Sending/});
  const chipList = () => screen.getByRole('list', {name: 'Recipients'});

  async function addRecipients(user: ReturnType<typeof renderDialog>['user'], raw: string) {
    await user.click(entryInput());
    await user.keyboard(raw);
    await user.click(addButton());
  }

  it('names what is being sent, by ITEM NAME rather than by key', () => {
    // The item name is what the recipient sees in their inbox, so it is what the sender should
    // be looking at while choosing recipients — `alice/reports/` is this user's own plumbing.
    renderDialog();
    const listed = within(screen.getByRole('list', {name: 'Items being sent'})).getAllByRole('listitem');

    expect(listed.map((li) => li.textContent)).toEqual(['reports/', 'notes.txt']);
  });

  it('adds comma/space-separated names as removable chips tagged with their kind', async () => {
    const {user} = renderDialog();
    await addRecipients(user, 'bob, cara');

    expect(within(chipList()).getAllByRole('listitem')).toHaveLength(2);
    expect(entryInput()).toHaveValue('');

    await user.click(within(chipList()).getByRole('button', {name: 'Remove user bob'}));
    expect(within(chipList()).queryByRole('button', {name: 'Remove user bob'})).not.toBeInTheDocument();
    expect(within(chipList()).getByRole('button', {name: 'Remove user cara'})).toBeInTheDocument();
  });

  it('mixes both kinds in one send', async () => {
    const {user, onSubmit} = renderDialog();
    await addRecipients(user, 'bob');
    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await addRecipients(user, 'finance');
    await user.click(sendButton());

    expect(onSubmit).toHaveBeenCalledWith([
      {kind: 'user', name: 'bob'},
      {kind: 'space', name: 'finance'}
    ]);
  });

  it('suggests usernames under one kind and the sender’s own spaces under the other', async () => {
    const {user} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bo');
    expect(await screen.findByRole('option', {name: 'bob'})).toBeInTheDocument();

    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await user.click(entryInput());
    await user.keyboard('fin');
    // The connections cache resolves through a query, so the second source settles a tick later
    // than the first — waited for rather than asserted, which is what the share dialog's own
    // suite does for the same field.
    await waitFor(() => expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['finance']));
  });

  it('never blocks a name it does not know, and says so in the softer wording for a space', async () => {
    // FR-002. An unlisted SPACE is not a wrong name: the suggestions are only the sender's own
    // spaces, and sending to a space you are not a member of is permitted.
    const {user, onSubmit} = renderDialog();
    await user.click(screen.getByRole('radio', {name: 'Shared spaces'}));
    await addRecipients(user, 'someoneelses');

    expect(await screen.findByText(/you can still send to a space you are not a member of/i)).toBeInTheDocument();
    await user.click(sendButton());
    expect(onSubmit).toHaveBeenCalledWith([{kind: 'space', name: 'someoneelses'}]);
  });

  it('commits a chip on Enter and does NOT submit the dialog', async () => {
    // SPEC-155's measured rule. A dialog that submits from a mid-edit field files the wrong
    // request — here it would send to whoever was already committed and drop what was typed.
    const {user, onSubmit} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bob{Enter}');

    expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('refuses a send with no recipients INLINE, and sends nothing', async () => {
    // FR-002 AC7. The control stays enabled precisely so this can be reached: a disabled button
    // explains nothing to the user who typed a name and forgot to commit it. An earlier version
    // disabled it, which made this banner unreachable — dead code where an AC should be, and a
    // test asserting only `toBeDisabled()` passed over it.
    const {user, onSubmit} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bob');
    await user.click(sendButton());

    expect(await screen.findByText('Add at least one recipient before sending.')).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('closes the suggestion list on the first Escape and the dialog on the second', async () => {
    // SPEC-155's depth registry, exercised rather than inherited: the innermost enabled handler
    // wins, and a child that stops the event never reaches the registry at all.
    const {user, onCancel} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bo');
    await screen.findByRole('option', {name: 'bob'});

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('option', {name: 'bob'})).not.toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it('a busy dialog swallows Escape rather than dismissing mid-request', async () => {
    const {user, onCancel} = renderDialog({busy: true});
    await user.keyboard('{Escape}');

    expect(onCancel).not.toHaveBeenCalled();
  });

  it('surfaces a submit error with the recipients intact, so a retry costs no retyping', async () => {
    const {user} = renderDialog({submitError: 'Sending files is not configured'});
    await addRecipients(user, 'bob');

    expect(screen.getByRole('alert')).toHaveTextContent('Sending files is not configured');
    expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeInTheDocument();
  });

  it('locks EVERY control while busy, not just the submit button', async () => {
    // Re-rendered with a committed chip rather than mounted busy-and-empty: a second empty
    // dialog's submit button is disabled by having no recipients, so asserting only that would
    // pass against an implementation where `busy` locked nothing at all.
    const {user, rerender} = renderDialog();
    await addRecipients(user, 'bob');

    rerender(true);

    expect(sendButton()).toBeDisabled();
    expect(entryInput()).toBeDisabled();
    expect(addButton()).toBeDisabled();
    expect(screen.getByRole('radio', {name: 'Shared spaces'})).toBeDisabled();
    expect(within(chipList()).getByRole('button', {name: 'Remove user bob'})).toBeDisabled();
  });

  it('renders no kind toggle at all when shared workspaces are off', async () => {
    // SPEC-163 FR-005: a single-option radio group asks a question with one answer, and implies
    // the other option exists somewhere.
    // Seeded directly rather than through the harness's all-on default: `setQueryDefaults`
    // FIRST is load-bearing, because the harness client runs `gcTime: 0` and would evict an
    // observer-less seed before the dialog mounts (SPEC-163's recorded trap).
    const client = createTestQueryClient();
    client.setQueryDefaults(featureFlagKeys.all, {gcTime: Infinity, staleTime: Infinity});
    client.setQueryData(featureFlagKeys.resolved(undefined), {
      ...FEATURE_FLAG_DEFAULTS,
      sharedWorkspaces: false
    });
    renderDialog({}, {queryClient: client, seedFeatureFlags: false});

    expect(screen.queryByRole('radio', {name: 'Shared spaces'})).not.toBeInTheDocument();
    expect(screen.getByRole('combobox')).toHaveAccessibleName(/Usernames/);
  });

  it('is axe-clean in its open, driven state', async () => {
    // Against the DRIVEN container, never a re-render: a fresh render would show the dialog
    // before anything was typed, which is not the state a user is in when they submit.
    const {user, container} = renderDialog();
    await addRecipients(user, 'bob, cara');

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });

  it('is axe-clean with the suggestion list OPEN, which is its own composition', async () => {
    // The combobox's own suite covers the listbox in isolation; what is only reachable here is
    // that listbox inside this dialog's focus trap, with this dialog's describedby wiring.
    const {user, container} = renderDialog();
    await user.click(entryInput());
    await user.keyboard('bo');
    await screen.findByRole('option', {name: 'bob'});

    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
