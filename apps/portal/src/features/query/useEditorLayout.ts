import {useMemo, useState} from 'react';
import {
  DEFAULT_LAYOUT_PRESET,
  LAYOUT_PRESET_EDITOR_FRACTION,
  MIN_EDITOR_HEIGHT,
  MIN_RESULTS_HEIGHT,
  QUERY_EDITOR_LAYOUT_STORAGE_PREFIX,
  type EditorLayoutPreset
} from './query.constants';

export type UseEditorLayoutResult = {
  /** The selected layout preset (session-persisted per user). */
  preset: EditorLayoutPreset;
  /** Selects a preset and persists it (best-effort) for the session. */
  setPreset: (preset: EditorLayoutPreset) => void;
  /** The editor pane's derived pixel height, clamped to the min-height floors. */
  editorHeight: number;
};

function storageKey(username: string | null): string | null {
  if (!username) return null;
  return `${QUERY_EDITOR_LAYOUT_STORAGE_PREFIX}${username}`;
}

function isPreset(value: unknown): value is EditorLayoutPreset {
  return value === 'editor' || value === 'even' || value === 'results';
}

// All storage access is wrapped so a disabled/quota-exceeded sessionStorage
// degrades to "not persisted" rather than crashing the workspace (FR-004).
function readStoredPreset(username: string | null): EditorLayoutPreset | null {
  const key = storageKey(username);
  if (!key) return null;
  try {
    const raw = sessionStorage.getItem(key);
    return isPreset(raw) ? raw : null;
  } catch {
    return null;
  }
}

function writeStoredPreset(username: string | null, preset: EditorLayoutPreset): void {
  const key = storageKey(username);
  if (!key) return;
  try {
    sessionStorage.setItem(key, preset);
  } catch {
    // Storage unavailable — the selection still applies for this render tree.
  }
}

/**
 * Derives the editor pane's clamped pixel height for a preset within the
 * available editor+results column height. The proportion is capped so the
 * results region keeps MIN_RESULTS_HEIGHT, then floored so the editor keeps
 * MIN_EDITOR_HEIGHT — on a viewport too short for both floors the editor
 * floor wins (no negative/overlapping panes, FR-002).
 */
export function clampEditorHeight(preset: EditorLayoutPreset, containerHeight: number): number {
  const proportional = containerHeight * LAYOUT_PRESET_EDITOR_FRACTION[preset];
  return Math.round(Math.max(MIN_EDITOR_HEIGHT, Math.min(proportional, containerHeight - MIN_RESULTS_HEIGHT)));
}

/**
 * Owns the SPEC-079 editor/results layout preset: the selection (per-user
 * sessionStorage persistence, degrade-safe, default `even`) and the editor
 * pane's derived pixel height within `containerHeight` (the measured
 * editor+results column). The caller applies `editorHeight` to the editor
 * pane; the results region takes the remainder.
 */
export function useEditorLayout(username: string | null, containerHeight: number): UseEditorLayoutResult {
  const [preset, setPresetState] = useState<EditorLayoutPreset>(
    () => readStoredPreset(username) ?? DEFAULT_LAYOUT_PRESET
  );

  const setPreset = (next: EditorLayoutPreset) => {
    setPresetState(next);
    writeStoredPreset(username, next);
  };

  const editorHeight = useMemo(() => clampEditorHeight(preset, containerHeight), [preset, containerHeight]);

  return {preset, setPreset, editorHeight};
}
