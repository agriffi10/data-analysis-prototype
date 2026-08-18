import {useRef, useState} from 'react';

type Props = {
  onFiles: (files: File[]) => void; // enqueue all selected/dropped files
  disabled?: boolean;
};

// SPEC-020 FR-003: a multi-file picker + drag-and-drop drop zone. Selecting or
// dropping any number of files enqueues them all onto the upload queue; per-file
// progress, status, and cancel live in the in-drawer uploads list (UploadList), not here
// (this is purely the "add files" surface). Upgrades SPEC-016's single-file zone.
export function UploadDropzone({onFiles, disabled}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  function emit(files: FileList | null) {
    if (files && files.length > 0) onFiles(Array.from(files));
  }

  const containerState = dragOver ? 'border-accent bg-accent-soft' : 'border-border bg-surface-2';
  const iconColor = dragOver ? 'text-accent' : 'text-text-3';

  return (
    <div
      className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors duration-150 ${containerState} ${
        disabled ? 'pointer-events-none opacity-60' : ''
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        if (!disabled) emit(e.dataTransfer.files);
      }}>
      <svg
        viewBox="0 0 32 32"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={`mx-auto h-8 w-8 ${iconColor}`}
        aria-hidden="true">
        <circle
          cx="16"
          cy="16"
          r="13"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M16 21v-9m0 0l-3 3m3-3l3 3"
        />
      </svg>

      <p className="mt-3 text-sm font-medium text-text">Drag files here</p>
      <p className="mt-1 text-sm text-text-2">
        or{' '}
        <button
          type="button"
          className="font-medium text-accent-text hover:underline disabled:cursor-not-allowed disabled:opacity-45"
          onClick={() => inputRef.current?.click()}
          disabled={disabled}>
          choose files
        </button>
      </p>
      <p className="mt-2 text-xs text-text-3">Up to 5 GB per file · multipart handled automatically</p>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="sr-only"
        aria-label="Choose files"
        disabled={disabled}
        onChange={(e) => {
          emit(e.target.files);
          e.target.value = ''; // allow re-selecting the same file(s)
        }}
      />
    </div>
  );
}
