/** The space a send reads from — the sender's own, or a shared space they belong to. */
export type SendSourceSpace = {
  kind: 'personal' | 'shared';
  /** The username for a personal space, the space name for a shared one. */
  name: string;
};

/** One selected file or folder. `key` is the full S3 key, exactly as the browser lists it. */
export type SendItem = {
  kind: 'file' | 'folder';
  key: string;
};

/** Who receives the files. A space needs no membership — the control plane does the write. */
export type SendRecipient = {
  kind: 'user' | 'space';
  name: string;
};

/** A send request, as the browser enqueues it. */
export type FileSendRequest = {
  /** Client-minted id; it is also the FIFO deduplication id, so it must be per-submit. */
  requestId: string;
  space: SendSourceSpace;
  items: SendItem[];
  recipients: SendRecipient[];
};
