import {describe, it, vi} from 'vitest';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';
import {Modal} from './Modal';
import {ConfirmDialog} from './ConfirmDialog';
import {Drawer} from './Drawer';
import {Input} from './Input';
import {Banner, type BannerVariant} from './Banner';
import {Pager} from './Pager';
import {Toast, type ToastState} from '../features/query/Toast';

const noop = () => {};

// Component-level axe checks: primitives rendered in the states the route tests
// don't reach. Rendered outside a landmark, so `region` is disabled via
// COMPONENT_AXE_OPTIONS (intentional — landmarks are a route-level concern).

describe('Modal / ConfirmDialog / Drawer accessibility (open)', () => {
  it('Modal has an accessible name and no violations', async () => {
    await expectNoA11yViolations(
      <Modal
        ariaLabel="Example dialog"
        onDismiss={noop}>
        <div className="p-4">
          <p>Body</p>
          <button type="button">OK</button>
        </div>
      </Modal>,
      COMPONENT_AXE_OPTIONS
    );
  });

  it('ConfirmDialog (danger, irreversible) has no violations', async () => {
    await expectNoA11yViolations(
      <ConfirmDialog
        title="Delete item"
        ariaLabel="Confirm delete item"
        confirmLabel="Delete"
        confirmVariant="danger"
        tone="danger"
        irreversible
        onConfirm={noop}
        onCancel={noop}>
        <p className="mt-2 text-sm">This removes the item permanently.</p>
      </ConfirmDialog>,
      COMPONENT_AXE_OPTIONS
    );
  });

  it('Drawer (open, with header accessory + footer) has no violations', async () => {
    await expectNoA11yViolations(
      <Drawer
        open
        onClose={noop}
        title="History"
        headerAccessory={<span className="text-xs">3 items</span>}
        footer={<div className="p-3">footer</div>}>
        <p>Drawer body content.</p>
      </Drawer>,
      COMPONENT_AXE_OPTIONS
    );
  });
});

describe('Input accessibility', () => {
  it('error state wires invalid + described-by with no violations', async () => {
    await expectNoA11yViolations(
      <Input
        label="Folder name"
        error="Enter a valid name."
        defaultValue="x/"
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});

describe('Banner accessibility (every variant)', () => {
  const variants: BannerVariant[] = ['success', 'warning', 'danger', 'info'];
  it.each(variants)('%s variant has no violations', async (variant) => {
    await expectNoA11yViolations(
      <Banner
        variant={variant}
        title="Heads up"
        onDismiss={noop}>
        <p>Something happened.</p>
      </Banner>,
      COMPONENT_AXE_OPTIONS
    );
  });
});

describe('Toast accessibility (every variant)', () => {
  const variants: ToastState['variant'][] = ['success', 'danger', 'info'];
  it.each(variants)('%s variant has no violations', async (variant) => {
    await expectNoA11yViolations(
      <Toast
        variant={variant}
        message="Saved your changes."
        onDismiss={vi.fn()}
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});

describe('Pager accessibility', () => {
  it('has no violations (both directions enabled)', async () => {
    await expectNoA11yViolations(
      <Pager
        hasPrev
        hasNext
        onPrev={noop}
        onNext={noop}
        label="1–20 of 57"
      />,
      COMPONENT_AXE_OPTIONS
    );
  });
});
