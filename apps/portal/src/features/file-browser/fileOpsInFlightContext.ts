import {createContext, useContext} from 'react';
import {FILE_OPS_MACHINE_TIMEOUT_SECONDS} from './fileOps.constants';
import type {FileOpSpace, InFlightOperation} from './fileOps.types';

export type FileOpsInFlightContextValue = {
  /** Everything this session has handed to the plane, newest first. */
  operations: InFlightOperation[];
  add: (operation: InFlightOperation) => void;
  dismiss: (requestId: string) => void;
  /**
   * Is an operation from THIS session still open against this space?
   *
   * Answers for a source OR a destination, because a cross-space copy or move takes both locks.
   */
  busySpace: (space: FileOpSpace) => boolean;
};

/** The session's in-flight file operations; provided by `FileOpsInFlightProvider`. */
export const FileOpsInFlightContext = createContext<FileOpsInFlightContextValue | null>(null);

/**
 * The session's in-flight file operations.
 *
 * @returns The store.
 * @throws Outside {@link FileOpsInFlightProvider}, which is mounted at the app shell.
 */
export function useFileOpsInFlight(): FileOpsInFlightContextValue {
  const value = useContext(FileOpsInFlightContext);
  if (!value) throw new Error('useFileOpsInFlight must be used within FileOpsInFlightProvider');
  return value;
}

/** Two spaces are the same space when both halves match — a name alone spans two buckets. */
export function sameSpace(a: FileOpSpace, b: FileOpSpace): boolean {
  return a.kind === b.kind && a.name === b.name;
}

/**
 * Is this entry still waiting on the plane?
 *
 * Age is checked as well as state so the gate is right the instant it is asked, rather than at
 * whatever point a timer happens to fire. The timer exists to re-render the surface; this is
 * what decides.
 *
 * @param operation - The entry.
 * @param now - Milliseconds since the epoch.
 * @returns True while the entry is unsettled and inside the machine's own ceiling.
 */
export function isOpen(operation: InFlightOperation, now: number): boolean {
  if (operation.state !== 'submitted') return false;
  return now - Date.parse(operation.submittedAt) < FILE_OPS_MACHINE_TIMEOUT_SECONDS * 1000;
}
