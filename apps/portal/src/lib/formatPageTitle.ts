// Canonical document-title formatting (SPEC-031). Pure + DOM-free so it can be
// unit-tested directly; the side-effecting `usePageTitle` hook wraps it.
const APP_NAME = 'S3 File Portal';

// Returns "{page} — S3 File Portal" (em-dash) when a page name is given, or just
// the product name when omitted/empty (used by the landing page).
export function formatPageTitle(page?: string): string {
  return page ? `${page} — ${APP_NAME}` : APP_NAME;
}
