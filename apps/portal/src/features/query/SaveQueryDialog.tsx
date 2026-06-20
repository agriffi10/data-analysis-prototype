import { useEffect, useRef, useState } from 'react';
import { Button } from '../../components/Button';
import { Input } from '../../components/Input';
import type { SavedQuery } from './query.types';

type Props = {
  initialName: string; // '' for a new save; the saved query's name on re-save
  savedQueries: SavedQuery[]; // to detect name collisions
  linkedId?: string; // active tab's savedQueryId (its own name isn't a collision)
  // targetId: the saved query id to write into — null = create a new one.
  onSave: (result: { name: string; targetId: string | null }) => void;
  onCancel: () => void;
};

// SPEC-043 FR-001/002/003: name-prompt modal (SPEC-026 pattern) with an inline
// overwrite-confirm step. New save → empty; re-save → pre-filled. Saving under a
// name owned by a *different* saved query asks to replace it; re-saving under the
// tab's own name is the normal in-place update.
export function SaveQueryDialog({
  initialName,
  savedQueries,
  linkedId,
  onSave,
  onCancel,
}: Props) {
  const [name, setName] = useState(initialName);
  const [collision, setCollision] = useState<SavedQuery | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel();
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const trimmed = name.trim();
  const canSave = trimmed.length > 0;

  const attemptSave = () => {
    if (!canSave) return;
    const existing = savedQueries.find(
      (q) => q.name.toLowerCase() === trimmed.toLowerCase(),
    );
    // A name owned by a *different* saved query → confirm overwrite (FR-003).
    if (existing && existing.id !== linkedId) {
      setCollision(existing);
      return;
    }
    // Re-save in place (own name) or brand-new name.
    onSave({ name: trimmed, targetId: linkedId ?? null });
  };

  const confirmOverwrite = () => {
    if (!collision) return;
    onSave({ name: trimmed, targetId: collision.id });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        role={collision ? 'alertdialog' : 'dialog'}
        aria-modal="true"
        aria-label={collision ? 'Confirm replace saved query' : 'Save query'}
        className="w-full max-w-md rounded-lg bg-surface shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        {collision ? (
          <>
            <div className="px-5 pb-4 pt-5">
              <h2 className="text-md font-semibold text-text">
                Replace “{collision.name}”?
              </h2>
              <p className="mt-3 text-sm text-text-2">
                A saved query named “{collision.name}” already exists. Saving will
                replace it with the current SQL.
              </p>
            </div>
            <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
              <Button variant="ghost" onClick={() => setCollision(null)}>
                Cancel
              </Button>
              <Button variant="danger" onClick={confirmOverwrite}>
                Replace
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="px-5 pb-4 pt-5">
              <h2 className="mb-3 text-md font-semibold text-text">
                {linkedId ? 'Save query' : 'Save query'}
              </h2>
              <Input
                ref={inputRef}
                id="saved-query-name"
                label="Name"
                value={name}
                placeholder="e.g. Monthly revenue"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    attemptSave();
                  }
                }}
              />
            </div>
            <div className="flex justify-end gap-2 rounded-b-lg border-t border-border bg-surface-2 px-5 py-4">
              <Button variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
              <Button variant="primary" onClick={attemptSave} disabled={!canSave}>
                Save
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
