import {useCallback, useEffect, useRef, useState} from 'react';
import {Modal} from '../../components/Modal';
import {DIALOG_PANEL, DIALOG_TITLE} from '../../components/dialogChrome';
import {SECTION_CAPTION} from '../../components/fieldStyles';
import {SpaceSelect} from '../../components/SpaceSelect';
import {DestinationPicker} from '../file-browser';
import {createTableRefusal, CREATE_TABLE_AT_ROOT_REFUSAL} from './createTableRefusal';

export type ChosenFolder = {
  spaceKind: 'personal' | 'shared';
  bucket: string;
  database: string;
  prefix: string;
  rootPrefix: string;
};

/**
 * A space this dialog can build in.
 *
 * Structural rather than `FileSpaceTarget`, so a caller can pass the list it has ALREADY put
 * through its own `sharedWorkspaces` filter. Reaching for `usableSpaceTargets` here instead
 * would rebuild the list from the connections and hand back the shared spaces the flag had just
 * removed. That is not hypothetical: the Query workspace shipped for a while offering a
 * colleague's space as a save destination with shared workspaces switched off.
 */
export type BuildableSpace = {
  id: string;
  label: string;
  bucket: string;
  rootPrefix: string;
  kind: 'personal' | 'shared';
};

export type CreateTableFromSpaceDialogProps = {
  /** Personal first, then the shared spaces the CALLER has decided to offer. */
  spaces: readonly BuildableSpace[];
  onChoose: (folder: ChosenFolder) => void;
  onCancel: () => void;
};

/**
 * Pick the folder a table will be built from, when the user is not already standing in one.
 *
 * The Files toolbar's `CreateTableButton` needs no such dialog — the folder in view IS the
 * answer. From the Data Explorer there is no folder in view at all, so the same build needs a
 * space and a folder chosen first, and this is that step and nothing else: it hands a folder to
 * `CreateTableDialog`, which still owns the name and the partition keys.
 *
 * **THE SPACE ROOT IS REFUSED HERE TOO, THROUGH THE SAME PREDICATE.** A table's `LOCATION` is
 * read recursively, so a build at the root sweeps in every app-managed folder the space keeps
 * there and succeeds while doing it. `allowCurrentParent` is therefore deliberately NOT set —
 * the picker's own confirm is disabled at the root — and `createTableRefusal` supplies the
 * sentence, so the browser has one wording for this rule and not two.
 *
 * @example
 * <CreateTableFromSpaceDialog spaces={spaces} onChoose={openNameDialog} onCancel={close} />
 */
export function CreateTableFromSpaceDialog({spaces, onChoose, onCancel}: CreateTableFromSpaceDialogProps) {
  const [spaceId, setSpaceId] = useState(spaces[0]?.id ?? '');
  const [prefix, setPrefix] = useState<string | null>(null);
  const selectRef = useRef<HTMLSelectElement>(null);

  const space = spaces.find((s) => s.id === spaceId) ?? spaces[0];

  // `Modal` sets `initialFocus: false` and defers to the consumer; there is no text field here
  // to inherit it, so focus goes to the space selector. With one space there is no selector and
  // the trap's fallback lands focus on the panel.
  useEffect(() => {
    selectRef.current?.focus();
  }, []);

  // Stable, or the picker's report-the-prefix effect would re-fire every render.
  const handleTargetChange = useCallback((next: {prefix: string}) => setPrefix(next.prefix), []);

  // A configuration error rather than an empty list — a personal space always exists. The
  // caller keeps the action hidden in that case; this is the belt to those braces.
  if (!space) return null;

  const current = prefix ?? space.rootPrefix;
  const refusal = createTableRefusal(current, space.rootPrefix);

  return (
    <Modal
      ariaLabel="Create table from a folder"
      dismissible
      onDismiss={onCancel}
      className={DIALOG_PANEL}>
      <h2 className={DIALOG_TITLE}>Create table from a folder</h2>
      <p className="mt-1 text-sm text-text-2">
        Choose the folder holding your data files. The portal reads them where they are — nothing is moved or copied —
        and builds the table in the background.
      </p>

      <SpaceSelect
        ref={selectRef}
        id="create-table-space"
        label="Space"
        spaces={spaces}
        value={space.id}
        onChange={setSpaceId}
      />

      <p className={`mb-1 mt-4 ${SECTION_CAPTION}`}>Data folder</p>
      <DestinationPicker
        // Remounting per space resets the breadcrumb and the browse prefix to that space's
        // root, so a folder can never straddle two spaces.
        key={space.id}
        bucket={space.bucket}
        items={[]}
        rootPrefix={space.rootPrefix}
        rootLabel={space.label}
        currentPrefix={space.rootPrefix}
        confirmDisabled={refusal !== null}
        // The picker's own reason slot, not a second status line beneath it: the default
        // wording is move/copy's ("These items are already here"), which says nothing about
        // why a table cannot be built here.
        currentParentMessage={CREATE_TABLE_AT_ROOT_REFUSAL}
        confirmLabel="Choose this folder"
        // Nothing runs from this dialog — it hands the folder to the name prompt, which owns
        // the enqueue and its own busy state.
        busyLabel="Loading…"
        onTargetChange={handleTargetChange}
        onConfirm={(destPrefix) =>
          onChoose({
            spaceKind: space.kind,
            bucket: space.bucket,
            // The space's database IS its root segment in both kinds: the username for a
            // personal space, the space name for a shared one.
            database: space.rootPrefix.replace(/\/$/, ''),
            prefix: destPrefix,
            rootPrefix: space.rootPrefix
          })
        }
        onCancel={onCancel}
      />
    </Modal>
  );
}
