import {describe, expect, it} from 'vitest';
import {MENU_MIN_WIDTH_PX} from '../../components/Menu';
import {contentRightOf, menuAlignFor} from './menuAlign';

describe('menuAlignFor', () => {
  it('opens leftward when opening rightward would pass the grid box’s content edge', () => {
    expect(menuAlignFor(800 - MENU_MIN_WIDTH_PX + 1, 800)).toBe('right');
    expect(menuAlignFor(800 - MENU_MIN_WIDTH_PX, 800)).toBe('left');
  });

  it('measures to the content edge, inside the scrollbar gutter, and keeps the default when unmeasured', () => {
    const box = document.createElement('div');
    box.getBoundingClientRect = () => new DOMRect(100, 0, 815, 400);
    Object.defineProperty(box, 'clientLeft', {value: 1});
    Object.defineProperty(box, 'clientWidth', {value: 798});

    expect(contentRightOf(box)).toBe(899);
    expect(contentRightOf(document.createElement('div'))).toBeUndefined();
    expect(menuAlignFor(700, undefined)).toBe('left');
  });
});
