import {beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, within} from '@testing-library/react';
import {CreateSharedConnectionDialog} from './CreateSharedConnectionDialog';
import {DeleteSharedSpaceDialog} from './DeleteSharedSpaceDialog';
import {LeaveSharedSpaceDialog} from './LeaveSharedSpaceDialog';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {MemberRosterDrawer} from './MemberRosterDrawer';
import {MembersList} from './MembersList';
import {parseMemberInput, parseMemberInputDetailed} from './memberInput';
import type {Member} from './sharedSpaces.types';

// ─── from CreateSharedConnectionDialog.test.tsx ───
describe('CreateSharedConnectionDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('CreateSharedConnectionDialog (SPEC-051 FR-001)', () => {
    it('disables Create until the name passes the catalog-safe rule', () => {
      render(
        <CreateSharedConnectionDialog
          onCreate={vi.fn()}
          onCancel={vi.fn()}
        />
      );
      const create = screen.getByRole('button', {name: 'Create'});
      expect(create).toBeDisabled();

      fireEvent.change(screen.getByLabelText('Connection name'), {
        target: {value: '9bad'} // leading digit
      });
      expect(create).toBeDisabled();
      expect(screen.getByText(/3–63 characters/)).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText('Connection name'), {
        target: {value: 'sales_data'}
      });
      expect(create).toBeEnabled();
    });

    it('confirms with the trimmed valid name', () => {
      const onCreate = vi.fn();
      render(
        <CreateSharedConnectionDialog
          onCreate={onCreate}
          onCancel={vi.fn()}
        />
      );
      fireEvent.change(screen.getByLabelText('Connection name'), {
        target: {value: '  marketing_q2  '}
      });
      fireEvent.click(screen.getByRole('button', {name: 'Create'}));
      expect(onCreate).toHaveBeenCalledWith('marketing_q2');
    });

    it('cancels with no create', () => {
      const onCancel = vi.fn();
      const onCreate = vi.fn();
      render(
        <CreateSharedConnectionDialog
          onCreate={onCreate}
          onCancel={onCancel}
        />
      );
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalled();
      expect(onCreate).not.toHaveBeenCalled();
    });
  });
});

// ─── from DeleteSharedSpaceDialog.test.tsx ───
describe('DeleteSharedSpaceDialog', () => {
  describe('DeleteSharedSpaceDialog (SPEC-054)', () => {
    it('keeps Delete disabled until the exact name is typed', () => {
      const onConfirm = vi.fn();
      render(
        <DeleteSharedSpaceDialog
          space="sales"
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );
      const confirm = screen.getByRole('button', {name: 'Delete'});
      expect(confirm).toBeDisabled();

      fireEvent.change(screen.getByLabelText(/to confirm/), {target: {value: 'sale'}});
      expect(confirm).toBeDisabled();

      fireEvent.change(screen.getByLabelText(/to confirm/), {target: {value: 'sales'}});
      expect(confirm).toBeEnabled();
      fireEvent.click(confirm);
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });

    it('Enter confirms only once the name matches', () => {
      const onConfirm = vi.fn();
      render(
        <DeleteSharedSpaceDialog
          space="sales"
          onConfirm={onConfirm}
          onCancel={vi.fn()}
        />
      );
      const field = screen.getByLabelText(/to confirm/);

      fireEvent.keyDown(field, {key: 'Enter'});
      expect(onConfirm).not.toHaveBeenCalled();

      fireEvent.change(field, {target: {value: 'sales'}});
      fireEvent.keyDown(field, {key: 'Enter'});
      expect(onConfirm).toHaveBeenCalledTimes(1);
    });
  });
});

// ─── from LeaveSharedSpaceDialog.test.tsx ───
describe('LeaveSharedSpaceDialog', () => {
  describe('LeaveSharedSpaceDialog (SPEC-054)', () => {
    it('confirms and cancels via the shared danger dialog', () => {
      const onConfirm = vi.fn();
      const onCancel = vi.fn();
      render(
        <LeaveSharedSpaceDialog
          space="sales"
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      );
      expect(screen.getByRole('alertdialog', {name: 'Leave sales'})).toBeInTheDocument();

      fireEvent.click(screen.getByRole('button', {name: 'Leave'}));
      expect(onConfirm).toHaveBeenCalledTimes(1);
      fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
      expect(onCancel).toHaveBeenCalledTimes(1);
    });
  });
});

