import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent, waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {AppNavDrawer} from './AppNavDrawer';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';

function renderDrawer(props: Partial<React.ComponentProps<typeof AppNavDrawer>> = {}, route = '/files') {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AppNavDrawer
        open
        onClose={props.onClose ?? vi.fn()}
        {...props}
      />
    </MemoryRouter>
  );
}

const DESTS = ['Files', 'Query', 'Connections', 'Notifications', 'Help'];

describe('AppNavDrawer', () => {
  it('renders nothing when closed', () => {
    renderDrawer({open: false});
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('lists the five primary destinations as links', () => {
    renderDrawer();
    for (const label of DESTS) {
      expect(screen.getByRole('link', {name: label})).toBeInTheDocument();
    }
  });

  it('marks the current route active with aria-current', () => {
    renderDrawer({}, '/query');
    expect(screen.getByRole('link', {name: 'Query'})).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', {name: 'Files'})).not.toHaveAttribute('aria-current', 'page');
  });

  it('closes on link activation, close button, Escape, and scrim tap', () => {
    const onClose = vi.fn();

    const {unmount} = renderDrawer({onClose});
    fireEvent.click(screen.getByRole('link', {name: 'Files'}));
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();

    const view2 = renderDrawer({onClose});
    fireEvent.click(screen.getByRole('button', {name: 'Close navigation'}));
    expect(onClose).toHaveBeenCalledTimes(2);
    view2.unmount();

    renderDrawer({onClose});
    fireEvent.keyDown(document, {key: 'Escape'});
    fireEvent.click(screen.getByRole('dialog').parentElement!);
    expect(onClose).toHaveBeenCalledTimes(4);
  });

  it('renders a page-supplied contextual rail, and nothing when omitted', () => {
    const {unmount} = renderDrawer({contextualRail: <div>SPACES RAIL</div>});
    expect(screen.getByText('SPACES RAIL')).toBeInTheDocument();
    unmount();

    renderDrawer();
    expect(screen.queryByText('SPACES RAIL')).not.toBeInTheDocument();
  });

  it('moves focus into the drawer on open and returns it to the trigger on close', async () => {
    function Harness({open}: {open: boolean}) {
      return (
        <MemoryRouter>
          <button>hamburger</button>
          <AppNavDrawer
            open={open}
            onClose={vi.fn()}
          />
        </MemoryRouter>
      );
    }
    const {rerender} = render(<Harness open={false} />);
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

  it('has no a11y violations', async () => {
    await expectNoA11yViolations(
      <MemoryRouter initialEntries={['/files']}>
        <AppNavDrawer
          open
          onClose={vi.fn()}
          contextualRail={<div>rail</div>}
        />
      </MemoryRouter>,
      COMPONENT_AXE_OPTIONS
    );
  });
});
