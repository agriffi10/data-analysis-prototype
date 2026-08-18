/**
 * Types for the static Help & guides content. All UI-local — nothing
 * outside `features/help/` consumes them, so they live here rather than in
 * `src/types/`. There is no runtime/user data: the content ships in the bundle.
 */

/** Which feature glyph a section/card renders (maps to an icon in `helpIcons`). */
export type HelpIconName = 'files' | 'query' | 'tables' | 'explore' | 'connections' | 'notifications';

/** Stable section id — also the URL hash (FR-003), e.g. `/help#query`. */
export type HelpSectionId = 'files' | 'query' | 'tables' | 'data-explorer' | 'shared-connections' | 'notifications';

/** An accent "Tip" or a danger "Careful" note; a guide renders at most one (FR-004). */
export type HelpCallout = {kind: 'tip'; text: string} | {kind: 'warning'; text: string};

/** A single how-to guide — one task the user can perform. */
export type HelpGuide = {
  /** Stable slug, unique within its section (e.g. `upload-files`). */
  id: string;
  title: string;
  /** One line shown beneath the title. */
  subtitle: string;
  /**
   * Optional friendly framing shown above the steps — a sentence or two of
   * context (what this is for, when you'd reach for it). May contain `<b>…</b>`.
   */
  intro?: string;
  /** Ordered steps; text may contain `<b>…</b>` emphasis for UI labels. */
  steps: string[];
  callout?: HelpCallout;
};

/** A feature section — one sidebar item + one content panel. */
export type HelpSection = {
  id: HelpSectionId;
  /** Sidebar item + page title, e.g. "Files". */
  label: string;
  /** `PageLayout` subtitle for the section. */
  subtitle: string;
  icon: HelpIconName;
  /** The section's guides; the count drives the sidebar badge (FR-003). */
  guides: HelpGuide[];
};
