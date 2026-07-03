import {describe, it, expect, beforeEach} from 'vitest';
import {renderHook, act} from '@testing-library/react';
import {useEditorLayout, clampEditorHeight} from './useEditorLayout';
import {
  DEFAULT_LAYOUT_PRESET,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  QUERY_EDITOR_LAYOUT_STORAGE_PREFIX
} from './query.constants';

const USER = 'alice';
const KEY = `${QUERY_EDITOR_LAYOUT_STORAGE_PREFIX}${USER}`;

beforeEach(() => {
  sessionStorage.clear();
});

describe('clampEditorHeight', () => {
  it('maps each preset to its proportion of a tall container', () => {
    // 1000px is tall enough that no floor kicks in except the results cap at 90%.
    expect(clampEditorHeight('even', 1000)).toBe(500);
    expect(clampEditorHeight('results', 1000)).toBe(100);
    // editor 90% of 1000 = 900 > 1000 - MIN_RESULTS_HEIGHT → capped.
    expect(clampEditorHeight('editor', 1000)).toBe(1000 - MIN_RESULTS_HEIGHT);
  });

  it('gives the editor its full 90% once the results floor is satisfied', () => {
    const h = MIN_RESULTS_HEIGHT * 10; // 90% leaves exactly the results floor
    expect(clampEditorHeight('editor', h)).toBe(h - MIN_RESULTS_HEIGHT);
    // Taller than that, 90% is below the cap → pure proportion.
    expect(clampEditorHeight('editor', 2000)).toBe(1800);
  });

  it('floors the editor at MIN_EDITOR_HEIGHT on the Results preset', () => {
    // 10% of 600 = 60 < MIN_EDITOR_HEIGHT.
    expect(clampEditorHeight('results', 600)).toBe(MIN_EDITOR_HEIGHT);
  });

  it('caps the editor so the results region keeps MIN_RESULTS_HEIGHT on the Editor preset', () => {
    // 90% of 400 = 360 > 400 - 120 = 280 → capped.
    expect(clampEditorHeight('editor', 400)).toBe(400 - MIN_RESULTS_HEIGHT);
  });

  it('lets the editor floor win when a short viewport cannot honor both floors', () => {
    // container - MIN_RESULTS_HEIGHT < MIN_EDITOR_HEIGHT → the editor floor wins;
    // never a negative/overlapping height.
    const short = MIN_EDITOR_HEIGHT + MIN_RESULTS_HEIGHT - 40;
    expect(clampEditorHeight('editor', short)).toBe(MIN_EDITOR_HEIGHT);
    expect(clampEditorHeight('results', short)).toBe(MIN_EDITOR_HEIGHT);
    expect(clampEditorHeight('even', 0)).toBe(MIN_EDITOR_HEIGHT);
  });
});

describe('useEditorLayout', () => {
  it('defaults to the even preset with no stored value', () => {
    const {result} = renderHook(() => useEditorLayout(USER, 1000));
    expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
    expect(result.current.editorHeight).toBe(500);
  });

  it('setPreset applies the new proportion and persists it per user', () => {
    const {result} = renderHook(() => useEditorLayout(USER, 1000));
    act(() => result.current.setPreset('results'));
    expect(result.current.preset).toBe('results');
    expect(result.current.editorHeight).toBe(100);
    expect(sessionStorage.getItem(KEY)).toBe('results');
  });

  it('restores a stored preset on mount (reload/tab-switch survival)', () => {
    sessionStorage.setItem(KEY, 'editor');
    const {result} = renderHook(() => useEditorLayout(USER, 1000));
    expect(result.current.preset).toBe('editor');
  });

  it('ignores a corrupt stored value and falls back to the default', () => {
    sessionStorage.setItem(KEY, 'sideways');
    const {result} = renderHook(() => useEditorLayout(USER, 1000));
    expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
  });

  it('scopes persistence to the username', () => {
    sessionStorage.setItem(`${QUERY_EDITOR_LAYOUT_STORAGE_PREFIX}bob`, 'editor');
    const {result} = renderHook(() => useEditorLayout(USER, 1000));
    expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
  });

  it('works without persisting when username is null', () => {
    const {result} = renderHook(() => useEditorLayout(null, 1000));
    act(() => result.current.setPreset('editor'));
    expect(result.current.preset).toBe('editor');
    expect(sessionStorage.length).toBe(0);
  });

  it('still selects (non-persistently) when sessionStorage throws', () => {
    const throwing = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      }
    };
    const original = Object.getOwnPropertyDescriptor(globalThis, 'sessionStorage');
    Object.defineProperty(globalThis, 'sessionStorage', {value: throwing, configurable: true});
    try {
      const {result} = renderHook(() => useEditorLayout(USER, 1000));
      expect(result.current.preset).toBe(DEFAULT_LAYOUT_PRESET);
      act(() => result.current.setPreset('results'));
      expect(result.current.preset).toBe('results');
    } finally {
      if (original) Object.defineProperty(globalThis, 'sessionStorage', original);
    }
  });

  it('re-derives the height when the container resizes', () => {
    const {result, rerender} = renderHook(({height}: {height: number}) => useEditorLayout(USER, height), {
      initialProps: {height: 1000}
    });
    expect(result.current.editorHeight).toBe(500);
    rerender({height: 700});
    expect(result.current.editorHeight).toBe(350);
  });
});
