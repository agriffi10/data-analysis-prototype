import { useRef, useState } from 'react';

type Props = {
  onFile: (file: File) => void;
  progress: number | null; // 0..100 while uploading, else null
  disabled?: boolean;
};

// SPEC-016 FR-001/FR-002: a single-file picker + drag-and-drop drop zone, with a
// live progress bar/percentage while the file uploads. Multi-file queue is SPEC-020.
export function UploadDropzone({ onFile, progress, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const uploading = progress !== null;

  function pickFirst(files: FileList | null) {
    if (files && files.length > 0) onFile(files[0]);
  }

  // Container color treatment by state (idle / drag-over / uploading).
  const containerState = uploading
    ? 'border-solid border-accent bg-accent-soft'
    : dragOver
      ? 'border-accent bg-accent-soft'
      : 'border-border bg-surface-2';
  const iconColor = dragOver || uploading ? 'text-accent' : 'text-text-3';

  return (
    <div
      className={`mb-4 rounded-lg border-2 border-dashed p-8 text-center transition-colors duration-150 ${containerState} ${
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
        if (!disabled && !uploading) pickFirst(e.dataTransfer.files);
      }}
    >
      <svg
        viewBox="0 0 32 32"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={`mx-auto h-8 w-8 ${iconColor}`}
        aria-hidden="true"
      >
        <circle cx="16" cy="16" r="13" />
        <path strokeLinecap="round" strokeLinejoin="round" d="M16 21v-9m0 0l-3 3m3-3l3 3" />
      </svg>

      {uploading ? (
        <div aria-live="polite">
          <p className="mt-3 text-sm font-medium text-text">
            Uploading… {progress}%
          </p>
          <div
            className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-border"
            role="progressbar"
            aria-valuenow={progress ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full rounded-full bg-accent transition-[width] duration-200"
              style={{ width: `${progress ?? 0}%` }}
            />
          </div>
        </div>
      ) : (
        <>
          <p className="mt-3 text-sm font-medium text-text">Drag a file here</p>
          <p className="mt-1 text-sm text-text-2">
            or{' '}
            <button
              type="button"
              className="font-medium text-accent-text hover:underline disabled:cursor-not-allowed disabled:opacity-45"
              onClick={() => inputRef.current?.click()}
              disabled={disabled}
            >
              choose a file
            </button>
          </p>
          <p className="mt-2 text-xs text-text-3">
            Up to 5 GB per file · multipart handled automatically
          </p>
          <input
            ref={inputRef}
            type="file"
            className="sr-only"
            aria-label="Upload file"
            disabled={disabled}
            onChange={(e) => {
              pickFirst(e.target.files);
              e.target.value = ''; // allow re-selecting the same file
            }}
          />
        </>
      )}
    </div>
  );
}
