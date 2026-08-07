import {beforeEach, describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen, waitFor} from '@testing-library/react';
import {Banner} from './Banner';
import type {BannerVariant} from './Banner';
import {createRef} from 'react';
import {Button} from './Button';
import {CopyButton} from './CopyButton';
import {ErrorBanner} from './ErrorBanner';
import {Input} from './Input';
import {Pager} from './Pager';
import {RefreshIconButton} from './RefreshIconButton';
import {SegmentedFilter} from './SegmentedFilter';
import {COMPONENT_AXE_OPTIONS, expectNoA11yViolations} from '../test/axe';
import {MobileActionBar} from './MobileActionBar';
import {Modal} from './Modal';
import {ConfirmDialog} from './ConfirmDialog';
import {Drawer} from './Drawer';
import {Toast} from './Toast';
import type {ToastState} from './Toast';
import userEvent from '@testing-library/user-event';

// ─── from Banner.test.tsx ───
describe('Banner', () => {
  describe('Banner', () => {
    it('renders each variant with its body', () => {
      const variants = ['success', 'warning', 'danger', 'info'] as const;
      variants.forEach((v) => {
        const {unmount} = render(<Banner variant={v}>Body {v}</Banner>);
        expect(screen.getByText(`Body ${v}`)).toBeInTheDocument();
        unmount();
      });
    });

    it('renders the title when provided', () => {
      render(
        <Banner
          variant="success"
          title="Done">
          details
        </Banner>
      );
      expect(screen.getByText('Done')).toBeInTheDocument();
    });

    it('shows a Dismiss button only when onDismiss is provided and calls it', () => {
      const onDismiss = vi.fn();
      const {rerender} = render(<Banner variant="danger">x</Banner>);
      expect(screen.queryByRole('button', {name: /dismiss/i})).not.toBeInTheDocument();

      rerender(
        <Banner
          variant="danger"
          onDismiss={onDismiss}>
          x
        </Banner>
      );
      fireEvent.click(screen.getByRole('button', {name: /dismiss/i}));
      expect(onDismiss).toHaveBeenCalledOnce();
    });

    it('defaults role to alert and honours status', () => {
      const {rerender} = render(<Banner variant="info">a</Banner>);
      expect(screen.getByRole('alert')).toBeInTheDocument();
      rerender(
        <Banner
          variant="success"
          role="status">
          a
        </Banner>
      );
      expect(screen.getByRole('status')).toBeInTheDocument();
    });
  });
});

// ─── from Button.test.tsx ───
describe('Button', () => {
  describe('Button', () => {
    it('renders each variant', () => {
      const variants = ['primary', 'default', 'ghost', 'danger'] as const;
      variants.forEach((v) => {
        const {unmount} = render(<Button variant={v}>{v}</Button>);
        expect(screen.getByRole('button', {name: v})).toBeInTheDocument();
        unmount();
      });
    });

    it('forwards disabled', () => {
      render(<Button disabled>Go</Button>);
      expect(screen.getByRole('button', {name: 'Go'})).toBeDisabled();
    });

    it('forwards onClick', () => {
      const onClick = vi.fn();
      render(<Button onClick={onClick}>Click</Button>);
      fireEvent.click(screen.getByRole('button', {name: 'Click'}));
      expect(onClick).toHaveBeenCalledOnce();
    });

    it('appends className additions', () => {
      render(<Button className="custom-x">Styled</Button>);
      expect(screen.getByRole('button', {name: 'Styled'})).toHaveClass('custom-x');
    });

    it('forwards a ref', () => {
      const ref = createRef<HTMLButtonElement>();
      render(<Button ref={ref}>Ref</Button>);
      expect(ref.current).toBeInstanceOf(HTMLButtonElement);
    });
  });
});

// ─── from CopyButton.test.tsx ───
describe('CopyButton', () => {
  const writeText = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    writeText.mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      value: {writeText},
      configurable: true
    });
  });

  describe('CopyButton', () => {
    it('has a stable accessible name woven from the label', () => {
      render(
        <CopyButton
          value="s3://b/k"
          label="full cloud path"
        />
      );
      expect(screen.getByRole('button', {name: /copy full cloud path/i})).toBeInTheDocument();
    });

    it('writes the value to the clipboard and announces success', async () => {
      render(
        <CopyButton
          value="s3://b/k"
          label="path"
        />
      );

      fireEvent.click(screen.getByRole('button', {name: /copy path/i}));

      expect(writeText).toHaveBeenCalledWith('s3://b/k');
      await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/copied/i));
    });

    it('does not throw or announce when the clipboard rejects', async () => {
      writeText.mockRejectedValueOnce(new Error('denied'));
      render(
        <CopyButton
          value="x"
          label="path"
        />
      );

      fireEvent.click(screen.getByRole('button', {name: /copy path/i}));

      await waitFor(() => expect(writeText).toHaveBeenCalled());
      expect(screen.getByRole('status').textContent).toBe('');
    });
  });
});

