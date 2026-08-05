import {describe, expect, it, vi} from 'vitest';
import {screen, within} from '@testing-library/react';
import {renderWithProviders} from '../../test/renderWithProviders';
import {RefreshTableDialog} from './RefreshTableDialog';
import type {TableRefreshTarget} from './tableRefresh.types';

const TARGET: TableRefreshTarget = {
  database: 'alice',
  table: {
    name: 'sales_2026',
    columns: [{name: 'region', type: 'string'}],
    location: 's3://dat-prod-user-space/alice/sales/2026/'
  },
  pending: null
};

const LINKED: TableRefreshTarget = {
  ...TARGET,
  pending: {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id', 'Order ID']}
};

function render(target = TARGET, props: Partial<React.ComponentProps<typeof RefreshTableDialog>> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const rendered = renderWithProviders(
    <RefreshTableDialog
      target={target}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...props}
    />
  );
  return {...rendered, onConfirm, onCancel};
}

const confirmButton = () => screen.getByRole('button', {name: 'Refresh table'});
const optIn = () => screen.getByRole('checkbox', {name: /allow columns to be removed/i});

describe('RefreshTableDialog', () => {
  it('names the table and the folder it will re-read', () => {
    render();
    expect(screen.getByRole('alertdialog', {name: /alice\.sales_2026/})).toBeInTheDocument();
    expect(screen.getByText('alice.sales_2026')).toBeInTheDocument();
    expect(screen.getByText('s3://dat-prod-user-space/alice/sales/2026/')).toBeInTheDocument();
  });

  it('states what a refresh does and does not do', () => {
    render();
    expect(screen.getByText(/files are not modified/i)).toBeInTheDocument();
    expect(screen.getByText(/partition keys are not changed/i)).toBeInTheDocument();
    // SPEC-149 made the rebuild in-place, so there is no unavailability window to warn about.
    expect(screen.getByText(/stays queryable/i)).toBeInTheDocument();
    expect(screen.getByText(/arrives as a notification/i)).toBeInTheDocument();
  });

  it('offers the opt-in unchecked with confirm enabled — an additive refresh needs no tick', async () => {
    const {onConfirm, user} = render();
    expect(optIn()).not.toBeChecked();
    expect(confirmButton()).toBeEnabled();
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith(false);
  });

  it('passes the ticked opt-in to confirm', async () => {
    const {onConfirm, user} = render();
    await user.click(optIn());
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it('names the consequence of removal beside the box', () => {
    render();
    expect(screen.getByText(/dropped from the table/i)).toBeInTheDocument();
    expect(screen.getByText(/will stop working/i)).toBeInTheDocument();
  });

  it('shows no removed-columns block when opened normally', () => {
    render();
    expect(screen.queryByRole('list', {name: /columns that would be removed/i})).not.toBeInTheDocument();
    expect(screen.queryByText(/previous refresh was stopped/i)).not.toBeInTheDocument();
  });

  it('names the link-borne columns and explains why the refresh was stopped', () => {
    render(LINKED);
    expect(screen.getByText(/previous refresh was stopped/i)).toBeInTheDocument();
    expect(screen.getByText(/no longer in the files/i)).toBeInTheDocument();
    const list = screen.getByRole('list', {name: /columns that would be removed/i});
    expect(within(list).getByText('legacy_id')).toBeInTheDocument();
    // Not a catalog-safe identifier — column names never have to be.
    expect(within(list).getByText('Order ID')).toBeInTheDocument();
  });

  it('gates confirm on the opt-in in the link-borne state', async () => {
    const {onConfirm, user} = render(LINKED);
    expect(optIn()).not.toBeChecked();
    expect(confirmButton()).toBeDisabled();

    await user.click(optIn());
    expect(confirmButton()).toBeEnabled();
    await user.click(confirmButton());
    expect(onConfirm).toHaveBeenCalledWith(true);
  });

  it('never pre-checks the box, even reopened for the same pending removal', () => {
    const {unmount} = render(LINKED);
    expect(optIn()).not.toBeChecked();
    unmount();
    render(LINKED);
    expect(optIn()).not.toBeChecked();
  });

  it('locks the dialog and shows progress while the enqueue is in flight', () => {
    render(TARGET, {busy: true});
    expect(screen.getByRole('button', {name: 'Starting…'})).toBeDisabled();
    expect(screen.getByRole('button', {name: 'Cancel'})).toBeDisabled();
    expect(optIn()).toBeDisabled();
  });

  it('surfaces a submit error inline without closing', () => {
    render(TARGET, {submitError: 'Sign in to continue.'});
    expect(screen.getByRole('alert')).toHaveTextContent('Sign in to continue.');
    expect(confirmButton()).toBeEnabled();
  });

  it('cancels on Escape when not busy', async () => {
    const {onCancel, user} = render();
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalled();
  });

  it('does not dismiss on Escape while busy', async () => {
    const {onCancel, user} = render(TARGET, {busy: true});
    await user.keyboard('{Escape}');
    expect(onCancel).not.toHaveBeenCalled();
  });

  // SPEC-095/145 FR-007: one tree, `tablet:` only — no `*Mobile` twin, and nothing
  // in the dialog reads `useIsMobile`. What a 400px viewport needs is structural.
  describe('at a narrow viewport', () => {
    // The viewport cap itself belongs to `Modal` and is asserted in Modal.test.tsx —
    // asserting it here would pass no matter what this component does.
    it('scrolls the column list rather than pushing confirm off-screen', () => {
      render({...LINKED, pending: {...LINKED.pending!, columns: Array.from({length: 20}, (_, i) => `col_${i}`)}});
      expect(screen.getByRole('list', {name: /columns that would be removed/i})).toHaveClass(
        'max-h-32',
        'overflow-y-auto'
      );
      expect(confirmButton()).toBeInTheDocument();
    });

    it('gives the opt-in a full-width touch target', () => {
      render();
      const label = optIn().closest('label');
      expect(label).toHaveClass('w-full');
      expect(label).toContainElement(optIn());
    });

    it('reflows the table/folder rows on one tree', () => {
      render();
      expect(screen.getByText('alice.sales_2026').parentElement).toHaveClass('flex-col', 'tablet:flex-row');
    });
  });

  it('persists nothing — no localStorage access on any path', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    const getItem = vi.spyOn(Storage.prototype, 'getItem');
    const {user} = render(LINKED);
    await user.click(optIn());
    await user.click(confirmButton());
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalled();
    setItem.mockRestore();
    getItem.mockRestore();
  });
});
