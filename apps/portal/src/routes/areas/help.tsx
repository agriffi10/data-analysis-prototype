import HelpPage from '../HelpPage';

/**
 * Help, at `/help`, reached by the header's help control rather than the tab bar.
 *
 * Eager: its content is a small static module already in the main bundle.
 *
 * @returns The Help page.
 */
export function HelpView() {
  return <HelpPage />;
}