// ─── from ErrorBanner.test.tsx ───
describe('ErrorBanner', () => {
  describe('ErrorBanner', () => {
    it('renders the FR-001-mapped message for a known AWS code, not the raw text', () => {
      render(<ErrorBanner error={{code: 'AccessDenied', message: 'User: arn:aws:sts is not authorized'}} />);
      expect(screen.getByText(/don't have permission/)).toBeInTheDocument();
      expect(screen.queryByText(/arn:aws/)).not.toBeInTheDocument();
    });

    it('maps an unqualified-table Athena failure to the add-database fix', () => {
      render(<ErrorBanner error={{code: 'FAILED', message: 'line 1:15: Table sales does not exist'}} />);
      expect(screen.getByText(/Add a database to each table/)).toBeInTheDocument();
    });

    it('falls back to the generic message for an unknown error', () => {
      render(<ErrorBanner error={{code: 'Whatever', message: 'boom internal detail'}} />);
      expect(screen.getByText('Something went wrong. Contact the Administrator.')).toBeInTheDocument();
      expect(screen.queryByText(/boom internal/)).not.toBeInTheDocument();
    });

    it('is an alert live region and can be dismissed', async () => {
      const onDismiss = vi.fn();
      render(
        <ErrorBanner
          error={{code: 'NetworkError'}}
          onDismiss={onDismiss}
        />
      );
      expect(screen.getByRole('alert')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', {name: 'Dismiss'}));
      expect(onDismiss).toHaveBeenCalledOnce();
    });
  });
});

// ─── from Input.test.tsx ───
describe('Input', () => {
  describe('Input', () => {
    it('renders a label wired to the input', () => {
      render(
        <Input
          id="name"
          label="Your name"
        />
      );
      expect(screen.getByLabelText('Your name')).toBeInTheDocument();
    });

    it('shows the error message and marks the input invalid', () => {
      render(
        <Input
          id="name"
          label="Name"
          error="Required"
        />
      );
      expect(screen.getByRole('alert')).toHaveTextContent('Required');
      expect(screen.getByLabelText('Name')).toHaveAttribute('aria-invalid', 'true');
    });

    it('does not render an error or aria-invalid when error is absent', () => {
      render(
        <Input
          id="name"
          label="Name"
        />
      );
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getByLabelText('Name')).not.toHaveAttribute('aria-invalid');
    });
  });
});

// ─── from Pager.test.tsx ───
describe('Pager', () => {
  describe('Pager', () => {
    it('renders the label and wires Prev/Next', () => {
      const onPrev = vi.fn();
      const onNext = vi.fn();
      render(
        <Pager
          hasPrev
          hasNext
          onPrev={onPrev}
          onNext={onNext}
          label="1–7 of 23"
        />
      );
      expect(screen.getByText('1–7 of 23')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', {name: 'Prev'}));
      fireEvent.click(screen.getByRole('button', {name: 'Next'}));
      expect(onPrev).toHaveBeenCalled();
      expect(onNext).toHaveBeenCalled();
    });

    it('disables Prev/Next per the flags', () => {
      render(
        <Pager
          hasPrev={false}
          hasNext={false}
          onPrev={vi.fn()}
          onNext={vi.fn()}
          label="1–5 of 5"
        />
      );
      expect(screen.getByRole('button', {name: 'Prev'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Next'})).toBeDisabled();
    });

    it('shows a loading Next and disables it when nextBusy', () => {
      render(
        <Pager
          hasPrev
          hasNext
          nextBusy
          onPrev={vi.fn()}
          onNext={vi.fn()}
          label="x"
        />
      );
      expect(screen.getByRole('button', {name: 'Loading…'})).toBeDisabled();
    });
  });
});

// ─── from RefreshIconButton.test.tsx ───
describe('RefreshIconButton', () => {
  describe('RefreshIconButton', () => {
    it('names what it refreshes and spins only while busy', () => {
      const {rerender} = render(
        <RefreshIconButton
          label="Refresh notifications"
          onClick={vi.fn()}
        />
      );

      const button = screen.getByRole('button', {name: 'Refresh notifications'});
      expect(button).toBeEnabled();
      expect(button.querySelector('svg')).not.toHaveClass('animate-spin');

      rerender(
        <RefreshIconButton
          label="Refresh notifications"
          busy
          onClick={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: 'Refresh notifications'})).toBeDisabled();
      expect(screen.getByRole('button', {name: 'Refresh notifications'}).querySelector('svg')).toHaveClass(
        'animate-spin'
      );
    });

    it('does not fire while busy', async () => {
      const onClick = vi.fn();
      render(
        <RefreshIconButton
          label="Refresh history"
          busy
          onClick={onClick}
        />
      );
      await userEvent.click(screen.getByRole('button', {name: 'Refresh history'}));
      expect(onClick).not.toHaveBeenCalled();
    });
  });
});

// ─── from SegmentedFilter.test.tsx ───
describe('SegmentedFilter', () => {
  const OPTIONS = [
    {value: 'all', label: 'All'},
    {value: 'clean', label: 'Clean'},
    {value: 'issues', label: 'Issues'}
  ] as const;

  describe('SegmentedFilter', () => {
    it('is one labelled group whose chosen option carries aria-pressed', () => {
      // The choice must not be conveyed by styling alone — that is the whole reason
      // this is a pressed-button group rather than a row of styled links.
      render(
        <SegmentedFilter
          label="Filter checks"
          options={OPTIONS}
          value="clean"
          onChange={vi.fn()}
        />
      );

      const group = screen.getByRole('group', {name: 'Filter checks'});
      expect(group).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Clean'})).toHaveAttribute('aria-pressed', 'true');
      expect(screen.getByRole('button', {name: 'All'})).toHaveAttribute('aria-pressed', 'false');
    });

    it('reports the chosen value', async () => {
      const onChange = vi.fn();
      render(
        <SegmentedFilter
          label="Filter checks"
          options={OPTIONS}
          value="all"
          onChange={onChange}
        />
      );

      await userEvent.click(screen.getByRole('button', {name: 'Issues'}));
      expect(onChange).toHaveBeenCalledWith('issues');
    });

    it('renders the given labels, not the raw values', () => {
      render(
        <SegmentedFilter
          label="Filter notifications"
          options={[
            {value: 'all', label: 'All'},
            {value: 'unread', label: 'Unread'}
          ]}
          value="all"
          onChange={vi.fn()}
        />
      );
      expect(screen.getByRole('button', {name: 'Unread'})).toBeInTheDocument();
      // The negative is the point: the page this replaced rendered the raw value and
      // leaned on a CSS `capitalize`, so the accessible name was lowercase.
      expect(screen.queryByText('unread')).toBeNull();
    });

    it('has no axe violations', async () => {
      await expectNoA11yViolations(
        <SegmentedFilter
          label="Filter checks"
          options={OPTIONS}
          value="all"
          onChange={vi.fn()}
        />,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from MobileActionBar.test.tsx ───
describe('MobileActionBar', () => {
  describe('MobileActionBar', () => {
    it('renders caller-supplied actions in a labelled toolbar', () => {
      render(
        <MobileActionBar ariaLabel="File actions">
          <button type="button">New folder</button>
          <button type="button">Upload</button>
        </MobileActionBar>
      );
      const bar = screen.getByRole('toolbar', {name: 'File actions'});
      expect(bar).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'New folder'})).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Upload'})).toBeInTheDocument();
    });

    it('is fixed to the bottom, hidden at tablet, and honors the safe-area inset', () => {
      render(
        <MobileActionBar>
          <button type="button">Go</button>
        </MobileActionBar>
      );
      const bar = screen.getByRole('toolbar');
      expect(bar).toHaveClass('fixed', 'bottom-0', 'tablet:hidden');
      expect(bar.className).toContain('env(safe-area-inset-bottom)');
    });

    it('has no a11y violations', async () => {
      await expectNoA11yViolations(
        <MobileActionBar ariaLabel="Actions">
          <button type="button">Upload</button>
        </MobileActionBar>,
        COMPONENT_AXE_OPTIONS
      );
    });
  });
});

// ─── from primitives.a11y.test.tsx ───
describe('primitives.a11y', () => {
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
});
