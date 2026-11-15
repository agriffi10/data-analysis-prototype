/**
 * The few navigations that move the whole document rather than the app: to the server's sign-in
 * route, to the provider's logout page, and the reload that drops one user's page when another has
 * signed in on this browser.
 *
 * A module of its own so a test can observe them. jsdom's `location.assign` and `reload` can be
 * neither replaced nor spied on, and do nothing, so a test that called them directly could assert
 * nothing about where the document went.
 */

/**
 * Navigate the document to a URL, leaving the app.
 *
 * @param url - Where to.
 * @returns None.
 */
export function assignDocument(url: string): void {
  window.location.assign(url);
}

/**
 * Reload the document, discarding every page state the app holds.
 *
 * @returns None.
 */
export function reloadDocument(): void {
  window.location.reload();
}
