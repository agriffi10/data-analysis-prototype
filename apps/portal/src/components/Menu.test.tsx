import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {configureAxe} from 'vitest-axe';
import {Menu, type MenuItem} from './Menu';
import {WCAG_TAGS} from '../test/axe';

// Local axe (the shared helper scans at render; the menu opens on click, so we
// open it first, then scan). Same disables as COMPONENT_AXE_OPTIONS + contrast.
const runAxe = configureAxe({
  runOnly: {type: 'tag', values: [...WCAG_TAGS]},
  rules: {'color-contrast': {enabled: false}, region: {enabled: false}}
});

function trigger(label = 'Open menu') {
  return ({open, toggle, ref}: {open: boolean; toggle: () => void; ref: React.Ref<HTMLButtonElement>}) => (
    <button
      ref={ref}
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      onClick={toggle}>
      {label}
    </button>
  );
}

function items(over: {rename?: () => void; remove?: () => void} = {}): MenuItem[] {
  return [
    {kind: 'action', label: 'Rename', onSelect: over.rename ?? vi.fn()},
    {kind: 'separator'},
    {kind: 'action', label: 'Delete', tone: 'danger', onSelect: over.remove ?? vi.fn()}
  ];
}

describe('Menu', () => {
  it('is closed initially and opens on trigger click', () => {
    render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={items()}
      />
    );
    const button = screen.getByRole('button', {name: 'Open menu'});
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();

    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu', {name: 'Row actions'})).toBeInTheDocument();
  });

  it('fires the item onSelect and closes', () => {
    const rename = vi.fn();
    render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={items({rename})}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    fireEvent.click(screen.getByRole('menuitem', {name: 'Rename'}));
    expect(rename).toHaveBeenCalledOnce();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('closes on Escape and on outside click', () => {
    render(
      <div>
        <button>outside</button>
        <Menu
          ariaLabel="Row actions"
          trigger={trigger()}
          items={items()}
        />
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

  it('roves focus between action items with arrow keys (skipping separators)', () => {
    render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={items()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    const rename = screen.getByRole('menuitem', {name: 'Rename'});
    const del = screen.getByRole('menuitem', {name: 'Delete'});
    expect(rename).toHaveFocus(); // first item focused on open

    fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowDown'});
    expect(del).toHaveFocus();
    fireEvent.keyDown(screen.getByRole('menu'), {key: 'ArrowUp'});
    expect(rename).toHaveFocus();
  });

  it('renders a danger-toned item and a separator', () => {
    render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={items()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    expect(screen.getByRole('menuitem', {name: 'Delete'})).toHaveClass('text-danger');
    expect(screen.getByRole('menu').querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });

  it('does not fire a disabled item', () => {
    const onSelect = vi.fn();
    render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={[{kind: 'action', label: 'Drop', onSelect, disabled: true}]}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    const item = screen.getByRole('menuitem', {name: 'Drop'});
    expect(item).toBeDisabled();
    fireEvent.click(item);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('has no a11y violations when open', async () => {
    const {container} = render(
      <Menu
        ariaLabel="Row actions"
        trigger={trigger()}
        items={items()}
      />
    );
    fireEvent.click(screen.getByRole('button', {name: 'Open menu'}));
    expect(await runAxe(container)).toHaveNoViolations();
  });
});
