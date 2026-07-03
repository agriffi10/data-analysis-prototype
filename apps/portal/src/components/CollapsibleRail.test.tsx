import {render, screen, fireEvent, within} from '@testing-library/react';
import {beforeEach, describe, it, expect, vi} from 'vitest';
import {CollapsibleRail} from './CollapsibleRail';
import {RAIL_COLLAPSED_STORAGE_KEY} from './useRailCollapsed';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';
import {memoryStorage} from '../test/storage';

beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));

const rail = (
  <CollapsibleRail
    ariaLabel="Test rail"
    title="Section">
    <ul aria-label="Section list">
      <li>
        <button type="button">child action</button>
      </li>
    </ul>
  </CollapsibleRail>
);

function renderRail() {
  return render(
    <CollapsibleRail
      ariaLabel="Test rail"
      title="Section">
      <button type="button">child action</button>
    </CollapsibleRail>
  );
}

describe('CollapsibleRail', () => {
  it('renders the panel with its content + a collapse control, no reopen handle when expanded', () => {
    renderRail();
    const rail = screen.getByRole('complementary', {name: 'Test rail'});
    expect(within(rail).getByRole('button', {name: 'child action'})).toBeInTheDocument();

    const collapse = screen.getByRole('button', {name: /collapse sidebar/i});
    expect(collapse).toHaveAttribute('aria-expanded', 'true');
    expect(collapse).toHaveAttribute('aria-controls', rail.id);
    expect(screen.queryByRole('button', {name: /show sidebar/i})).not.toBeInTheDocument();
  });

  it('collapsing reveals a reopen handle wired to the rail; reopening hides it again', () => {
    renderRail();
    fireEvent.click(screen.getByRole('button', {name: /collapse sidebar/i}));

    const handle = screen.getByRole('button', {name: /show sidebar/i});
    expect(handle).toHaveAttribute('aria-expanded', 'false');
    expect(handle).toHaveAttribute('aria-controls', screen.getByRole('complementary', {name: 'Test rail'}).id);
    // The panel content is retained (not unmounted) so in-rail state survives.
    expect(
      within(screen.getByRole('complementary', {name: 'Test rail'})).getByRole('button', {name: 'child action'})
    ).toBeInTheDocument();

    fireEvent.click(handle);
    expect(screen.queryByRole('button', {name: /show sidebar/i})).not.toBeInTheDocument();
    expect(screen.getByRole('button', {name: /collapse sidebar/i})).toBeInTheDocument();
  });

  it('persists the collapsed choice under the single shared key', () => {
    renderRail();
    fireEvent.click(screen.getByRole('button', {name: /collapse sidebar/i}));
    expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
  });

  it('starts collapsed when the shared key already says collapsed (carries across rails)', () => {
    localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
    renderRail();
    expect(screen.getByRole('button', {name: /show sidebar/i})).toBeInTheDocument();
  });

  // SPEC-085 FR-004 / SPEC-045: no new axe violations in either rail state.
  it('has no axe violations when expanded', async () => {
    await expectNoA11yViolations(rail, COMPONENT_AXE_OPTIONS);
  });

  it('has no axe violations when collapsed', async () => {
    localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
    await expectNoA11yViolations(rail, COMPONENT_AXE_OPTIONS);
  });
});
