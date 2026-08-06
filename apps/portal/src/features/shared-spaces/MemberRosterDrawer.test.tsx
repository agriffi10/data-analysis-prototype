import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, within} from '@testing-library/react';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {MemberRosterDrawer} from './MemberRosterDrawer';

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
    expect(screen.queryByRole('button', {name: /^Remove /})).not.toBeInTheDocument();
  });

  it('offers a Refresh control that re-reads connection state', () => {
    const {onRefresh} = setup();
    fireEvent.click(screen.getByRole('button', {name: 'Refresh connections'}));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('shows a non-blocking note (and no list) for a legacy entry without a roster', () => {
    setup({members: [], unavailable: true});
    expect(screen.getByText(/member list isn.t available yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
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
