import {describe, it, expect, vi} from 'vitest';
import {render, screen, fireEvent} from '@testing-library/react';
import {ColumnResizeHandle} from './ColumnResizeHandle';
import {COLUMN_RESIZE_STEP_PX} from './query.constants';

function renderHandle(over: Partial<Parameters<typeof ColumnResizeHandle>[0]> = {}) {
  const props = {
    columnIndex: 2,
    columnName: 'revenue',
    width: 180,
    onResize: vi.fn(),
    onReset: vi.fn(),
    ...over
  };
  render(<ColumnResizeHandle {...props} />);
  return props;
}

describe('ColumnResizeHandle', () => {
  it('is an accessible vertical separator naming its column', () => {
    renderHandle();
    const handle = screen.getByRole('separator', {name: 'Resize column revenue'});
    expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    expect(handle).toHaveAttribute('tabindex', '0');
  });

  it('drag resizes by the pointer delta from the gesture origin', () => {
    const {onResize} = renderHandle({columnIndex: 2, width: 180});
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

  it('double-click resets the column', () => {
    const {onReset} = renderHandle({columnIndex: 2});
    fireEvent.doubleClick(screen.getByRole('separator'));
    expect(onReset).toHaveBeenCalledWith(2);
  });

  it('Arrow Right / Left adjust the width by the keyboard step', () => {
    const {onResize} = renderHandle({columnIndex: 2, width: 180});
    const handle = screen.getByRole('separator');
    fireEvent.keyDown(handle, {key: 'ArrowRight'});
    expect(onResize).toHaveBeenLastCalledWith(2, 180 + COLUMN_RESIZE_STEP_PX);
    fireEvent.keyDown(handle, {key: 'ArrowLeft'});
    expect(onResize).toHaveBeenLastCalledWith(2, 180 - COLUMN_RESIZE_STEP_PX);
  });
});
