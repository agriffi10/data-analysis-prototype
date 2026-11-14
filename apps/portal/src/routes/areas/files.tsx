import {FeatureRoute} from '../FeatureRoute';
import FilesPage from '../FilesPage';

/**
 * Files, at `/files`.
 *
 * A gated view keeps its path and swaps what renders. The route must still match, or a disabled
 * feature would fall through to the 404 and tell a user with a perfectly correct link that their
 * URL is wrong.
 *
 * @returns The Files page behind its flag.
 */
export function FilesView() {
  return (
    <FeatureRoute flag="files">
      <FilesPage />
    </FeatureRoute>
  );
}
