import {
  ATHENA_RESULTS_FOLDER,
  DATA_QUALITY_REPORTS_FOLDER,
  SHARED_TABLES_FOLDER,
  SYSTEM_SETTINGS_FOLDER
} from '../../lib/appManagedPaths';

/**
 * The first segments below a space root that the data-quality plane refuses to check.
 *
 * Mirrors `dqcommon.config.RESERVED_PREFIXES`, which `lambdas/test_quality_check_browser_mirror.py`
 * holds equal. The plane refuses these as `forbidden`, whose sentence is "You don't have access",
 * which is false of a folder the user can plainly open — so the browser refuses first, in words.
 */
export const QUALITY_CHECK_RESERVED_ROOTS = [
  ATHENA_RESULTS_FOLDER,
  'user_settings',
  SHARED_TABLES_FOLDER,
  DATA_QUALITY_REPORTS_FOLDER,
  '_fc-work',
  '_directory',
  SYSTEM_SETTINGS_FOLDER
] as const;

/** Why a check of that item is refused, shown on the disabled control. */
export const QUALITY_CHECK_RESERVED_REFUSAL =
  'Data Quarry manages this folder, so its data can’t be checked here. Copy the files into a folder of your own and check that.';

/**
 * Why the data-quality check refuses this item, or undefined when it may be checked.
 *
 * @param key - The selected file's key or folder's prefix, absolute.
 * @param rootPrefix - The space root the key sits under.
 * @returns The refusal, or undefined.
 */
export function qualityCheckRefusal(key: string, rootPrefix: string): string | undefined {
  if (!key.startsWith(rootPrefix)) return undefined;
  const first = key.slice(rootPrefix.length).split('/')[0];
  return (QUALITY_CHECK_RESERVED_ROOTS as readonly string[]).includes(first)
    ? QUALITY_CHECK_RESERVED_REFUSAL
    : undefined;
}
