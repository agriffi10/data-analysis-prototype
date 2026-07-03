import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {ResultTabs} from './ResultTabs';
import type {ResultTab} from './query.types';

const tabs: ResultTab[] = [
  {statementIndex: 0, executionId: 'q-1', label: '1 · SELECT a'},
  {statementIndex: 2, executionId: 'q-3', label: '3 · SELECT b'},
  {statementIndex: 3, executionId: 'q-4', label: '4 · SHOW TABLES'}
];

function renderTabs(activeIndex = 0, onSelect = vi.fn()) {
  render(
    <ResultTabs
      tabs={tabs}
      activeIndex={activeIndex}
      onSelect={onSelect}
    />
  );
  return onSelect;
}

describe('ResultTabs (SPEC-078 FR-007)', () => {
  it('renders one labeled tab per result set, in order, with the active tab selected', () => {
    renderTabs(1);
    const rendered = screen.getAllByRole('tab');
    expect(rendered.map((t) => t.textContent)).toEqual(['1 · SELECT a', '3 · SELECT b', '4 · SHOW TABLES']);
    expect(rendered[1]).toHaveAttribute('aria-selected', 'true');
    expect(rendered[0]).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tablist', {name: 'Result tabs'})).toBeInTheDocument();
  });

  it('clicking a tab selects it', () => {
    const onSelect = renderTabs(0);
    fireEvent.click(screen.getByRole('tab', {name: /SHOW TABLES/}));
    expect(onSelect).toHaveBeenCalledWith(2);
  });

  it('uses a roving tabindex — only the active tab is in the Tab sequence', () => {
    renderTabs(1);
    const rendered = screen.getAllByRole('tab');
    expect(rendered.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
  });

  it('supports the WAI-ARIA tabs keyboard model (arrows wrap, Home/End jump)', () => {
    const onSelect = renderTabs(1);
    const rendered = screen.getAllByRole('tab');

    fireEvent.keyDown(rendered[1], {key: 'ArrowRight'});
    expect(onSelect).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(rendered[1], {key: 'ArrowLeft'});
    expect(onSelect).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(rendered[2], {key: 'ArrowRight'}); // wraps
    expect(onSelect).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(rendered[1], {key: 'Home'});
    expect(onSelect).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(rendered[1], {key: 'End'});
    expect(onSelect).toHaveBeenLastCalledWith(2);
  });
});
