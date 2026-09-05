const APP_NAME = 'Data Quarry';

/**
 * Formats the document title: "{page} — Data Quarry" (em-dash), or just the
 * product name when the page is omitted/empty. Pure and DOM-free; the
 * side-effecting `usePageTitle` hook wraps it.
 */
export function formatPageTitle(page?: string): string {
  return page ? `${page} — ${APP_NAME}` : APP_NAME;
}
