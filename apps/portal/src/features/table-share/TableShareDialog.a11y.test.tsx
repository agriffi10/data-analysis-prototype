import {describe, it} from 'vitest';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {TableShareDialog} from './TableShareDialog';

const noop = () => {};

describe('TableShareDialog a11y', () => {
  it('has no axe violations in the default state', async () => {
    await expectNoA11yViolations(
      <TableShareDialog
        source={{database: 'alice', table: 'orders'}}
        onSubmit={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });

  it('has no axe violations with a submit error while busy', async () => {
    await expectNoA11yViolations(
      <TableShareDialog
        source={{database: 'alice', table: 'orders'}}
        busy
        submitError="Failed to submit the request"
        onSubmit={noop}
        onCancel={noop}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