// ─── from MemberRosterDrawer.test.tsx ───
describe('MemberRosterDrawer', () => {
  function setup(overrides: Partial<Parameters<typeof MemberRosterDrawer>[0]> = {}) {
    const props = {
      open: true,
      onClose: vi.fn(),
      space: 'salesdata',
      owner: 'alice',
      members: [
        {username: 'alice', status: 'active' as const},
        {username: 'bob', status: 'pending' as const}
      ],
      onRefresh: vi.fn(),
      ...overrides
    };
    render(<MemberRosterDrawer {...props} />);
    return props;
  }

  describe('MemberRosterDrawer (SPEC-075 FR-003)', () => {
    it('lists members with the owner tagged and shows join status', () => {
      setup();
      const ownerRow = screen.getByText('alice').closest('li')!;
      expect(within(ownerRow).getByText('Owner')).toBeInTheDocument();
      expect(within(screen.getByText('bob').closest('li')!).getByText('Pending')).toBeInTheDocument();
    });

    it('is read-only — no Add and no per-member Remove', () => {
      setup();
      expect(screen.queryByRole('button', {name: /Add members/})).not.toBeInTheDocument();
      expect(screen.queryByRole('button', {name: /Remove/})).not.toBeInTheDocument();
    });

    it('offers a Refresh control that re-reads connection state', () => {
      const {onRefresh} = setup();
      fireEvent.click(screen.getByRole('button', {name: 'Refresh connections'}));
      expect(onRefresh).toHaveBeenCalled();
    });

    // ── SPEC-186 FR-008 ────────────────────────────────────────────────────
    // The app asserted both things at once: this drawer said `bob | Pending` under a sentence
    // saying a Pending member "hasn't signed in yet", while the connections row one click away
    // said Active — read by bob, who plainly had. The acknowledge verb now fans the roster out
    // (`cache.write_roster_to_all`); this closes the window before that lands.
    it('never tells the reader they have not signed in', () => {
      setup({viewer: 'bob'});
      expect(within(screen.getByText('bob').closest('li')!).getByText('Active')).toBeInTheDocument();
      expect(screen.queryByText(/hasn.t signed in yet/i)).not.toBeInTheDocument();
    });

    it('has no axe violations', async () => {
      await expectNoA11yViolations(
        <MemberRosterDrawer
          open
          onClose={vi.fn()}
          space="salesdata"
          owner="alice"
          members={[
            {username: 'alice', status: 'active'},
            {username: 'bob', status: 'pending'}
          ]}
          onRefresh={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from MembersList.test.tsx ───
describe('MembersList', () => {
  const roster: Member[] = [
    {username: 'cara', status: 'pending'},
    {username: 'alice', status: 'active'},
    {username: 'bob', status: 'active'}
  ];

  describe('MembersList (SPEC-075)', () => {
    it('lists the owner first (tagged), then the rest alphabetical', () => {
      render(
        <MembersList
          owner="alice"
          members={roster}
        />
      );
      const items = screen.getAllByRole('listitem');
      expect(items.map((li) => within(li).getAllByText(/alice|bob|cara/)[0].textContent)).toEqual([
        'alice',
        'bob',
        'cara'
      ]);
      const ownerRow = screen.getByText('alice').closest('li')!;
      expect(within(ownerRow).getByText('Owner')).toBeInTheDocument();
    });

    it('renders a per-member status chip and never a chip on the owner', () => {
      render(
        <MembersList
          owner="alice"
          members={roster}
        />
      );
      expect(within(screen.getByText('cara').closest('li')!).getByText('Pending')).toBeInTheDocument();
      expect(within(screen.getByText('bob').closest('li')!).getByText('Active')).toBeInTheDocument();
      // The owner row shows "Owner", not a join-status chip.
      const ownerRow = screen.getByText('alice').closest('li')!;
      expect(within(ownerRow).queryByText('Active')).not.toBeInTheDocument();
    });

    it('is read-only by default — no Remove buttons', () => {
      render(
        <MembersList
          owner="alice"
          members={roster}
        />
      );
      expect(screen.queryByRole('button', {name: /Remove/})).not.toBeInTheDocument();
    });

    it('renders Remove per non-owner member when onRemove is given, and calls it', () => {
      const onRemove = vi.fn();
      render(
        <MembersList
          owner="alice"
          members={roster}
          onRemove={onRemove}
        />
      );
      // Owner has no Remove. Queried by the member-naming label since SPEC-154 FR-006, which
      // also retires the `.closest('li')` reach this needed to disambiguate identical buttons.
      expect(screen.queryByRole('button', {name: 'Remove alice'})).toBeNull();
      fireEvent.click(screen.getByRole('button', {name: 'Remove bob'}));
      expect(onRemove).toHaveBeenCalledWith('bob');
    });
  });
});

// ─── from memberInput.test.ts ───
describe('memberInput', () => {
  /**
   * `parseMemberInput` had no direct unit test before SPEC-147 — it was exercised only through
   * `AddMembersDialog.test.tsx`. Its cases are pinned here BEFORE the detailed variant lands
   * beside it, because FR-006's criterion is that the original's behaviour is unchanged, and a
   * behaviour with no test is one a refactor can change without anything noticing.
   */
  describe('parseMemberInput — unchanged by SPEC-147', () => {
    it('splits on commas, spaces and newlines', () => {
      expect(parseMemberInput('bob, cara\ndan  erin')).toEqual(['bob', 'cara', 'dan', 'erin']);
    });

    it('DROPS anything failing the catalog-safe rule, silently', () => {
      // The silent drop is the shipped behaviour that consumers and their tests rely on. The
      // detailed variant below exists precisely because it is the wrong behaviour in a field
      // that can afford to say something.
      expect(parseMemberInput('bob alice@corp.com 9lives x')).toEqual(['bob']);
    });

    it('returns an empty list for empty input', () => {
      expect(parseMemberInput('')).toEqual([]);
      expect(parseMemberInput('   ,  ')).toEqual([]);
    });
  });

  describe('parseMemberInputDetailed', () => {
    it('reports what it rejected instead of dropping it', () => {
      expect(parseMemberInputDetailed('bob alice@corp.com 9lives')).toEqual({
        valid: ['bob'],
        invalid: ['alice@corp.com', '9lives']
      });
    });

    it('reports invalid tokens AS TYPED, not lowercased', () => {
      // The user has to recognise what they pasted in order to fix it, and `bob smith` is a
      // different string from the `Bob Smith` on their clipboard.
      expect(parseMemberInputDetailed('Bob Smith!').invalid).toEqual(['Smith!']);
    });

    it('returns two empty lists for empty input', () => {
      expect(parseMemberInputDetailed('  , \n ')).toEqual({valid: [], invalid: []});
    });
  });
});

describe('DeleteSharedSpaceDialog — what it may no longer claim (SPEC-205)', () => {
  it('makes no destruction claim and does not say the action cannot be undone', () => {
    // Render-based rather than a word sweep over the source: the sentences that mattered were
    // "This can’t be undone." with a curly apostrophe and a body naming files and tables, and a
    // list of search terms written from memory matched neither.
    render(
      <DeleteSharedSpaceDialog
        space="sales"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />
    );

    const dialog = screen.getByRole('alertdialog');
    expect(dialog).not.toHaveTextContent(/can.t be undone/i);
    expect(dialog).not.toHaveTextContent(/permanently deletes/i);
    // Deliberately not a ban on the word "destroy": the copy uses it truthfully, in
    // "kept … rather than destroyed". Forbidding a word rather than a claim is the sweep this
    // assertion exists to replace.
    // What it says instead: access ends, the contents are kept, the name is spent.
    expect(dialog).toHaveTextContent(/every member loses access/i);
    expect(dialog).toHaveTextContent(/kept by administrators/i);
    expect(dialog).toHaveTextContent(/name can never be used again/i);
  });
});
