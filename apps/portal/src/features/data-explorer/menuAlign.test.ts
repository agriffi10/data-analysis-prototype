import {describe, expect, it} from 'vitest';
import {MENU_MIN_WIDTH_PX} from '../../components/Menu';
import {menuAlignFor} from './menuAlign';

const rect = (left: number, width: number) => new DOMRect(left, 0, width, 24);

describe('menuAlignFor', () => {
  it('opens leftward when opening rightward would pass the grid box’s right edge', () => {
    const box = rect(0, 800);

    expect(menuAlignFor(rect(800 - MENU_MIN_WIDTH_PX + 1, 24), box)).toBe('right');
    expect(menuAlignFor(rect(800 - MENU_MIN_WIDTH_PX, 24), box)).toBe('left');
  });

  it('keeps the default when there is no measured box to stay inside', () => {
    expect(menuAlignFor(rect(700, 24), undefined)).toBe('left');
    expect(menuAlignFor(rect(700, 24), rect(0, 0))).toBe('left');
  });
});
