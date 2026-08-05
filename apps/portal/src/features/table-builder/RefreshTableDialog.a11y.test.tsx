import {describe, it} from 'vitest';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {RefreshTableDialog} from './RefreshTableDialog';
import type {TableRefreshTarget} from './tableRefresh.types';

const noop = () => {};

const TARGET: TableRefreshTarget = {
  database: 'alice',
  table: {name: 'sales_2026', columns: [], location: 's3://dat-prod-user-space/alice/sales/2026/'},
  pending: null
};

describe('RefreshTableDialog a11y', () => {
  it('has no axe violations in the plain state', async () => {
    await expectNoA11yViolations(
      <RefreshTableDialog
        target={TARGET}
        onConfirm={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });

  it('has no axe violations in the link-borne state', async () => {
    await expectNoA11yViolations(
      <RefreshTableDialog
        target={{...TARGET, pending: {database: 'alice', tableName: 'sales_2026', columns: ['legacy_id', 'Order ID']}}}
        onConfirm={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });

  it('has no axe violations with a submit error while busy', async () => {
    await expectNoA11yViolations(
      <RefreshTableDialog
        target={TARGET}
        busy
        submitError="Failed to submit the request"
        onConfirm={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
