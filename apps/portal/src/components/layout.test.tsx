import userEvent from '@testing-library/user-event';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, render, screen, waitFor, within} from '@testing-library/react';
import {USER_EVENT_OPTIONS, renderWithProviders} from '../test/renderWithProviders';
import {AppNavDrawer} from './AppNavDrawer';
import {CollapsibleRail} from './CollapsibleRail';
import {RAIL_COLLAPSED_STORAGE_KEY} from './useRailCollapsed';
import {memoryStorage} from '../test/storage';
import {ErrorBoundary} from './ErrorBoundary';

// ─── from AppNavDrawer.test.tsx ───
describe('AppNavDrawer', () => {
  function renderDrawer(props: Partial<React.ComponentProps<typeof AppNavDrawer>> = {}, route = '/files') {
    return renderWithProviders(
      <AppNavDrawer
        open
        onClose={props.onClose ?? vi.fn()}
        isPathEnabled={() => true}
        {...props}
      />,
      {route, auth: null}
    );
  }

  describe('AppNavDrawer', () => {
    it('renders nothing when closed', () => {
      renderDrawer({open: false});
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });

    it('closes on link activation, close button, Escape, and scrim tap', async () => {
      const onClose = vi.fn();

      const {unmount, user} = renderDrawer({onClose});
      await user.click(screen.getByRole('link', {name: 'Files'}));
      expect(onClose).toHaveBeenCalledTimes(1);
      unmount();

      const view2 = renderDrawer({onClose});
      await user.click(screen.getByRole('button', {name: 'Close navigation'}));
      expect(onClose).toHaveBeenCalledTimes(2);
      view2.unmount();

      renderDrawer({onClose});
      await user.keyboard('{Escape}');
      await user.click(screen.getByRole('dialog').parentElement!);
      expect(onClose).toHaveBeenCalledTimes(4);
    });

    it('stays open when a press inside the drawer is released over the scrim', async () => {
      const onClose = vi.fn();
      const {user} = renderDrawer({onClose});
      const drawer = screen.getByRole('dialog', {name: 'Navigation'});

      await user.pointer([
        {keys: '[MouseLeft>]', target: drawer},
        {target: drawer.parentElement!},
        {keys: '[/MouseLeft]', target: drawer.parentElement!}
      ]);

      expect(onClose).not.toHaveBeenCalled();
    });

    it('moves focus into the drawer on open and returns it to the trigger on close', async () => {
      function Harness({open}: {open: boolean}) {
        return (
          <>
            <button>hamburger</button>
            <AppNavDrawer
              open={open}
              onClose={vi.fn()}
              isPathEnabled={() => true}
            />
          </>
        );
      }
      const {rerender} = renderWithProviders(<Harness open={false} />, {auth: null});
      const trigger = screen.getByRole('button', {name: 'hamburger'});
      trigger.focus();
      expect(trigger).toHaveFocus();

      rerender(<Harness open />);
      await waitFor(() => {
        const dialog = screen.getByRole('dialog', {name: 'Navigation'});
        expect(dialog.contains(document.activeElement)).toBe(true);
      });

      rerender(<Harness open={false} />);
      await waitFor(() => expect(trigger).toHaveFocus());
    });
  });
});

// ─── from CollapsibleRail.test.tsx ───
describe('CollapsibleRail', () => {
  beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));

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
    it('collapsing reveals a reopen handle wired to the rail; reopening hides it again', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      renderRail();
      await user.click(screen.getByRole('button', {name: /collapse sidebar/i}));

      const handle = screen.getByRole('button', {name: /show sidebar/i});
      expect(handle).toHaveAttribute('aria-expanded', 'false');
      expect(handle).toHaveAttribute('aria-controls', screen.getByRole('complementary', {name: 'Test rail'}).id);
      // The panel content is retained (not unmounted) so in-rail state survives.
      expect(
        within(screen.getByRole('complementary', {name: 'Test rail'})).getByRole('button', {name: 'child action'})
      ).toBeInTheDocument();

      await user.click(handle);
      expect(screen.queryByRole('button', {name: /show sidebar/i})).not.toBeInTheDocument();
      expect(screen.getByRole('button', {name: /collapse sidebar/i})).toBeInTheDocument();
    });

    it('moves focus to Show sidebar on a collapse, having taken none on mount', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      renderRail();
      expect(document.body).toHaveFocus();

      await user.click(screen.getByRole('button', {name: /collapse sidebar/i}));

      expect(screen.getByRole('button', {name: /show sidebar/i})).toHaveFocus();
    });

    it('moves focus back to Collapse when Show sidebar unmounts itself', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      localStorage.setItem(RAIL_COLLAPSED_STORAGE_KEY, 'true');
      renderRail();
      const focus = vi.spyOn(HTMLElement.prototype, 'focus');

      await user.click(screen.getByRole('button', {name: /show sidebar/i}));

      const collapse = screen.getByRole('button', {name: /collapse sidebar/i});
      expect(collapse).toHaveFocus();
      // Nor may that focus scroll: the rail's box is still easing open from zero width, and
      // scrolling Collapse into view there anchors the content to the right (measured in Chromium).
      expect(focus).toHaveBeenLastCalledWith({preventScroll: true});
      focus.mockRestore();
      // jsdom runs no transitions, so this is the only fence it has on the real-browser half: a
      // panel whose visibility transitions IN is still hidden when that focus lands, and Chrome
      // refuses it. Measured: a 200ms visibility transition left focus on <body>, 0ms on the button.
      expect(collapse.closest('.transition-\\[visibility\\]')).toHaveClass('duration-0');
    });

    it('persists the collapsed choice under the single shared key', async () => {
      const user = userEvent.setup(USER_EVENT_OPTIONS);
      renderRail();
      await user.click(screen.getByRole('button', {name: /collapse sidebar/i}));
      expect(localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe('true');
    });
  });
});

// ─── from ErrorBoundary.test.tsx ───
describe('ErrorBoundary', () => {
  function Boom({message = 'chunk load failed'}: {message?: string}): never {
    throw new Error(message);
  }

  // React logs every caught error to console.error regardless of the boundary. That
  // is React's own noise, not ours, and would bury a real failure in the output.
  let consoleError: ReturnType<typeof vi.spyOn>;
  beforeEach(() => {
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  });
  afterEach(() => {
    consoleError.mockRestore();
    vi.unstubAllEnvs();
    cleanup();
  });

  describe('ErrorBoundary', () => {
    it('renders the fallback with a reload control when a child throws', () => {
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      );

      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText('This part of the page didn’t load')).toBeInTheDocument();
      expect(screen.getByRole('button', {name: 'Reload the page'})).toBeInTheDocument();
    });

    it('never renders the thrown error’s message (SPEC-106: no raw text on a surface)', () => {
      render(
        <ErrorBoundary>
          <Boom message="TypeError: Failed to fetch dynamically imported module: https://d123.cloudfront.net/assets/QueryPage-a1b2c3.js" />
        </ErrorBoundary>
      );

      expect(screen.queryByText(/cloudfront/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/Failed to fetch/i)).not.toBeInTheDocument();
      expect(document.body.textContent).not.toContain('QueryPage-a1b2c3.js');
    });
  });
});
