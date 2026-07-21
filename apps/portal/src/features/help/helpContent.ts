import type {HelpSection} from './help.types';

// SPEC-074 FR-005 — MAINTENANCE NOTE.
// This content describes only the portal behavior that is shipped and reachable
// by users as of implementation: Files (incl. running a data-quality check and
// reading its report, SPEC-113/114), Query, Tables (create-from-folder + share,
// SPEC-066→072 / 088→094), Shared connections (incl. SPEC-073 pending/active
// join status), and Notifications. Every step below maps to a real, wired
// affordance in the code.
//
// The data-quality guides now cover the whole loop: starting a check from EITHER
// entry point (Files, or Data quality → New quality check — SPEC-124), the
// notification that reports it, the report itself, and (SPEC-123) browsing past
// checks from the Data quality tab. Since SPEC-126 drains every control plane's
// request DLQ back into notifications, the guides may now say a failure ALWAYS
// reports itself there — they hedged with "usually" until that shipped, because a
// request that never started an execution notified nobody.
// When a feature is added, changed, or removed, revisit this file so the guides
// never promise behavior that isn't shipped — the post-spec ritual in
// docs/process.md includes a check for exactly this.

/** The authored Help & guides sections, in sidebar order (FR-003/005). */
export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'files',
    label: 'Files',
    subtitle: 'Your own private space to upload, organize, and manage files.',
    icon: 'files',
    guides: [
      {
        id: 'upload-files',
        title: 'Upload files',
        subtitle: 'Add files to a folder from your computer.',
        intro:
          'Everything starts here — getting your files into the portal. Uploads always land in the folder you’re currently viewing, so browse to where you want them first, then drop them in. Big files are welcome; the panel keeps you posted on each one.',
        steps: [
          'Open the <b>Files</b> tab and browse to the folder you want to upload into.',
          'Click <b>Upload</b> to open the upload panel.',
          'Drag files onto the drop zone, or click it to pick files from your computer.',
          'Each file uploads into the current folder, and the panel tracks its progress until it’s done.'
        ],
        callout: {
          kind: 'tip',
          text: 'Uploading something that shares a name with an existing file? You choose what happens: <b>Overwrite</b> the old one, or keep both — the app suggests an automatically numbered name so nothing is lost.'
        }
      },
      {
        id: 'create-folders',
        title: 'Create and use folders',
        subtitle: 'Keep your files organized in folders.',
        intro:
          'Folders work just like they do on your computer — they’re how you keep things tidy as your files grow. You can nest them as deep as you like, and the breadcrumbs at the top always show where you are.',
        steps: [
          'In the <b>Files</b> tab, click <b>New folder</b>.',
          'Enter a <b>Folder name</b> — no slashes, and no leading or trailing spaces.',
          'Click <b>Create</b>, and the new folder appears in the list.',
          'Open a folder by clicking its row; use the breadcrumbs above the list — or the <b>..</b> row at the top of a subfolder — to step back up the tree.'
        ]
      },
      {
        id: 'download-files',
        title: 'Download files',
        subtitle: 'Save a file back to your computer.',
        intro: 'When you need a file back on your own machine, downloading takes just a click — or a double-click.',
        steps: [
          'In the <b>Files</b> tab, click <b>Details</b> on the file, then <b>Download</b> to save it locally.',
          'In a hurry? Just <b>double-click the file row</b> and it downloads right away.'
        ]
      },
      {
        id: 'rename-move-copy-delete',
        title: 'Rename, move, copy, or delete',
        subtitle: 'Reorganize files and folders after uploading.',
        intro:
          'Plans change, and so does how you want your files arranged. Tick items for a bulk toolbar, or open a single item’s details to rename it. These actions work on whole folders too, not just single files.',
        steps: [
          'Tick the checkbox on one or more items — a toolbar with <b>Copy</b>, <b>Move</b>, and <b>Delete</b> appears.',
          'For <b>Move</b> or <b>Copy</b>, pick a destination folder, then confirm with <b>Move here</b> or <b>Copy here</b>.',
          'To <b>Rename</b> a single item, click <b>Details</b> on its row and choose <b>Rename</b>, then type a <b>New name</b> — a file keeps its original extension automatically.'
        ],
        callout: {
          kind: 'warning',
          text: 'Deleting is forever — there’s no version history or trash, so a deleted file or folder is gone for good. To keep you safe, the confirm dialog starts on <b>Cancel</b>, so a stray Enter key won’t delete anything.'
        }
      },
      {
        id: 'file-details',
        title: 'View file details',
        subtitle: 'Inspect a file’s name, path, size, type, and metadata.',
        intro:
          'Sometimes you just need to know more about a file — exactly where it lives, how big it is, or what metadata it carries. The details panel gathers all of that in one place.',
        steps: [
          'Click <b>Details</b> on any file or folder row.',
          'The panel shows its name and paths, and — for files — size, type, last modified, and any custom metadata.',
          'From here you can also <b>Download</b> a file or <b>Rename</b> the item.',
          'Use the copy buttons to grab a path, and close the panel with <b>Escape</b> or the close button.'
        ]
      },
      {
        id: 'check-data-quality',
        title: 'Check data quality',
        subtitle: 'Find out what’s wrong with a data file — without changing it.',
        intro:
          'Before you build a table from a folder of CSVs, or after someone hands you an export you don’t trust, this tells you what’s actually in there: how many rows, whether a column that looks numeric has stray text in it, how much is blank, whether rows repeat, and — for a folder — whether every file agrees on the same columns. It only ever <b>reads</b> your data. Nothing is modified, moved, or deleted.',
        steps: [
          'There are two ways in. From <b>Files</b>: tick the checkbox on <b>one</b> file or <b>one</b> folder, then click <b>Check quality</b> in the toolbar above the list and confirm — the dialog names exactly what will be read.',
          'Or from <b>Data quality</b>: click <b>New quality check</b>, choose the space, then browse to the folder you want checked. Click a file first if you want to check just that one file.',
          'The check runs in the background and can take a few minutes. Carry on working; you don’t have to wait on the page.',
          'When it finishes you’ll get a <b>notification</b> with the result. Click it to open the full report.',
          'The report shows every finding: row and column counts, blank values, columns whose values don’t match their type, repeated rows, and — for a folder — any file whose columns disagree with the rest.'
        ],
        callout: {
          kind: 'tip',
          text: 'The check never guesses in your favour. Some figures are <b>estimates</b> and say so: ragged-row counts over-count rows with commas inside quotes, and on a large folder the text-encoding check reads a sample rather than every byte. A figure marked <b>Skipped</b> or <b>Not computed</b> is one the check couldn’t make — never a clean result.'
        }
      },
      {
        id: 'past-data-quality-checks',
        title: 'Find a past quality check',
        subtitle: 'Every check you’ve run, in one place — you don’t need to keep the notification.',
        intro:
          'The <b>Data quality</b> tab lists every check that finished, newest first, across your own space and any shared spaces you belong to. Click a row to reopen its full report. This is what makes a report safe to come back to: before, a report was reachable only from its notification, so clearing the notification effectively lost it.',
        steps: [
          'Open the <b>Data quality</b> tab.',
          'Use <b>All</b> / <b>Issues found</b> / <b>Clean</b> to narrow the list, and <b>Prev</b> / <b>Next</b> to page through it.',
          'Click any row to open that check’s full report.',
          'To run another, click <b>New quality check</b>. A check you’ve just started is <b>not</b> in this list yet — it appears once it finishes, which can take a few minutes.'
        ],
        callout: {
          kind: 'tip',
          text: 'A row tagged <b>Sampled</b> means some of that check’s figures are estimates rather than exact counts — open the report to see which. A check that <b>failed</b> has no row here, because it never produced a report; it always reports itself in your <b>notifications</b> instead — including a request that couldn’t be started at all.'
        }
      }
    ]
  },
  {
    id: 'query',
    label: 'Query',
    subtitle: 'Write SQL, explore your data, and share the results.',
    icon: 'query',
    guides: [
      {
        id: 'run-query',
        title: 'Write and run a query',
        subtitle: 'Run SQL against your tables.',
        intro:
          'The Query tab is a full SQL workspace over your data. Type a query, run it, and the results land right below the editor. The status bar keeps you informed the whole time — how far along the query is, how many rows came back, how much data it scanned, and how long it took.',
        steps: [
          'Open the <b>Query</b> tab and type SQL in the editor.',
          'Click <b>Run Statement</b>, or press <kbd>Ctrl/Cmd + Enter</kbd> — it runs your selection if you have one, otherwise the statement under the cursor.',
          'Watch the status bar for progress, the exact total row count, data scanned, and how long it took.',
          'Changed your mind mid-run? Click <b>Stop</b> to cancel a running query or script.'
        ]
      },
      {
        id: 'run-script',
        title: 'Run several statements at once',
        subtitle: 'Write a script of ;-separated statements and run it top to bottom.',
        intro:
          'You don’t have to run statements one at a time. Put several in the editor separated by semicolons — say, a <b>CREATE TABLE</b> followed by a <b>SELECT</b> — and the portal runs them in order, one after another. Each gets its own history entry, and you pick whether you want a single final result or one result per statement.',
        steps: [
          'Write multiple statements in one editor, separated by semicolons.',
          'Open the dropdown next to <b>Run Statement</b> to reach the two whole-script options.',
          'Choose <b>Run Query Tab</b> (<kbd>Ctrl/Cmd + Shift + Enter</kbd>) to run every statement in order and show the last result set.',
          'Or choose <b>Run Multiple Queries</b> (<kbd>Ctrl/Cmd + Alt + Enter</kbd>) to keep every statement’s result in its own tab above the results table.',
          'Statements run one at a time, in order. The status bar shows which one is running (for example “Statement 2 of 4”), and each gets its own history entry.',
          'If a statement fails, the script stops there — the error names the statement that failed, and the ones after it don’t run.'
        ],
        callout: {
          kind: 'warning',
          text: 'There are no transactions here: statements that already succeeded keep their effects — a table you created or dropped stays that way — even if a later statement fails.'
        }
      },
      {
        id: 'browse-databases',
        title: 'Browse databases and query across them',
        subtitle: 'Explore every database you can access and join across them.',
        intro:
          'The rail on the left is your map of everything you can query — your own personal database plus any shared spaces you belong to. Expand any database to see its tables and columns. There’s no “current” database to switch between, which means a single query can read from, and join across, any databases you have access to.',
        steps: [
          'The schema rail on the left lists every database you can access — your personal database (named after your username) and any shared spaces you belong to.',
          'Expand a database to inspect its tables and columns.',
          'Created a table elsewhere, or a teammate did? Click the <b>Refresh</b> icon on that database to re-read its tables and views without reloading the page.',
          'Short on space? <b>Collapse the side panel</b> with the chevron in its header; a small handle at the edge brings it back. Your choice is remembered across the Files and Query pages.',
          'Reference each table by its full name, <b>database.table</b> (for example <b>mydb.orders</b>), and you can join freely across databases in one query.'
        ],
        callout: {
          kind: 'tip',
          text: 'Because there’s no active database, an unqualified name like <b>orders</b> won’t resolve — always write it out as <b>database.table</b>.'
        }
      },
      {
        id: 'save-query',
        title: 'Save a query',
        subtitle: 'Keep the queries you reach for often.',
        intro:
          'Got a query you’ll want again? Save it and give it a name so it’s a click away next time, instead of retyping it or hunting through your history.',
        steps: [
          'With a valid query in the editor, click <b>Save</b>.',
          'Give it a <b>Name</b> and click <b>Save</b> — saving again later updates it in place.',
          'A small marker on the tab lets you know when your edits have drifted from the saved copy.'
        ]
      },
      {
        id: 'query-history',
        title: 'Review query history',
        subtitle: 'Find and rerun something from earlier.',
        intro:
          'Every query you run is remembered, so you can always find your way back to something you ran an hour — or a week — ago, even if you never saved it.',
        steps: [
          'Open the history panel to see your past runs, newest first.',
          'Each entry shows the query, its status, how long it took, and how much data it scanned.',
          'Click one to load it into a new tab, where you can tweak it and run it again.'
        ]
      },
      {
        id: 'work-with-results',
        title: 'Work with results',
        subtitle: 'Read and page through query output.',
        intro:
          'Once a query succeeds, its results fill the table below the editor. You can make yourself at home here — resize columns, page through large result sets, and give whichever pane you’re focused on more room.',
        steps: [
          'After a query succeeds, results appear in a table below the editor.',
          'Drag a column’s edge to resize it — your widths are remembered as you switch tabs.',
          'Use <b>Prev</b> and <b>Next</b> to page through large result sets.',
          'Choose how many rows show at once with <b>Rows per page</b> above the table — any number from 1 to 1000 (the default is 100). One setting covers every result tab, and it sticks for the session.',
          'Ran a script with <b>Run Multiple Queries</b>? Each row-returning statement gets its own result tab above the table — switch tabs to compare outputs, and each keeps its own page position and column widths.',
          'Want more room? The <b>Default / Query Editor / Results</b> control in the toolbar snaps the split between the editor and the results — grow whichever you’re working in. Your choice sticks for the session.'
        ]
      },
      {
        id: 'save-results',
        title: 'Save results to your files',
        subtitle: 'Export a result set back into your files.',
        intro:
          'Results don’t have to stay in the Query tab. Save a successful query’s output as a file — in your own space or a shared one — and it becomes just another file you can download, share, or even build a new table from.',
        steps: [
          'After a successful query, click <b>Save results to my files</b> in the status bar.',
          'Choose a destination space and a file name.',
          'The results export in the background, and a notification lets you know when they’re saved.'
        ]
      }
    ]
  },
  {
    id: 'tables',
    label: 'Tables',
    subtitle: 'Turn folders of files into queryable tables, and share them.',
    icon: 'tables',
    guides: [
      {
        id: 'create-table',
        title: 'Create a table from a folder',
        subtitle: 'Turn a folder of files into a table you can query.',
        intro:
          'Have a folder full of data files — CSV, JSON, or Parquet — that you’d like to run SQL against? This turns them into a table without moving or copying anything. The portal reads the files where they already sit and builds the table in the background, then it shows up in the <b>Query</b> tab ready to go.',
        steps: [
          'In the <b>Files</b> tab, open the folder whose files you want to query, then click <b>Create table</b>.',
          'Enter a <b>Table name</b> (lowercase letters, digits, or underscores, starting with a letter).',
          'If your files sit in <b>key=value</b> folders (for example <b>year=2026/month=01/</b>), click <b>Add partition keys</b> and declare each key in order — coarsest first — along with its type and range.',
          'Click <b>Create table</b>. It’s built in the background, and you’ll get a notification when it’s ready — or if something stopped it from being created.'
        ],
        callout: {
          kind: 'tip',
          text: 'Once it’s ready, the table appears in the <b>Query</b> tab under the same space, so you can start writing SQL against it straight away.'
        }
      },
      {
        id: 'share-table',
        title: 'Share a table',
        subtitle: 'Copy a table into other users’ or shared spaces’ databases.',
        intro:
          'Any table you can browse in the <b>Query</b> schema rail can be shared. Sharing copies the table’s data files into each recipient’s space and creates the table in their database, so they can query it as their own — it’s a one-time snapshot, not a live link.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, open the <b>⋮</b> menu on a table and choose <b>Share table</b> (views can’t be shared).',
          'Pick who to share with — <b>Users</b> or <b>Shared spaces</b> — type one or more names, and click <b>Add</b>. You can mix both kinds in one share.',
          'Adjust the <b>Table name for recipients</b> if you like (it defaults to the source table’s name).',
          'Click <b>Share</b>. The copy runs in the background — each recipient is notified on success, and every outcome lands in your notifications.'
        ],
        callout: {
          kind: 'warning',
          text: 'If a recipient already has a table with that name (or leftover files where it would go), that recipient’s share fails with a notification — nothing is overwritten. The others still go through.'
        }
      }
    ]
  },
  {
    id: 'shared-connections',
    label: 'Shared connections',
    subtitle: 'Spaces you share with teammates — files and tables, together.',
    icon: 'connections',
    guides: [
      {
        id: 'create-shared-connection',
        title: 'Create a shared connection',
        subtitle: 'Make a space several people can share.',
        intro:
          'A shared connection is a space that more than one person can work in — the same files and the same tables, visible to everyone you invite. It’s how you collaborate here. You always start out as the owner and the only member; you bring others in afterwards.',
        steps: [
          'On the <b>Connections</b> tab, click <b>Create</b>.',
          'Enter a <b>Connection name</b> (lowercase letters, digits, or underscores, starting with a letter).',
          'Click <b>Create</b>. It’s set up in the background and shows up in your list when it’s ready.'
        ],
        callout: {
          kind: 'tip',
          text: 'Choose the name carefully — it’s permanent, must be unique across every space, and can’t be renamed later. You’ll start the space on your own; add people whenever you’re ready with <b>Add members</b>.'
        }
      },
      {
        id: 'add-members',
        title: 'Add members',
        subtitle: 'Give other people access to a space you own.',
        intro:
          'Ready to bring your team in? As the owner, you can add members at any time, and each one immediately gets access to all the shared files and tables in the space.',
        steps: [
          'Open <b>Manage</b> on a space you own, then click <b>Add members</b>.',
          'Enter one or more <b>Usernames</b>, separated by spaces, commas, or new lines.',
          'Click <b>Add</b>. Everyone you add gets access to the same shared files and tables; any usernames that don’t exist are simply ignored.'
        ]
      },
      {
        id: 'member-status',
        title: 'See who has access and their status',
        subtitle: 'Check the member list and each person’s join status.',
        intro:
          'Wondering who’s in a space and whether they’ve found their way to it yet? The member list shows everyone, with a status next to each person so you can tell who has actually opened the space.',
        steps: [
          'If you own the space, open <b>Manage</b>; if you’re a member, open <b>View members</b> — either one shows the full member list (read-only for members).',
          'Each person shows a status: <b>Active</b> once they’ve signed in and opened the space, or <b>Pending</b> until they do.',
          'Click <b>Refresh</b> to pull in the latest statuses.'
        ],
        callout: {
          kind: 'tip',
          text: 'Pending vs Active only reflects whether someone has opened the space yet — their access is granted the moment you add them, not when they first show up.'
        }
      },
      {
        id: 'remove-members',
        title: 'Remove a member',
        subtitle: 'Revoke someone’s access to a space you own.',
        intro:
          'If someone no longer needs to be in a space, you can remove them as the owner. Their access ends, but nothing they contributed goes away.',
        steps: [
          'In the <b>Manage</b> member list, click <b>Remove</b> next to a member and confirm.',
          'They lose access, but the shared files and tables stay put. The owner can’t be removed.'
        ]
      },
      {
        id: 'leave-space',
        title: 'Leave a space',
        subtitle: 'Step out of a space you belong to.',
        intro:
          'Done with a space you were invited to? You can leave it yourself, without needing the owner to remove you. It only affects your own access.',
        steps: [
          'On a space you belong to but don’t own, choose <b>Leave</b> and confirm.',
          'You lose access; everyone else keeps theirs, and nothing is deleted.'
        ]
      },
      {
        id: 'delete-space',
        title: 'Delete a space',
        subtitle: 'Permanently remove a space you own.',
        intro:
          'When a shared space has served its purpose, the owner can delete it outright. This is the big one — it clears the space away for everyone, so it asks you to confirm by name first.',
        steps: [
          'On a space you own, choose <b>Delete</b>.',
          'Type the space’s name to confirm you mean it, then click <b>Delete</b>.'
        ],
        callout: {
          kind: 'warning',
          text: 'This permanently deletes the space for everyone — all of its files, all of its tables, the database itself, and every member’s access. There’s no undo.'
        }
      }
    ]
  },
  {
    id: 'notifications',
    label: 'Notifications',
    subtitle: 'How the portal keeps you posted on activity.',
    icon: 'notifications',
    guides: [
      {
        id: 'find-notifications',
        title: 'Find your notifications',
        subtitle: 'Know when something needs your attention.',
        intro:
          'Some things in the portal happen in the background — a table being built, results being exported, changes to a shared space. Notifications are how the portal taps you on the shoulder when one of those finishes or needs you. Look to the bell in the top bar.',
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
        intro:
          'The Notifications page is the full record of everything the portal has let you know about — your shared spaces and background jobs like table builds — with the newest at the top.',
        steps: [
          'The <b>Notifications</b> page lists them newest first, 10 per page.',
          'Switch between <b>All</b> and <b>Unread</b>, and use <b>Prev</b> / <b>Next</b> to page through them.',
          'Click <b>Refresh</b> to check for new ones.'
        ]
      },
      {
        id: 'mark-read',
        title: 'Mark notifications as read',
        subtitle: 'Clear the unread indicator.',
        intro:
          'Once you’ve seen a notification, mark it read to clear the count on the bell — one at a time, or all at once when you just want a clean slate.',
        steps: [
          'Click <b>Mark read</b> on a single notification, or <b>Mark all read</b> to clear them all in one go.',
          'The unread count on the bell updates right away.'
        ],
        callout: {
          kind: 'tip',
          text: 'Notifications can’t be deleted — marking one read simply clears its unread marker, and it stays in your history.'
        }
      }
    ]
  }
];
