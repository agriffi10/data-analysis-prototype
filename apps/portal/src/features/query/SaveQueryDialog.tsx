import {useRef, useState} from 'react';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';
import {ConfirmDialog} from '../../components/ConfirmDialog';
import type {SavedQuery} from './query.types';

type Props = {
  /** '' for a new save; the saved query's name on re-save. */
  initialName: string;
  /** Used to detect name collisions. */
  savedQueries: SavedQuery[];
  /** Active tab's savedQueryId (its own name isn't a collision). */
  linkedId?: string;
  /** `targetId` is the saved query id to write into — null = create a new one. */
  onSave: (result: {name: string; targetId: string | null}) => void;
  onCancel: () => void;
};

/**
 * Name-prompt modal with an inline overwrite-confirm step. New save → empty;
 * re-save → pre-filled. Saving under a name owned by a *different* saved query
 * asks to replace it; re-saving under the tab's own name is the normal
 * in-place update.
 */
export function SaveQueryDialog({initialName, savedQueries, linkedId, onSave, onCancel}: Props) {
  const [name, setName] = useState(initialName);
  const [collision, setCollision] = useState<SavedQuery | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const trimmed = name.trim();
  const canSave = trimmed.length > 0;

  const attemptSave = () => {
    if (!canSave) return;
    const existing = savedQueries.find((q) => q.name.toLowerCase() === trimmed.toLowerCase());
    // A name owned by a *different* saved query → confirm overwrite.
    if (existing && existing.id !== linkedId) {
      setCollision(existing);
      return;
    }
    // Re-save in place (own name) or brand-new name.
    onSave({name: trimmed, targetId: linkedId ?? null});
  };

  if (collision) {
    return (
      <ConfirmDialog
        title={`Replace “${collision.name}”?`}
        ariaLabel="Confirm replace saved query"
        confirmLabel="Replace"
        confirmVariant="danger"
        onConfirm={() => onSave({name: trimmed, targetId: collision.id})}
        onCancel={() => setCollision(null)}>
        <p className="mt-3 text-sm text-text-2">
          A saved query named “{collision.name}” already exists. Saving will replace it with the current SQL.
        </p>
      </ConfirmDialog>
    );
  }

  return (
    <FormDialog
      title="Save query"
      ariaLabel="Save query"
      submitLabel="Save"
      submitDisabled={!canSave}
      autoFocusRef={inputRef}
      autoFocusSelect
      onSubmit={attemptSave}
      onCancel={onCancel}>
      {/* `mt-3` reproduces the gap the old markup got from an `mb-3` on the heading. */}
      <div className="mt-3">
        <Input
          ref={inputRef}
          id="saved-query-name"
          label="Name"
          required
          aria-required="true"
          value={name}
          placeholder="e.g. Monthly revenue"
          onChange={(e) => setName(e.target.value)}
        />
      </div>
    </FormDialog>
  );
}
