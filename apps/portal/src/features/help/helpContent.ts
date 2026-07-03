import type {HelpSection} from './help.types';

// SPEC-074 FR-005 — MAINTENANCE NOTE.
// This content describes only the portal behavior that is shipped and reachable
// by users as of implementation (2026-07-03): Files (incl. Table Builder),
// Query, Shared connections (incl. SPEC-073 pending/active join status), and
// Notifications. Every step below maps to a real, wired affordance in the code.
// When a feature is added, changed, or removed, revisit this file so the guides
// never promise behavior that isn't shipped — the post-spec ritual in
// docs/process.md includes a check for exactly this.

/** The authored Help & guides sections, in sidebar order (FR-003/005). */
export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'files',
    label: 'Files',
    subtitle: 'Uploading, organizing, and managing your files.',
    icon: 'files',
    guides: [
      {
        id: 'upload-files',
        title: 'Upload files',
        subtitle: 'Add files to a folder from your computer.',
        steps: [
          'Open the <b>Files</b> tab and browse to the folder you want to upload into.',
          'Click <b>Upload</b> to open the upload panel.',
          'Drag files onto the drop zone, or click it to pick files from your computer.',
          'Each file uploads into the current folder; the panel tracks its progress.'
        ],
        callout: {
          kind: 'tip',
          text: 'If a file with the same name already exists, you can <b>Overwrite</b> it or keep both — the app offers an automatically numbered name.'
        }
      },
      {
        id: 'create-folders',
        title: 'Create and use folders',
        subtitle: 'Keep your files organized in folders.',
        steps: [
          'In the <b>Files</b> tab, click <b>New folder</b>.',
          'Enter a <b>Folder name</b> — no slashes, and no leading or trailing spaces.',
          'Click <b>Create</b>.',
          'Open a folder by clicking its row; use the breadcrumbs above the list to move back up.'
        ]
      },
      {
        id: 'download-files',
        title: 'Download files',
        subtitle: 'Save a file to your computer.',
        steps: [
          'In the <b>Files</b> tab, select the file you want.',
          'Click <b>Download</b> to save it locally.',
          'Or just <b>double-click the file row</b> to download it right away.'
        ]
      },
      {
        id: 'rename-move-copy-delete',
        title: 'Rename, move, copy, or delete',
        subtitle: 'Reorganize files and folders after uploading.',
        steps: [
          'Tick the checkbox on one or more items — a toolbar of actions appears.',
          'Choose <b>Rename</b>, <b>Move</b>, <b>Copy</b>, or <b>Delete</b>.',
          'For <b>Move</b> or <b>Copy</b>, pick a destination folder, then confirm with <b>Move here</b> or <b>Copy here</b>.',
          'For <b>Rename</b>, type a <b>New name</b> — a file keeps its original extension.'
        ],
        callout: {
          kind: 'warning',
          text: "Deletes can't be undone — there's no version history, so a deleted file or folder is gone for good. The confirm dialog starts on <b>Cancel</b> to protect you."
        }
      },
      {
        id: 'file-details',
        title: 'View file details',
        subtitle: 'Inspect name, path, size, type, and metadata.',
        steps: [
          'Click <b>Details</b> on any file or folder row.',
          'The panel shows its name and paths, and — for files — size, type, last modified, and any custom metadata.',
          'Use the copy buttons to copy a path; close with <b>Escape</b> or the close button.'
        ]
      },
      {
        id: 'create-table',
        title: 'Create a table from a folder',
        subtitle: 'Turn a folder of files into a table you can query.',
        steps: [
          'In the <b>Files</b> tab, open the folder whose files you want to query, then click <b>Create table</b>.',
          'Enter a <b>Table name</b> (lowercase letters, digits, or underscores, starting with a letter).',
          'If your files sit in <b>key=value</b> folders (e.g. <b>year=2026/month=01/</b>), click <b>Add partition keys</b> and declare each key in order — coarsest first — with its type and range.',
          "Click <b>Create table</b>. It's built in the background; you'll be notified when it's ready or if it couldn't be created."
        ],
        callout: {
          kind: 'tip',
          text: 'Once ready, the table appears in the <b>Query</b> tab under the same space, ready to query.'
        }
      }
    ]
  },
  {
    id: 'query',
    label: 'Query',
    subtitle: 'Running SQL and exploring your data.',
    icon: 'query',
    guides: [
      {
        id: 'run-query',
        title: 'Write and run a query',
        subtitle: 'Run SQL against your tables.',
        steps: [
          'Open the <b>Query</b> tab and type SQL in the editor.',
          'Click <b>Run</b>, or press <kbd>Ctrl/Cmd + Enter</kbd>.',
          'The status bar shows progress, the exact total row count, data scanned, and how long it took.',
          'To stop a long-running query, click <b>Stop</b>.'
        ]
      },
      {
        id: 'browse-databases',
        title: 'Browse databases and query across them',
        subtitle: 'Explore every database you can access and join across them.',
        steps: [
          'The schema rail on the left lists every database you can access — your personal database (named after your username) and any shared spaces you belong to.',
          'Expand a database to inspect its tables and columns.',
          'Created a table elsewhere (or a teammate did)? Click the <b>Refresh</b> icon on that database to re-read its tables and views without reloading the page.',
          'Need more room? <b>Collapse the side panel</b> with the chevron in its header; a small handle at the edge brings it back. The choice is remembered across the Files and Query pages.',
          'Reference each table by its full name, <b>database.table</b> (e.g. <b>mydb.orders</b>). There is no “current” database, so you can read from — and join across — any databases you have access to in a single query.'
        ],
        callout: {
          kind: 'tip',
          text: 'Because there’s no active database, an unqualified name like <b>orders</b> won’t resolve — always write <b>database.table</b>.'
        }
      },
      {
        id: 'save-query',
        title: 'Save a query',
        subtitle: 'Keep queries you run often.',
        steps: [
          'With a valid query in the editor, click <b>Save</b>.',
          'Give it a <b>Name</b> and click <b>Save</b> — re-saving updates it in place.',
          'A marker on the tab shows when your edits have drifted from the saved copy.'
        ]
      },
      {
        id: 'query-history',
        title: 'Review query history',
        subtitle: 'Find and rerun something from earlier.',
        steps: [
          'Open the history panel to see your past runs, newest first.',
          'Each entry shows the query, its status, duration, and data scanned.',
          'Click one to load it into a new tab and run it again.'
        ]
      },
      {
        id: 'work-with-results',
        title: 'Work with results',
        subtitle: 'Read and page through query output.',
        steps: [
          'After a query succeeds, results appear in a table below the editor.',
          "Drag a column's edge to resize it — widths are remembered as you switch tabs.",
          'Use <b>Prev</b> and <b>Next</b> to page through large result sets.'
        ]
      },
      {
        id: 'save-results',
        title: 'Save results to your files',
        subtitle: 'Export a result set back into your files.',
        steps: [
          'After a successful query, click <b>Save results to my files</b> in the status bar.',
          'Choose a destination space and a file name.',
          'The results export in the background; a notification confirms when they are saved.'
        ]
      }
    ]
  },
  {
    id: 'shared-connections',
    label: 'Shared connections',
    subtitle: 'Creating and managing spaces you share with others.',
    icon: 'connections',
    guides: [
      {
        id: 'create-shared-connection',
        title: 'Create a shared connection',
        subtitle: 'Make a space several people can share.',
        steps: [
          'On the <b>Connections</b> tab, click <b>Create</b>.',
          'Enter a <b>Connection name</b> (lowercase letters, digits, or underscores, starting with a letter).',
          "Click <b>Create</b>. It's set up in the background and appears in your list when ready."
        ],
        callout: {
          kind: 'tip',
          text: "The name is permanent and must be unique across all spaces — it can't be renamed later. You start the space alone; add people afterwards with <b>Add members</b>."
        }
      },
      {
        id: 'add-members',
        title: 'Add members',
        subtitle: 'Give other people access to a space you own.',
        steps: [
          'Open <b>Manage</b> on a space you own, then click <b>Add members</b>.',
          'Enter one or more <b>Usernames</b>, separated by spaces, commas, or new lines.',
          'Click <b>Add</b>. Members get access to the same shared files and tables; unknown usernames are ignored.'
        ]
      },
      {
        id: 'member-status',
        title: 'See who has access and their status',
        subtitle: 'Check the member list and each person’s join status.',
        steps: [
          'If you own the space, open <b>Manage</b>; if you belong to it, open <b>View members</b> — either shows the full member list (read-only for members).',
          'Each member shows a status: <b>Active</b> once they have signed in and opened the space, or <b>Pending</b> until they do.',
          'Click <b>Refresh</b> to check for updates.'
        ],
        callout: {
          kind: 'tip',
          text: 'Pending vs Active only reflects whether the person has opened the space yet — access is granted the moment you add them.'
        }
      },
      {
        id: 'remove-members',
        title: 'Remove a member',
        subtitle: 'Revoke someone’s access to a space you own.',
        steps: [
          'In the <b>Manage</b> member list, click <b>Remove</b> next to a member and confirm.',
          "They lose access, but the shared files and tables aren't deleted. The owner can't be removed."
        ]
      },
      {
        id: 'leave-space',
        title: 'Leave a space',
        subtitle: 'Step out of a space you belong to.',
        steps: [
          "On a space you belong to but don't own, choose <b>Leave</b> and confirm.",
          'You lose access; everyone else keeps theirs and nothing is deleted.'
        ]
      },
      {
        id: 'delete-space',
        title: 'Delete a space',
        subtitle: 'Permanently remove a space you own.',
        steps: [
          'On a space you own, choose <b>Delete</b>.',
          "Type the space's name to confirm, then click <b>Delete</b>."
        ],
        callout: {
          kind: 'warning',
          text: "This permanently deletes the space for everyone — all of its files, all of its tables, the database, and every member's access. It can't be undone."
        }
      }
    ]
  },
  {
    id: 'notifications',
    label: 'Notifications',
    subtitle: 'Staying on top of activity in the portal.',
    icon: 'notifications',
    guides: [
      {
        id: 'find-notifications',
        title: 'Find your notifications',
        subtitle: 'Know when something needs your attention.',
        steps: [
          'Look for the <b>bell</b> in the top bar.',
          'A number on the bell shows how many unread notifications you have.',
          'Click it to open your notifications.'
        ]
      },
      {
        id: 'read-notifications',
        title: 'Read your notifications',
        subtitle: 'Browse your full notification history.',
        steps: [
          'The <b>Notifications</b> page lists them newest first, 10 per page.',
          'Switch between <b>All</b> and <b>Unread</b>, and use <b>Prev</b> / <b>Next</b> to page.',
          'Click <b>Refresh</b> to check for new ones. Notifications cover your shared spaces and background jobs such as table builds.'
        ]
      },
      {
        id: 'mark-read',
        title: 'Mark notifications as read',
        subtitle: 'Clear the unread indicator.',
        steps: [
          'Click <b>Mark read</b> on a single notification, or <b>Mark all read</b> to clear them all.',
          'The unread count on the bell updates right away.'
        ],
        callout: {
          kind: 'tip',
          text: 'Notifications can’t be deleted — reading one just clears its unread marker.'
        }
      }
    ]
  }
];
