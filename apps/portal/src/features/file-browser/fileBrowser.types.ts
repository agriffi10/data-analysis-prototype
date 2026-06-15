// Feature-scoped types for the file browser (SPEC-015).

export type DownloadUrl = {
  url: string; // presigned GetObject URL
  expiresAt: string; // ISO timestamp the URL stops working
};
