import {useCallback, useState} from 'react';
import {useToast} from '../../components/toastContext';
import {toUserText} from '../../lib/errorMessages';
import {lastSegment} from '../file-browser/fileBrowser.paths';
import {enqueueTableBuild} from './tableBuild.service';
import type {ChosenFolder} from './CreateTableFromSpaceDialog';
import type {PartitionKey} from './tableBuild.types';

export type UseCreateTableFromSpaceResult = {
  /** Which step is showing, or null when the flow is closed. */
  step: 'folder' | 'name' | null;
  /** The chosen folder, once there is one — the name step needs its path and suggestion. */
  folder: ChosenFolder | null;
  busy: boolean;
  error: string | null;
  start: () => void;
  chooseFolder: (folder: ChosenFolder) => void;
  submit: (args: {tableName: string; partitionKeys: PartitionKey[]}) => Promise<void>;
  cancel: () => void;
};

/**
 * The two-step create-table flow for a surface with no folder in view: choose a folder, then
 * name the table.
 *
 * `CreateTableButton` needs neither the state machine nor the first step — on the Files toolbar
 * the folder in view IS the answer, and it opens the name prompt directly. This exists because
 * the Data Explorer has no folder in view and the same build needs one chosen first; the second
 * step is the SAME `CreateTableDialog`, and the enqueue is the same one call.
 *
 * A hook rather than state inside the picker, because the picker is unmounted the moment a tab
 * opens and this flow outlives nothing — but it does outlive the picker's own scroll position,
 * and putting it here keeps the picker a rendering of what it is given.
 *
 * Async, like every table build: a success toast confirms the submission and the OUTCOME
 * arrives as a notification. A failure keeps the name step up with the reason on it, so the
 * user can retry without re-choosing the folder.
 *
 * @returns The step, the chosen folder, the in-flight flag, the error and the four actions.
 */
export function useCreateTableFromSpace(): UseCreateTableFromSpaceResult {
  const [step, setStep] = useState<'folder' | 'name' | null>(null);
  const [folder, setFolder] = useState<ChosenFolder | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  const start = useCallback(() => {
    setError(null);
    setFolder(null);
    setStep('folder');
  }, []);

  const chooseFolder = useCallback((chosen: ChosenFolder) => {
    setError(null);
    setFolder(chosen);
    setStep('name');
  }, []);

  const cancel = useCallback(() => {
    setStep(null);
    setFolder(null);
    setError(null);
  }, []);

  const submit = useCallback(
    async ({tableName, partitionKeys}: {tableName: string; partitionKeys: PartitionKey[]}) => {
      if (!folder) return;
      setBusy(true);
      setError(null);
      const result = await enqueueTableBuild({
        space: {
          kind: folder.spaceKind,
          bucket: folder.bucket,
          prefix: folder.prefix,
          database: folder.database
        },
        tableName,
        partitionKeys
      });
      setBusy(false);
      if (!result.success) {
        // The dialog stays up so the user can retry — no silent failure, and no lost folder.
        setError(toUserText(result.error));
        return;
      }
      setStep(null);
      setFolder(null);
      toast.push({
        variant: 'success',
        message: `Creating table “${tableName}”… you’ll be notified when it’s ready.`
      });
    },
    [folder, toast]
  );

  return {step, folder, busy, error, start, chooseFolder, submit, cancel};
}

/**
 * The name a chosen folder suggests for its table — its own last segment, or the space name at
 * a root the flow does not actually allow.
 *
 * @param folder - The chosen folder, or null before one is chosen.
 * @returns The suggestion, or '' when there is no folder yet.
 */
export function suggestedNameFor(folder: ChosenFolder | null): string {
  if (!folder) return '';
  return lastSegment(folder.prefix) || folder.database;
}
