import {describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../../test/axe';
import {OperationOutcomeBanner} from './OperationSummaryBanner';
import type {FileOpItemResult} from './fileOps.types';

/**
 * The banner over a plane run's PER-ITEM outcomes.
 *
 * Driven with a mixed list rather than through the conflict view, which is its only production
 * caller today and sends nothing but `conflict`. Without this the grouping, the counts and the
 * success variant would all be unexercised — the shape of test that passes because the code it
 * covers is never reached.
 */
const MIXED: FileOpItemResult[] = [
  {itemKey: 'alice/a.csv', label: 'a.csv', outcome: 'moved'},
  {itemKey: 'alice/b.csv', label: 'b.csv', outcome: 'moved'},
  {itemKey: 'alice/c.csv', label: 'c.csv', outcome: 'noop'},
  {itemKey: 'alice/athenaresults/', label: 'athenaresults', outcome: 'protected'},
  {itemKey: 'alice/d.csv', label: 'd.csv', outcome: 'conflict', sample: ['d.csv'], more: true}
];

describe('OperationOutcomeBanner', () => {
  it('groups by outcome and counts each group', () => {
    renderWithProviders(
      <OperationOutcomeBanner
        title="5 items"
        results={MIXED}
      />
    );
    // Four groups from five items — the two `moved` share one.
    expect(screen.getByText('Moved (2)')).toBeInTheDocument();
    expect(screen.getByText('Nothing to do (1)')).toBeInTheDocument();
    expect(screen.getByText('Protected — Data Quarry manages these (1)')).toBeInTheDocument();
    expect(screen.getByText('Something is in the way (1)')).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(5);
  });

  it('is NEUTRAL for a mixed run and a success only when every item landed', () => {
    // The whole reason `{count, errors}` could not be reused: a `noop` is neither a success nor an
    // error, so a binary chosen on `errors.length === 0` calls this run clean or calls it a
    // failure, and both are wrong.
    const {unmount} = renderWithProviders(
      <OperationOutcomeBanner
        title="5 items"
        results={MIXED}
      />
    );
    const mixed = screen.getByRole('status');
    expect(mixed.className).not.toMatch(/success/);
    unmount();

    renderWithProviders(
      <OperationOutcomeBanner
        title="2 items"
        results={MIXED.filter((r) => r.outcome === 'moved')}
      />
    );
    expect(screen.getByRole('status').className).toMatch(/success/);
  });

  it('never lets a SHORTENED sample read as the whole of it', () => {
    // The producer bounds the sample by bytes as well as count, so "and more" is the only thing
    // standing between a truncated list and a user who believes they have seen all of it.
    renderWithProviders(
      <OperationOutcomeBanner
        title="1 item"
        results={[MIXED[4]]}
      />
    );
    expect(within(screen.getByRole('status')).getByText(/and more/)).toBeInTheDocument();
  });

  it('says nothing about a title it was not given, and dismisses when it can', async () => {
    const onDismiss = vi.fn();
    const {user} = renderWithProviders(
      <OperationOutcomeBanner
        title="5 items need your attention"
        results={MIXED}
        onDismiss={onDismiss}
      />
    );
    // Never a completion claim: the title is the caller's, and no verb is invented here.
    expect(screen.getByText('5 items need your attention')).toBeInTheDocument();
    await user.click(screen.getByRole('button', {name: /dismiss/i}));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('passes axe', async () => {
    await expectNoA11yViolations(
      <OperationOutcomeBanner
        title="5 items"
        results={MIXED}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
