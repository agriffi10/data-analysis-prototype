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

  return (
    <div
      className={`mb-4 rounded-lg border-2 border-dashed p-4 text-center text-sm transition-colors ${
        dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300'
      } ${disabled ? 'opacity-60' : ''}`}
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
      {uploading ? (
        <div aria-live="polite">
          <p className="mb-2 text-gray-600">Uploading… {progress}%</p>
          <div
            className="h-2 w-full overflow-hidden rounded bg-gray-200"
            role="progressbar"
            aria-valuenow={progress ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <div
              className="h-full bg-blue-600 transition-[width]"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      ) : (
        <>
          <p className="text-gray-500">
            Drag a file here, or{' '}
            <button
              type="button"
              className="font-medium text-blue-600 hover:underline disabled:opacity-50"
              onClick={() => inputRef.current?.click()}
              disabled={disabled}
            >
              choose a file
            </button>
            .
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
