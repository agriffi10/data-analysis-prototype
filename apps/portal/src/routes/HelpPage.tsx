import {HelpPage as HelpView} from '../features/help';

/** The `/help` route — reached via the header help link; the feature view owns the content and document title. */
export default function HelpPage() {
  return <HelpView />;
}
