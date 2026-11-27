import {describe, expect, it, vi} from 'vitest';
import {fireEvent, render, screen} from '@testing-library/react';
import {ColumnResizeHandle} from './ColumnResizeHandle';
import {COLUMN_RESIZE_STEP_PX} from './catalog.constants';

// The handle moved here from `features/query/` in SPEC-180: two sibling features draw
// result grids and neither may import the other. Its tests moved with it, and the column
// identifier is exercised in BOTH of its shapes — an index (the Query workspace) and a
// name (the Data Explorer) — because the generic parameter is the point of the move.

describe('ColumnResizeHandle', () => {
  function renderHandle(over: Partial<Parameters<typeof ColumnResizeHandle<number>>[0]> = {}) {
    const props = {
      column: 2,
      columnName: 'revenue',
      width: 180,
      onResize: vi.fn(),
      onReset: vi.fn(),
      ...over
    };
    const {unmount} = render(<ColumnResizeHandle {...props} />);
    return {...props, unmount};
  }

  it('is an accessible vertical separator naming its column', () => {
    renderHandle();
    const handle = screen.getByRole('separator', {name: 'Resize column revenue'});
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    expect(handle).toHaveAttribute('tabindex', '0');
  });

  it('drag resizes by the pointer delta from the gesture origin', () => {
    const {onResize} = renderHandle({column: 2, width: 180});
    const handle = screen.getByRole('separator');
    fireEvent.pointerDown(handle, {clientX: 100});
    fireEvent.pointerMove(window, {clientX: 140}); // +40
    expect(onResize).toHaveBeenLastCalledWith(2, 220);
    fireEvent.pointerMove(window, {clientX: 60}); // -40 from origin
    expect(onResize).toHaveBeenLastCalledWith(2, 140);
  });

  it('stops resizing after pointerup', () => {
    const onResize = vi.fn();
    renderHandle({onResize});
    const handle = screen.getByRole('separator');
    fireEvent.pointerDown(handle, {clientX: 100});
    fireEvent.pointerUp(window);
    onResize.mockClear();
    fireEvent.pointerMove(window, {clientX: 300});
    expect(onResize).not.toHaveBeenCalled();
  });

  it('stops resizing when the browser takes the gesture over, which fires no pointerup', () => {
    const {onResize} = renderHandle();
    fireEvent.pointerDown(screen.getByRole('separator'), {clientX: 100});
    fireEvent.pointerMove(window, {clientX: 140});
    expect(onResize).toHaveBeenCalledTimes(1);

    fireEvent.pointerCancel(window);
    fireEvent.pointerMove(window, {clientX: 300});

    expect(onResize).toHaveBeenCalledTimes(1);
  });

  it('stops resizing when the grid goes mid-drag, so a stale handle writes no width', () => {
    const {onResize, unmount} = renderHandle();
    fireEvent.pointerDown(screen.getByRole('separator'), {clientX: 100});
    fireEvent.pointerMove(window, {clientX: 140});
    expect(onResize).toHaveBeenCalledTimes(1);

    unmount();
    fireEvent.pointerMove(window, {clientX: 300});

    expect(onResize).toHaveBeenCalledTimes(1);
  });

  it('ends a drag still in flight when another starts, so one gesture writes one width', () => {
    const onResize = vi.fn();
    const {unmount} = renderHandle({column: 2, width: 180, onResize});
    const handle = screen.getByRole('separator');
    fireEvent.pointerDown(handle, {clientX: 100});
    fireEvent.pointerDown(handle, {clientX: 200});

    fireEvent.pointerMove(window, {clientX: 240});
    expect(onResize.mock.calls).toEqual([[2, 220]]);

    unmount();
    fireEvent.pointerMove(window, {clientX: 300});
    expect(onResize).toHaveBeenCalledTimes(1);
  });

  it('follows the pointer that started the drag, and no other finger on the screen', () => {
    const onResize = vi.fn();
    renderHandle({column: 2, width: 180, onResize});
    fireEvent.pointerDown(screen.getByRole('separator'), {clientX: 100, pointerId: 1});

    fireEvent.pointerMove(window, {clientX: 400, pointerId: 2});
    fireEvent.pointerUp(window, {pointerId: 2});
    fireEvent.pointerMove(window, {clientX: 140, pointerId: 1});

    expect(onResize.mock.calls).toEqual([[2, 220]]);
  });

  it('double-click resets the column', () => {
    const {onReset} = renderHandle({column: 2});
    fireEvent.doubleClick(screen.getByRole('separator'));
    expect(onReset).toHaveBeenCalledWith(2);
  });

  it('Arrow Right / Left adjust the width by the keyboard step', () => {
    const {onResize} = renderHandle({column: 2, width: 180});
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, {key: 'ArrowRight'});
    expect(onResize).toHaveBeenLastCalledWith(2, 180 + COLUMN_RESIZE_STEP_PX);
    fireEvent.keyDown(handle, {key: 'ArrowLeft'});
    expect(onResize).toHaveBeenLastCalledWith(2, 180 - COLUMN_RESIZE_STEP_PX);
  });

  it('reports a NAME-keyed column back to its caller unchanged', () => {
    const onResize = vi.fn();
    const onReset = vi.fn();
    render(
      <ColumnResizeHandle
        column="revenue"
        columnName="revenue"
        width={180}
        onResize={onResize}
        onReset={onReset}
      />
    );
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, {key: 'ArrowRight'});
    expect(onResize).toHaveBeenLastCalledWith('revenue', 180 + COLUMN_RESIZE_STEP_PX);
    fireEvent.doubleClick(handle);
    expect(onReset).toHaveBeenCalledWith('revenue');
  });
});
