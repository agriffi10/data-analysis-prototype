import {describe, it, expect, afterEach} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {LandingNavMenu} from './LandingNavMenu';
import {expectNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../test/axe';

const links = [
  {label: 'Features', href: '#features'},
  {label: 'Security', href: '#security'}
];

afterEach(() => {
  window.location.hash = '';
});

describe('LandingNavMenu', () => {
  it('is a closed hamburger toggle initially', () => {
    render(<LandingNavMenu links={links} />);
    const toggle = screen.getByRole('button', {name: 'Open menu'});
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    // The whole control is mobile-only.
    expect(toggle.closest('.relative')).toHaveClass('tablet:hidden');
  });

  it('reveals the section anchors when toggled', () => {
    render(<LandingNavMenu links={links} />);
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    expect(screen.getByRole('menuitem', {name: 'Features'})).toBeInTheDocument();
    expect(screen.getByRole('menuitem', {name: 'Security'})).toBeInTheDocument();
    expect(screen.getByRole('button', {name: 'Open menu'})).toHaveAttribute('aria-expanded', 'true');
  });

  it('navigates to the anchor and closes the panel on link activation', () => {
    render(<LandingNavMenu links={links} />);
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Security'}));
    expect(window.location.hash).toBe('#security');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes on Escape and on outside click', () => {
    render(
      <div>
        <button>outside</button>
        <LandingNavMenu links={links} />
      </div>
    );
    const open = () => fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));

    open();
    fireEvent.keyDown(screen.getByRole('menu'), {key: 'Escape'});
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    open();
    fireEvent.mouseDown(screen.getByRole('button', {name: 'outside'}));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('has no a11y violations (closed)', async () => {
    await expectNoA11yViolations(<LandingNavMenu links={links} />, COMPONENT_AXE_OPTIONS);
  });
});
