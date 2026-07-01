import {useEffect, useRef} from 'react';
import {Input} from '../../components/Input';
import {Button} from '../../components/Button';
import {emptyDraftKey, type DraftPartitionKey, type PartitionKeyErrors, type PartitionType} from './partitionKeys';

// SPEC-071 FR-002: the optional, ordered partition-keys editor. Controlled — the
// dialog owns the draft rows (so it can compute validity + the wire keys) and the
// per-row `errors`; this component renders + edits them and manages focus on
// add/remove (accessibility rulebook: labelled dynamic rows). An empty list means a
// flat (unpartitioned) table — no keys are sent.

type Props = {
  value: DraftPartitionKey[];
  errors: PartitionKeyErrors[]; // index-aligned with `value`
  disabled?: boolean;
  onChange: (rows: DraftPartitionKey[]) => void;
};

const selectClass =
  'h-9 w-full rounded-md border border-border bg-surface px-3 text-base text-text focus-visible:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-45';

export function PartitionKeysField({value, errors, disabled = false, onChange}: Props) {
  // Name inputs by row id, so we can move focus to a specific row after add/remove.
  const nameRefs = useRef(new Map<string, HTMLInputElement>());
  const addBtnRef = useRef<HTMLButtonElement>(null);
  // What to focus after the next render: a row id, or 'add' for the top affordance.
  const pendingFocus = useRef<string | null>(null);

  useEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    if (target === 'add') addBtnRef.current?.focus();
    else nameRefs.current.get(target)?.focus();
  });

  const update = (id: string, patch: Partial<DraftPartitionKey>) =>
    onChange(value.map((r) => (r.id === id ? {...r, ...patch} : r)));

  const addKey = () => {
    const row = emptyDraftKey();
    pendingFocus.current = row.id;
    onChange([...value, row]);
  };

  const removeKey = (id: string) => {
    const idx = value.findIndex((r) => r.id === id);
    const next = value.filter((r) => r.id !== id);
    nameRefs.current.delete(id);
    // Move focus to the nearest remaining row's name, else back to the Add button.
    pendingFocus.current = next.length === 0 ? 'add' : (next[idx] ?? next[idx - 1]).id;
    onChange(next);
  };

  const move = (id: string, dir: -1 | 1) => {
    const idx = value.findIndex((r) => r.id === id);
    const to = idx + dir;
    if (to < 0 || to >= value.length) return;
    const next = [...value];
    [next[idx], next[to]] = [next[to], next[idx]];
    onChange(next);
  };

  if (value.length === 0) {
    return (
      <div className="mt-4">
        <Button
          ref={addBtnRef}
          type="button"
          variant="default"
          size="sm"
          disabled={disabled}
          onClick={addKey}>
          Add partition keys
        </Button>
        <p className="mt-1.5 text-xs text-text-3">
          Optional — only if your files are organized in <code>key=value/</code> folders (e.g.{' '}
          <code>year=2026/month=01/</code>).
        </p>
      </div>
    );
  }

  return (
    <fieldset className="mt-4">
      <legend className="text-sm font-medium text-text">Partition keys</legend>
      <p className="mt-1 mb-3 text-xs text-text-3">
        List keys in <strong>granularity order, coarsest first</strong> (e.g. year, then month, then day). A value
        outside a declared integer/date range is excluded from query results, so set ranges wide enough.
      </p>

      <ol className="flex flex-col gap-3">
        {value.map((row, i) => {
          const err = errors[i] ?? {};
          return (
            <li key={row.id}>
              <div
                role="group"
                aria-label={`Partition key ${i + 1}`}
                className="rounded-md border border-border bg-surface-2 p-3">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <Input
                      ref={(el) => {
                        if (el) nameRefs.current.set(row.id, el);
                        else nameRefs.current.delete(row.id);
                      }}
                      aria-label={`Partition key ${i + 1} name`}
                      placeholder="key name (e.g. year)"
                      value={row.name}
                      error={err.name}
                      disabled={disabled}
                      onChange={(e) => update(row.id, {name: e.target.value})}
                    />
                  </div>
                  <div className="flex shrink-0 items-center gap-1 pt-0.5">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Move partition key ${i + 1} earlier`}
                      disabled={disabled || i === 0}
                      onClick={() => move(row.id, -1)}>
                      ↑
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Move partition key ${i + 1} later`}
                      disabled={disabled || i === value.length - 1}
                      onClick={() => move(row.id, 1)}>
                      ↓
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="!text-danger hover:!bg-danger-soft hover:!text-danger"
                      aria-label={`Remove partition key ${i + 1}`}
                      disabled={disabled}
                      onClick={() => removeKey(row.id)}>
                      Remove
                    </Button>
                  </div>
                </div>

                <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div>
                    <label
                      htmlFor={`${row.id}-type`}
                      className="mb-1.5 block text-sm font-medium text-text">
                      Type
                    </label>
                    <select
                      id={`${row.id}-type`}
                      value={row.type}
                      disabled={disabled}
                      className={selectClass}
                      onChange={(e) => update(row.id, {type: e.target.value as PartitionType})}>
                      <option value="integer">Integer</option>
                      <option value="date">Date</option>
                      <option value="string">String</option>
                    </select>
                  </div>

                  {row.type === 'integer' && (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        <Input
                          aria-label={`Partition key ${i + 1} minimum`}
                          label="Min"
                          inputMode="numeric"
                          placeholder="0"
                          value={row.min}
                          error={err.min}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {min: e.target.value})}
                        />
                        <Input
                          aria-label={`Partition key ${i + 1} maximum`}
                          label="Max"
                          inputMode="numeric"
                          placeholder="2026"
                          value={row.max}
                          error={err.max}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {max: e.target.value})}
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <Input
                          aria-label={`Partition key ${i + 1} digit width`}
                          label="Digits (optional zero-pad, e.g. 2 for 01)"
                          inputMode="numeric"
                          placeholder="—"
                          value={row.digits}
                          error={err.digits}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {digits: e.target.value})}
                        />
                      </div>
                    </>
                  )}

                  {row.type === 'date' && (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        <Input
                          aria-label={`Partition key ${i + 1} range start`}
                          label="Range start"
                          placeholder="2020-01-01"
                          value={row.start}
                          error={err.start}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {start: e.target.value})}
                        />
                        <Input
                          aria-label={`Partition key ${i + 1} range end`}
                          label="Range end (NOW allowed)"
                          placeholder="NOW"
                          value={row.end}
                          error={err.end}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {end: e.target.value})}
                        />
                      </div>
                      <div className="sm:col-span-2">
                        <Input
                          aria-label={`Partition key ${i + 1} date format`}
                          label="Format"
                          placeholder="yyyy-MM-dd"
                          value={row.format}
                          error={err.format}
                          disabled={disabled}
                          onChange={(e) => update(row.id, {format: e.target.value})}
                        />
                      </div>
                    </>
                  )}

                  {row.type === 'string' && (
                    <div className="sm:col-span-2">
                      <Input
                        aria-label={`Partition key ${i + 1} values`}
                        label="Values (comma-separated)"
                        placeholder="us, eu, apac"
                        value={row.values}
                        error={err.values}
                        disabled={disabled}
                        onChange={(e) => update(row.id, {values: e.target.value})}
                      />
                    </div>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      <Button
        ref={addBtnRef}
        type="button"
        variant="default"
        size="sm"
        className="mt-3"
        disabled={disabled}
        onClick={addKey}>
        Add another key
      </Button>
    </fieldset>
  );
}
