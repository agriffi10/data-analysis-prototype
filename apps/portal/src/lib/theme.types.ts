/** What the user chose. Persisted per browser; `system` follows `prefers-color-scheme`. */
export type ThemePreference = 'light' | 'dark' | 'system';

/** What is actually painted, after resolving `system`. */
export type EffectiveTheme = 'light' | 'dark';
