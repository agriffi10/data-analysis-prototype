import {FEATURE_FLAG_DEFAULTS, useFeatureSet} from '../feature-flags';

/**
 * Is the file browser handing copy, move, delete and rename to the control plane?
 *
 * **One reading of the flag, shared by the dispatcher and the in-flight surface**, because the two
 * have to agree in every state: a gesture that enqueues while the surface reads the flag as off
 * would leave the per-space gate held with nothing on screen to dismiss, and the dismiss is the
 * only thing that frees a space whose run never correlates.
 *
 * **While the flags are in flight this takes the compiled-in default rather than `useFeature`'s
 * conservative `false`.** The conservative answer everywhere else is "do not offer a control yet";
 * here it would be "run a folder move as up to three round trips per contained object from the
 * user's laptop", which is the cost the plane exists to remove.
 *
 * @returns True when a gesture that is not exactly one file goes to the plane.
 */
export function useAsyncFileOperations(): boolean {
  const {isEnabled, status} = useFeatureSet();
  return status === 'loading' ? FEATURE_FLAG_DEFAULTS.asyncFileOperations : isEnabled('asyncFileOperations');
}
