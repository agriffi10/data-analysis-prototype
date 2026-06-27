import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { expectNoA11yViolations, COMPONENT_AXE_OPTIONS } from '../../test/axe';
import { QueryTabStrip } from './QueryTabStrip';
import type { QueryTab } from './query.types';

const tabs: QueryTab[] = [
  { id: 't1', label: 'Query 1', sql: 'SELECT 1;' },
  { id: 't2', label: 'Revenue', sql: 'SELECT 2;', savedQueryId: 'sq1' },
  { id: 't3', label: 'Query 3', sql: '' },
];

const noop = () => {};

function strip(activeTabId = 't1') {
  return (
    <div>
      <QueryTabStrip
        tabs={tabs}
        activeTabId={activeTabId}
        dirtyTabIds={new Set(['t2'])}
        onSelect={noop}
        onClose={noop}
        onNew={noop}
        onOpenSaved={noop}
        onOpenHistory={noop}
      />
      {/* The panel the tablist's `aria-controls` points at (lives in
          QueryWorkspace at runtime). */}
      <div role="tabpanel" id="query-tabpanel" aria-labelledby="query-tab-t1" />
    </div>
  );
}

describe('QueryTabStrip accessibility (SPEC-045 FR-004)', () => {
  it('multi-tab strip has no violations', async () => {
    // The closable tab's ✕ is now a decorative, non-focusable pointer affordance
    // (not a nested <button>), so axe's `nested-interactive` rule runs clean here
    // — keyboard close stays available via the Delete key on the focused tab.
    await expectNoA11yViolations(strip(), COMPONENT_AXE_OPTIONS);
  });

  it('exposes a tablist whose only children are tabs, linked to one tabpanel', () => {
    render(strip());
    const tablist = screen.getByRole('tablist', { name: 'Query tabs' });
    expect(tablist).toBeInTheDocument();

    const tabEls = screen.getAllByRole('tab');
    expect(tabEls).toHaveLength(3);
    // Every tab is a direct child of the tablist (aria-required-children) and links
    // to the single shared tabpanel.
    for (const tab of tabEls) {
      expect(tab.parentElement).toBe(tablist);
      expect(tab).toHaveAttribute('aria-controls', 'query-tabpanel');
    }
    expect(screen.getByRole('tabpanel')).toHaveAttribute('id', 'query-tabpanel');
  });
});
