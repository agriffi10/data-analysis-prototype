import {useRef, useState} from 'react';
import {validateFolderName} from './fileBrowser.service';
import {FormDialog} from '../../components/FormDialog';
import {Input} from '../../components/Input';

type Props = {
  onCreate: (name: string) => void;
  onCancel: () => void;
};

// Prompt for a new folder name with client-side validation (the
// same rules the service enforces) before any request is issued. Chrome, focus and
// Enter-to-submit come from FormDialog; Escape cancels via Modal.
export function CreateFolderDialog({onCreate, onCancel}: Props) {
  const [name, setName] = useState('');
  const [touched, setTouched] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const validationError = validateFolderName(name);
  const showError = touched && validationError !== null;

  function submit() {
    setTouched(true);
    if (validateFolderName(name) === null) onCreate(name);
  }

  return (
    <FormDialog
      title="New folder"
      ariaLabel="Create folder"
      submitLabel="Create"
      autoFocusRef={inputRef}
      onSubmit={submit}
      onCancel={onCancel}>
      <div className="mt-4">
        <Input
          id="new-folder-name"
          ref={inputRef}
          label="Folder name"
          required
          aria-required="true"
          value={name}
          error={showError ? validationError : null}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => setTouched(true)}
        />
      </div>
    </FormDialog>
  );
}
