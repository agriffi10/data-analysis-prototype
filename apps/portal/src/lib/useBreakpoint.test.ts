import {describe, it, expect, afterEach} from 'vitest';
import {renderHook} from '@testing-library/react';
import {useBreakpoint, useIsMobile} from './useBreakpoint';

function setWidth(w: number) {
  Object.defineProperty(window, 'innerWidth', {value: w, writable: true, configurable: true});
}

describe('useBreakpoint', () => {
  afterEach(() => setWidth(1024));

  it('reports mobile below the tablet threshold (<900px)', () => {
    setWidth(500);
    expect(renderHook(() => useBreakpoint()).result.current).toEqual({
      isMobile: true,
      isTablet: false,
      isDesktop: false
    });
    expect(renderHook(() => useIsMobile()).result.current).toBe(true);
  });

  it('reports tablet in the [900, 1300) band', () => {
    setWidth(1000);
    expect(renderHook(() => useBreakpoint()).result.current).toEqual({
      isMobile: false,
      isTablet: true,
      isDesktop: false
    });
    expect(renderHook(() => useIsMobile()).result.current).toBe(false);
  });

  it('reports desktop at or above 1300px', () => {
    setWidth(1400);
    expect(renderHook(() => useBreakpoint()).result.current).toEqual({
      isMobile: false,
      isTablet: false,
      isDesktop: true
    });
  });

  it('treats the exact thresholds as inclusive lower bounds', () => {
    setWidth(900);
    expect(renderHook(() => useBreakpoint()).result.current.isTablet).toBe(true);
    setWidth(1300);
    expect(renderHook(() => useBreakpoint()).result.current.isDesktop).toBe(true);
  });
});
