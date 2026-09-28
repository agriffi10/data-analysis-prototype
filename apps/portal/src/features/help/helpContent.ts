import type {HelpSection} from './help.types';

// MAINTENANCE NOTE.
// This content describes only the portal behavior that is shipped and reachable
// by users: Files (incl. background file operations and their conflict round trip,
// sending, archiving, and running a data-quality check and reading its report),
// Query, Tables, the Data Explorer, Shared spaces, Notifications, getting
// around the app, and feedback. Every step below maps to a real, wired affordance
// in the code, named by the text the user sees.
//
// A guide is hidden by the flag its MAIN action sits behind, through a row in
// gatedSurfaces.ts — never by a check here. An option inside a dialog that a
// different switch can remove gets a short guide of its own under that switch,
// rather than a step in the main guide: the Parquet, JSON and Excel formats, and
// sending or sharing to a shared space, are split out that way. Passing mentions
// of a shared space in a space picker are not split, and overstate while the
// shared-workspaces switch is off.
//
// The data-quality guides cover the whole loop: starting a check from EITHER
// entry point (Files, or Data quality → New quality check), the notification that
// reports it, the report itself, and browsing past checks from the Data quality
// tab. The guides say a failure reports itself in notifications, with no adverb.
// "usually" went when the drain began sweeping every control plane's request DLQ
// back into notifications, since a request that never started an execution had
// notified nobody; "always" overclaims, because an uncatchable Step Functions
// error ends the execution without reaching the failure notifier. The
// data-quality page's footer note carries the long form.
//
// When a feature is added, changed, or removed, revisit this file so the guides
// never promise behavior that isn't shipped — the post-spec ritual in
// docs/process/completion-ritual.md includes a check for exactly this.
//
// ONE GUIDE COVERS RENAME, MOVE, COPY AND DELETE, and it cannot be gated. The conflict guide
// beside it follows the async switchover, because a refusal round trip only exists while the
// routing does — but the four verbs still work on a single file in either state, and with the
// switch off one of this guide's steps is what explains the controls a folder or any multi-item
// selection then leaves unavailable. Gating the guide would leave the core of the Files section
// undocumented whenever the kill switch is thrown. The accepted cost, stated rather than hidden:
// with that switch off, the intro and the background-operation steps overstate for as long as it
// stays off.

/** The authored Help & guides sections, in sidebar order. */
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
          'Everything starts here — getting your files into Data Quarry. Uploads always land in the folder you’re currently viewing, so browse to where you want them first, then drop them in. Each file can be up to 5 GB, and the panel keeps you posted on every one.',
        steps: [
          'Open the <b>Files</b> tab and browse to the folder you want to upload into. If you mean to query the files as a table, put them in a folder of their own rather than at the top of your space: a table is built from a whole folder, never from a single file.',
          'Click <b>Upload</b> to open the upload panel.',
          'Drag files onto the panel, or click <b>choose files</b> to pick them from your computer. You can upload files but not whole folders, so create the folder first with <b>New folder</b> and upload into it.',
          'Each file uploads into the current folder, and the panel tracks its progress until it’s done. You can close the panel and carry on in other pages while it works, but reloading or closing the browser tab cancels any upload still in progress.',
          'Small files upload in one go. Large ones are sent in pieces, so if your connection drops partway only the pieces in flight are tried again, rather than the whole file — you may see the progress bar pause while it catches up.',
          'If a file does fail, the panel marks it <b>Failed</b> and nothing is saved: an upload that never finishes leaves no file behind for you to find or tidy up. Drop it in again to retry. Pieces left behind by an interrupted upload, such as one cut off by closing the tab, are cleaned up automatically within seven days.'
        ],
        callout: {
          kind: 'warning',
          text: 'When an upload shares a name with an existing file, the upload panel holds the new one back until you choose, and the rest of your files carry on. <b>Rename</b> lets you type a different name, so both files are kept. <b>Cancel</b> leaves the new one out of the upload. <b>Overwrite</b> replaces the existing file for good — there is no version history or trash to get it back.'
        }
      },
      {
        id: 'create-folders',
        title: 'Create and use folders',
        subtitle: 'Keep your files organized in folders.',
        intro:
          'Folders work just like they do on your computer — they’re how you keep things tidy as your files grow. You can put folders inside folders, and the breadcrumbs at the top always show where you are.',
        steps: [
          'In the <b>Files</b> tab, click <b>New folder</b>.',
          'Enter a <b>Folder name</b>. It can’t contain a slash or start or end with a space, and it can’t be one of the names Data Quarry uses for its own folders, such as <b>system_settings</b>.',
          'Click <b>Create</b>, and the new folder appears in the list.',
          'Open a folder by clicking its name. To step back up, use the breadcrumbs above the list, or the <b>..</b> row at the top of a subfolder.'
        ]
      },
      {
        id: 'download-files',
        title: 'Download files',
        subtitle: 'Save a file back to your computer.',
        intro: 'When you need a file back on your own machine, downloading takes a click or two.',
        steps: [
          'In the <b>Files</b> tab, click <b>Details</b> on the file, then <b>Download</b> to save it to your computer. On a phone or in a narrow window, <b>Details</b> is the <b>ⓘ</b> button at the end of the row.',
          'In a hurry? <b>Double-click the file’s row</b> and it downloads right away. On a phone or in a narrow window, just tap the file.'
        ]
      },
      {
        id: 'rename-move-copy-delete',
        title: 'Rename, move, copy, or delete',
        subtitle: 'Reorganize files and folders after uploading.',
        intro:
          'Plans change, and so does how you want your files arranged. Tick items to use the toolbar above the list, or open a single item’s details to rename it. A single file is done straight away. Whole folders work too, and because a folder can hold thousands of files Data Quarry does those in the background while you carry on.',
        steps: [
          'Tick the checkbox on one or more items, and <b>Copy</b>, <b>Move</b> and <b>Delete</b> in the toolbar above the list become available.',
          'For <b>Move</b> or <b>Copy</b>, open the destination folder in the picker, then confirm with <b>Move here</b> or <b>Copy here</b>.',
          'To <b>Rename</b> a single item, click <b>Details</b> on its row and choose <b>Rename</b>, then type a <b>New name</b> — a file keeps its original extension automatically.',
          'A single file is done straight away. <b>Anything else — a folder, or more than one item — is handed to Data Quarry to do in the background.</b> You get a note that it has been requested, an entry in the in-progress list, and a notification when it finishes.',
          'While one of those is running, anything else in that space that would also run in the background — another folder or multi-item <b>Copy</b>, <b>Move</b> or <b>Delete</b>, a folder <b>Rename</b>, and <b>Archive</b> — is unavailable, and hovering over the button says why. Nothing is queued, so start it again once the first has finished. If its notification never arrives, press <b>Dismiss</b> on its entry in the in-progress list. Single files are unaffected.',
          'The file list doesn’t update by itself when background work finishes. Press the refresh button at the end of the folder path, or switch to another browser tab and come back.',
          'If Data Quarry’s background service is unavailable, <b>Copy</b>, <b>Move</b> and <b>Delete</b> are unavailable for a folder or for more than one item, and so is <b>Rename</b> for a folder — hovering over each says why. A single file works as normal.',
          'The folders Data Quarry fills for you are gathered under <b>system_settings</b>, sorted in among your own folders — <b>athenaresults</b>, where your query results are kept, and your <b>archive</b> receipts. Click it to open it up, and browse what is inside as normal. Both are managed for you, so neither can be deleted or moved, and you can open and download what they hold but not upload into them or change it. Tables shared with you stay in <b>shared_tables</b> at the top level, because they are yours to work with.'
        ],
        callout: {
          kind: 'warning',
          text: 'Deleting is forever — there’s no version history or trash, so a deleted file or folder is gone for good. A background delete can also <b>partly</b> succeed: some items go and others are kept back, and the notification names the first few that were kept and says how many more there were. To keep you safe, the confirm dialog starts on <b>Cancel</b>, so a stray Enter key won’t delete anything.'
        }
      },
      {
        id: 'resolve-file-operation-conflicts',
        title: 'When a move or copy is refused',
        subtitle: 'Something was in the way — here is how to finish the job.',
        intro:
          'A background move or copy never quietly writes over your files. If something with the same name is already at the destination, that item is left exactly where it was and the rest of the request carries on without it. The notification says what happened, and you can settle the conflicts from there.',
        steps: [
          'In <b>Notifications</b>, find the message about the operation. Below it there is a <b>Review conflicts</b> link.',
          'The review lists the items that could not be placed, with a sample of what is in the way.',
          'For a rename, choose <b>Use a different name…</b>, type a name that is free, and click <b>Request again</b>. Nothing is written over, and the request is sent again for that item only.',
          'Otherwise choose <b>Overwrite…</b>, read the confirmation, and confirm with <b>Overwrite</b>. Only the items that were in the way are sent again; your notification says what became of the rest.',
          'You get a fresh notification for the second request, the same as the first.'
        ],
        callout: {
          kind: 'warning',
          text: 'Overwriting <b>cannot be undone</b>: there is no version history and no trash here, so whatever was at the destination is replaced for good. Renaming is the safe way out, and it is what most people want. Anything that arrives at the destination after you press <b>Overwrite</b> is left alone.'
        }
      },
      {
        id: 'send-files',
        title: 'Send files to someone',
        subtitle: 'Hand a copy of files or folders to another person.',
        intro:
          'Sometimes the quickest way to share something is to give someone a copy of it. Select what you want, pick who gets it, and Data Quarry copies it into their space in the background — you keep your originals, and you hear back about each recipient.',
        steps: [
          'In the <b>Files</b> tab, tick one or more items — files, folders, or a mix — and click <b>Send to…</b>.',
          'Type a username and press <kbd>Enter</kbd> or click <b>Add</b>; each name you add appears as a chip. Names are offered as you type, and a name that isn’t offered is still allowed — it’s checked when the request is sent. You can type several at once, separated by spaces or commas.',
          'Click <b>Send</b>. The copy runs in the background, so you can carry on working.',
          'What you sent lands in their space under <b>shared_files</b> → your username, and they get a notification with a link straight to it.'
        ],
        callout: {
          kind: 'tip',
          text: 'A send is a <b>copy</b>, and it never overwrites: you keep yours, the recipient isn’t asked to accept, and if they already have something you sent under the same name that recipient is refused — the notification tells you which item it was, so you can rename it and send again.'
        }
      },
      {
        id: 'send-files-to-a-space',
        title: 'Send files to a shared space',
        subtitle: 'Give a copy to a whole team’s space instead of one person.',
        intro:
          'A send can go to a shared space as well as to a person, and one send can go to both. The copy lands in the space, where everyone in it can see it.',
        steps: [
          'In the <b>Files</b> tab, tick what you want to send and click <b>Send to…</b>.',
          'Under <b>Send to</b>, choose <b>Shared spaces</b>. Type a space’s name in <b>Space names</b> and press <kbd>Enter</kbd> or click <b>Add</b>; the spaces you belong to are offered as you type.',
          'To send to people as well, switch back to <b>Users</b> and add their names. The spaces you already added stay.',
          'Click <b>Send</b>. What you sent lands in the space under <b>shared_files</b> → your username, and the space’s <b>owner</b> is the one notified.'
        ]
      },
      {
        id: 'archive-files',
        title: 'Archive and restore files',
        subtitle: 'Put files back where they were, after archiving them for the long term.',
        intro:
          'Archiving takes files or folders out of your space and stores them cheaply for the long term. Unlike a delete, the copy is kept safely — but it is <b>no longer in your file list</b>, and getting it back is not instant. Use it for things you want to keep but do not expect to open again soon.',
        steps: [
          'In the <b>Files</b> tab, tick one or more items and click <b>Archive</b> — or open a single item’s <b>Details</b> and choose <b>Archive</b> there.',
          'Read the confirmation. It names what will go, and says plainly that these files leave this space.',
          'Click <b>Archive</b>. The work happens in the background, and a notification tells you when it has finished — including the <b>archive id</b> you will need to get it back.',
          'Every archive also leaves a folder under <b>system_settings</b> → <b>archive</b> in your space, named after its id, holding a receipt you can download and read.',
          'To bring an archive back, open the <b>Files</b> tab in the space it was archived from, click <b>Restore Archived Data</b>, paste the archive id, and click <b>Restore</b>. Everything comes back where it was. In a narrow window that first button moves to a bar along the bottom and says just <b>Restore</b>.',
          'A restore takes <b>several hours</b> — the files have to be retrieved from long-term storage first. You get one notification when it starts and another when it is done.',
          'An archive can be restored once. When every file is back, the archived copy is removed, and the notification says so.'
        ],
        callout: {
          kind: 'warning',
          text: 'A restore puts every file back where it came from, and it refuses to overwrite anything: if even one of those files exists again, <b>nothing</b> is restored and the notification names the files in the way. Move or rename them and request the restore again. The same rule holds while the restore is running, file by file — if something appears at one of those paths in the hours a restore takes, that file is left exactly as it is and the notification tells you how many were skipped. The <b>archive</b> folder itself — under <b>system_settings</b> — is read-only: you can open and download receipts, but not upload into it, rename it or delete it.'
        }
      },
      {
        id: 'file-details',
        title: 'View file details',
        subtitle: 'Inspect a file’s name, path, size, type, and metadata.',
        intro:
          'Sometimes you just need to know more about a file — exactly where it lives, how big it is, or what metadata it carries. The details panel gathers all of that in one place.',
        steps: [
          'Click <b>Details</b> on any file or folder row. On a phone or in a narrow window, it’s the <b>ⓘ</b> button at the end of the row.',
          'The panel shows its name and paths, and — for files — size, type, last modified, storage class, ETag, and any custom metadata.',
          'From here you can also <b>Download</b> a file or <b>Rename</b> the item.',
          'Use the copy buttons to copy a path, and close the panel with <kbd>Escape</kbd> or the close button.'
        ]
      },
      {
        id: 'check-data-quality',
        title: 'Check data quality',
        subtitle: 'Find out what’s wrong with a data file — without changing it.',
        intro:
          'Before you build a table from a folder of CSVs, or after someone hands you an export you don’t trust, this tells you what’s actually in there: how many rows, whether a column that looks numeric has stray text in it, how much is blank, whether rows repeat, and — for a folder — whether every file agrees on the same columns. It only ever <b>reads</b> your data. Nothing is modified, moved, or deleted.',
        steps: [
          'There are two ways in. From <b>Files</b>: tick the checkbox on <b>one</b> file or <b>one</b> folder, click <b>Check data quality</b> in the toolbar above the list, and click <b>Start check</b> — the dialog names exactly what will be read.',
          'Or from <b>Data quality</b>: click <b>New quality check</b>, choose the space if you belong to more than one, and browse to the folder you want checked. Click a file first if you want to check just that one file. Then click <b>Check this folder</b>, or <b>Check this file</b>.',
          'A check needs a folder, not the top of a space, so in <b>New quality check</b> the button stays unavailable until you open one. A check reads every file beneath what you give it, and the top of a space also holds your query results, archived copies and shared tables, which would be counted as your data. One file sitting at the top is fine: click it and only it is read.',
          'It reads CSV and <code>.txt</code> files, JSON (including <code>.ndjson</code> and <code>.jsonl</code>) and Parquet, and CSV or JSON compressed as <code>.gz</code>. A folder can hold up to 1,000 files with up to 200 columns, all in one format.',
          'The check runs in the background and can take a few minutes. Carry on working; you don’t have to wait on the page.',
          'When it finishes you’ll get a <b>notification</b> naming what was checked. Click it to open the full report — the findings live there, not in the notification.',
          'If the <b>column names</b> in your data won’t work in Athena — a header like <b>Order ID</b>, or two headers in the same file that differ only by case — the check stops and the notification names them. There’s no report in that case: those names are also what would stop a table being readable, so they’re worth fixing before anything else. Headers that differ only by case in <b>different</b> files, like <b>CustomerID</b> in one and <b>customerid</b> in another, are fine: Athena reads them as one column, so the report lists it once, spelled as in the first file by name that has it, and notes the other spellings.'
        ],
        callout: {
          kind: 'tip',
          text: 'Checking <b>one file</b> reports on that file alone — its neighbours in the same folder are not counted, even though they sit alongside it.'
        }
      },
      {
        id: 'read-data-quality-report',
        title: 'Read a data quality report',
        subtitle: 'What each part of the report tells you, and what it can’t.',
        intro:
          'A report opens from its notification, or from its row on the <b>Data quality</b> tab. It starts with what matters most and then lists every finding, so you can read as far as you need.',
        steps: [
          'The report opens with its totals — rows, files, duplicate rows, and columns with issues — and then <b>What to look at first</b>, the few findings most worth your time.',
          'Below them the report lists every finding: blank values, columns whose values don’t match their type, repeated rows, and — for a folder — any file whose columns disagree with the rest.',
          'In a folder of CSV files it also flags any file whose columns don’t line up with the report’s <b>Columns</b>, the order every file is read in, because a CSV’s columns are read in order and that file’s values are counted under the wrong columns. If the first file is the odd one out, it is the other files that get flagged.',
          'When the report finds <b>repeated rows</b>, it lists up to five of the most repeated ones under <b>Most repeated rows</b>, each with how many times it appears — the duplicate count in the totals counts every copy after the first, so the two numbers are not the same figure. If your data has columns holding lists or objects, the repeated rows can’t be shown, and the report says so where the table would have been.',
          'For more than one file, it shows how many rows each file holds, and where the text encoding is wrong, which file each example is in and how far into it.',
          'If a source turns out to have <b>no rows at all</b> — an empty or header-only export — the report says so as a finding rather than calling it clean.',
          'When you check a folder, a column named after one of its <b>key=value</b> partitions — <b>Year</b> or <b>year</b> in a folder like <b>year=2026/</b> — doesn’t stop the check. In a CSV its figures are reported under a new name, <b>year_in_file</b>, because a CSV’s columns are read in order and the partition already has the name. In JSON or Parquet it is left out of the report’s column figures, because a table over the folder reads the folder’s value in its place. Either way the report says so at the top of its <b>Columns</b>. If your CSV files don’t all put that column in the same place, the report flags the files whose columns don’t line up. Checking one file doesn’t read the folder’s partitions, so there the column keeps its own name.',
          'A report that would be too large to open whole leaves out the repeated rows first, then shortens its longest lists — the files that disagree, the rows in each file, a column’s other spellings — and says how many more each one had.',
          'To check the same thing again, click <b>Re-run check</b>.'
        ],
        callout: {
          kind: 'tip',
          text: 'The check never guesses in your favour. Some figures are <b>estimates</b> and say so: the ragged-row count over-counts rows with commas or line breaks inside quoted values, and when there’s more data than it can read in full — about 2 GB — or some files are compressed, the text-encoding check reads a sample rather than every byte. A figure marked <b>Skipped</b> or <b>Not computed</b> is one the check couldn’t make — never a clean result.'
        }
      },
      {
        id: 'past-data-quality-checks',
        title: 'Find a past quality check',
        subtitle: 'Recent checks in all your spaces, in one place — you don’t need to keep the notification.',
        intro:
          'The <b>Data quality</b> tab lists the checks that finished, newest first, across your own space and any shared spaces you belong to — including checks other people in those spaces ran. Each space keeps its 200 most recent. Click a row to reopen its full report.',
        steps: [
          'Open the <b>Data quality</b> tab.',
          'Use <b>All</b> / <b>Issues found</b> / <b>Clean</b> to narrow the list, and <b>Prev</b> / <b>Next</b> to page through it.',
          'Click any row to open that check’s full report.',
          'To run another, click <b>New quality check</b>. A check you’ve just started is <b>not</b> in this list yet — it appears once it finishes, which can take a few minutes. The list doesn’t update by itself, so click the refresh button beside the filters to see it.'
        ],
        callout: {
          kind: 'tip',
          text: 'A row tagged <b>Partly checked</b> had at least one check that didn’t cover all of the data: it was skipped, it couldn’t finish, or the text-encoding check read a sample rather than every byte. Checks of JSON and Parquet data always carry it, because the ragged-row check only applies to CSV. <b>Clean</b> on such a row means no issues in what could be checked — open the report to see which checks those were. A check that <b>failed</b> has no row here, because it never produced a report; it reports itself in your <b>notifications</b> instead — including one that was accepted but never got going.'
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
          'The Query tab is a full SQL workspace over your data. Type a query, run it, and the results land right below the editor. The status bar keeps you informed the whole time — whether the query is queued or running and for how long, how many rows came back, how much data it scanned, and how long it took.',
        steps: [
          'Open the <b>Query</b> tab and type SQL in the editor.',
          'Click <b>Run Statement</b>, or press <kbd>Ctrl/Cmd + Enter</kbd> in the editor — it runs your selection if you have one, otherwise the statement under the cursor. In a narrower window the toolbar shows its buttons as icons only.',
          'Watch the status bar for progress, the exact total row count, data scanned, and how long it took. While the total is still being counted it shows the rows loaded so far, with a <b>+</b> if there are more, and says <b>counting…</b>.',
          'If the query fails because of something in its SQL, open <b>Details</b> under the message to read Athena’s own explanation. Its line and column count from the start of the statement that ran, not from the top of the editor.',
          'Changed your mind mid-run? Click <b>Stop</b> to cancel a running query or script.'
        ],
        callout: {
          kind: 'warning',
          text: 'A query still running after <b>30 minutes</b> keeps going in Athena, and keeps scanning, but the tab stops waiting for it and says so, and <b>Stop</b> is no longer offered for it. When it finishes, its results are saved in your files under <b>system_settings</b> › <b>athenaresults</b>, in a file named after the query ID the message shows.'
        }
      },
      {
        id: 'query-tabs',
        title: 'Work in several query tabs',
        subtitle: 'Keep different queries open side by side.',
        intro:
          'Each tab above the editor holds its own query, results and run, so you can keep a few pieces of work open at once and switch between them.',
        steps: [
          'Click <b>+</b> in the tab strip above the editor to open a new, empty tab, and click a tab to switch to it.',
          'A query you open from <b>Saved queries</b>, or from a table’s menu in the schema rail, opens in a tab of its own.',
          'Close a tab with its <b>✕</b>, or from the keyboard, move to it with the arrow keys and press <kbd>Delete</kbd> or <kbd>Backspace</kbd>. A tab with SQL in it asks first, and <b>Close tab</b> confirms. The last tab can’t be closed.',
          'You can have up to 10 tabs open. They survive a page reload, but closing the browser tab or window clears them, so save anything you want to keep.'
        ]
      },
      {
        id: 'run-script',
        title: 'Run several statements at once',
        subtitle: 'Run a SQL script of ;-separated statements from top to bottom.',
        intro:
          'You don’t have to run statements one at a time. Put several in the editor separated by semicolons — say, a <b>CREATE TABLE</b> followed by a <b>SELECT</b> — and Data Quarry runs them in order, one after another. Each gets its own history entry, and you pick whether you want a single final result or one result per statement.',
        steps: [
          'Write multiple statements in one editor, separated by semicolons.',
          'Open the dropdown next to <b>Run Statement</b> to reach the two whole-script options.',
          'Choose <b>Run Query Tab</b> (<kbd>Ctrl/Cmd + Shift + Enter</kbd>) to run every statement in order and show the last result set.',
          'Or choose <b>Run Multiple Queries</b> (<kbd>Ctrl/Cmd + Alt/Option + Enter</kbd>) to give every statement that returns rows its own result tab above the results table.',
          'To run only some of them, select those statements and click <b>Run Statement</b>. Each one that returns rows gets its own result tab.',
          'Close a result tab you no longer need with its <b>✕</b>, or from the keyboard, move to it with the arrow keys and press <kbd>Delete</kbd> or <kbd>Backspace</kbd>. The last one stays open, and the next run replaces them all.',
          'Statements run one at a time, in order. The status bar shows which one is running (for example “Statement 2 of 4”), and each gets its own history entry.',
          'To keep a copy of the script on your computer, click <b>Download</b> in the toolbar above the editor. The tab’s whole query is saved as a <code>.sql</code> file named after the tab — a saved query’s tab carries its name.',
          'If a statement fails, or is still running after <b>30 minutes</b>, the script stops there — the message names the statement, and the ones after it don’t run.'
        ],
        callout: {
          kind: 'warning',
          text: 'There are no transactions here: statements that already succeeded keep their effects — a table you created or dropped stays that way — even if a later statement fails.'
        }
      },
      {
        id: 'browse-databases',
        title: 'Browse databases and query across them',
        subtitle: 'Use the database navigator to find your tables, and join across databases.',
        intro:
          'The rail on the left is your database navigator, a map of everything you can query — your own personal database plus any shared spaces you belong to. Expand any database to see its tables and columns. There’s no “current” database to switch between, which means a single query can read from, and join across, any databases you have access to.',
        steps: [
          'The rail on the left lists every database you can access. Your personal database, named after your username, is under <b>My database</b>; any shared spaces you belong to are under <b>Shared spaces</b>, one database each.',
          'Expand a database to inspect its tables and columns.',
          'Created a table elsewhere, or a teammate did? Click the <b>Refresh</b> icon beside an expanded database to re-read its tables and views without reloading the page.',
          'Hover over a table and open its <b>⋮</b> menu for more. <b>View data</b> opens a new tab and runs a query over the whole table, <b>View DDL</b> opens how the table was defined, and <b>Drop table</b> — <b>Drop view</b> on a view — removes it after you confirm. Dropping a table built from a folder leaves its files where they are, but an Iceberg table you created in a query is dropped together with its data.',
          'Short on space? <b>Collapse the side panel</b> with the chevron in its header; a small handle at the edge brings it back. Your choice is remembered in this browser.',
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
        subtitle: 'Keep a query as a SQL script you can open again.',
        intro:
          'Got a query you’ll want again? Save it and give it a name so it’s a click away next time, instead of retyping it or hunting through your history. A saved query is an ordinary <code>.sql</code> file in a <b>saved_queries</b> folder in a space, so you can find it, download it or delete it like anything else — and saving into a shared space is how you hand a query to the people you work with.',
        steps: [
          'With a query in the editor, click <b>Save</b>.',
          'Choose a <b>Space</b> to save it into: your own files, or any shared space available to you. It opens on the space the query came from, or the last one you worked in.',
          'Give it a <b>Name</b> and click <b>Save</b>. Saving always asks — even when you opened the query from a file — so you can see which file, in which space, you are about to write.',
          'The query is written to that space’s <b>saved_queries</b> folder as a <code>.sql</code> file named after the name you gave it. Type <code>report</code>, <code>report.sql</code> or <code>report.SQL</code> and you get the same file.',
          'If another query of that name is already there, you’re asked to confirm with <b>Replace</b>. Saving back to the file your tab was opened from replaces it without asking, and the dialog says so before you click. Names are case-sensitive, so <b>Report</b> and <b>report</b> are two different files.',
          'Saving into a different space than the one your tab came from writes a <i>new</i> file there and leaves the original alone. Your tab then follows the new file.',
          'Everyone with access to that space can open what you saved — a saved query in a shared space belongs to the space, not to you alone.',
          'A dot (•) before the tab’s name means your edits differ from the file you opened or last saved. After a page reload it shows again only once you reopen or save that file.',
          'The <b>saved_queries</b> folder itself can’t be deleted, moved or renamed, but everything inside it is yours to manage.'
        ]
      },
      {
        id: 'load-saved-query',
        title: 'Open a saved query',
        subtitle: 'Find a .sql script — yours or a colleague’s — and open it.',
        intro:
          'Saved queries live in a <b>saved_queries</b> folder in a space, so opening one starts by choosing which space to look in.',
        steps: [
          'Click <b>Saved queries</b> in the toolbar above the editor, beside <b>Save</b>, to open the list.',
          'Choose a <b>Space</b> at the top. Your own space, shown as your username, comes first, and any shared space available to you is listed after it. Your choice is remembered for the rest of the session.',
          'The list shows the <code>.sql</code> files in that space’s <b>saved_queries</b> folder in alphabetical order, with names that start with a capital letter first, along with when each changed and how big it is. Use <b>Prev</b> and <b>Next</b> to page through them.',
          'A count ending in <b>+</b> — like <b>1–10 of 25+</b> — means there are at least that many; pressing Next fetches more.',
          'Click <b>Open</b> to load one into a new tab. Editing it changes only your tab: the file changes when you save, and not before.',
          'Or click <b>Open and run</b> to open it in a new tab and run it straight away. Every statement in it runs in order, as <b>Run Query Tab</b> runs them, and you see the last result set.',
          'Click <b>Delete</b> and confirm to remove one. Deleting a query in a shared space removes it for everyone in that space; a tab that has it open keeps its SQL.'
        ],
        callout: {
          kind: 'tip',
          text: 'Only <code>.sql</code> files at the top level of the folder appear here. Anything else in <b>saved_queries</b> — a CSV, a subfolder — is a normal file, and you’ll find it in <b>Files</b>.'
        }
      },
      {
        id: 'query-history',
        title: 'Review query history',
        subtitle: 'Find and rerun something from earlier.',
        intro:
          'Data Quarry remembers your 100 most recent runs, so you can find your way back to something you ran earlier even if you never saved it. Each statement in a script counts as one run.',
        steps: [
          'Click <b>History</b> at the right-hand end of the tab strip above the editor to see your past runs, newest first.',
          'Each entry shows whether it succeeded, when it ran, the query, how much data it scanned and how long it took — and the saved query’s name if it came from one.',
          'Click <b>Open</b> to open the query in a new tab, or <b>Re-run</b> to open it in a new tab and run it straight away. The tab you were on keeps its own query.'
        ]
      },
      {
        id: 'work-with-results',
        title: 'Work with results',
        subtitle: 'Switch between result tabs, and read and page through query output.',
        intro:
          'Once a query succeeds, its results fill the table below the editor. You can make yourself at home here — resize columns, page through large result sets, and give whichever pane you’re focused on more room.',
        steps: [
          'After a query succeeds, results appear in a table below the editor.',
          'Drag a column’s edge to resize it — your widths are remembered as you switch tabs.',
          'Use <b>Prev</b> and <b>Next</b> to page through large result sets.',
          'Choose how many rows show at once with <b>Rows per page</b> above the table — any number from 1 to 1000 (the default is 100). One setting covers every result tab, and it sticks for the session.',
          'Ran a script with <b>Run Multiple Queries</b>, or selected several statements and clicked <b>Run Statement</b>? Each row-returning statement gets its own result tab above the table — switch tabs to compare outputs, and each keeps its own page position and column widths. Close one you no longer need with its <b>✕</b>, or press <kbd>Delete</kbd> or <kbd>Backspace</kbd> on it; the last one stays open.',
          'Want more room? Drag the divider between the editor and the results to any split you like — or, if you would rather not drag, use the small <b>▲</b> and <b>▼</b> buttons on the divider to nudge it a step at a time. Click the divider and the arrow keys, <b>Home</b> and <b>End</b> move it too; from the keyboard, it sits between those two buttons. Double-click it to go back to an even split. Where you leave it sticks for the session.'
        ]
      },
      {
        id: 'query-filter-by-value',
        title: 'Filter by value',
        subtitle: 'Pick values from a list, in the Data Explorer.',
        intro:
          'A query here filters with the <b>WHERE</b> you type. To pick values from a list instead — every value a column holds, with how many rows hold each — open the table in the <b>Data Explorer</b>.',
        steps: [
          'Hover over a table in the <b>Databases</b> rail, open its <b>⋮</b> menu and choose <b>Explore data</b>, or click <b>Explore in Data Explorer</b> above a result.',
          'In the Data Explorer, open a column’s <b>⋯</b> menu and choose <b>Filter by value…</b>. Tick the values to keep, or choose <b>is not one of</b> to hide them. <b>NULL</b> and <b>(empty)</b> are listed like any other value.',
          'The filter is written out as SQL under <b>Generated SQL</b>, and <b>Open in Query</b> brings that statement back here to edit.'
        ]
      },
      {
        id: 'save-results',
        title: 'Save results to your files',
        subtitle: 'Export a result set back into your files.',
        intro:
          'Results don’t have to stay in the Query tab. Save a query’s output as a file — in your own space or a shared one — and it becomes just another file you can download, share, or even build a new table from. If a multi-statement script failed or you stopped it part-way, the earlier statement’s full result can still be saved, so you don’t have to re-run to get it.',
        steps: [
          'Click <b>Save results…</b> in the status bar, beside the run’s status. It saves a query’s rows; for a <b>SHOW</b> or <b>DESCRIBE</b> it is greyed out and says why.',
          'Type a <b>File name</b> — the extension is added for you — then choose where it goes: a space under <b>Save to</b> if you belong to more than one, and a folder under <b>Destination folder</b>.',
          'Click <b>Save here</b>. The results are saved as a CSV file straight away, and a message confirms where it landed.',
          'The whole result set is saved — every row, not just the page on screen.'
        ],
        callout: {
          kind: 'tip',
          text: 'If a file of that name is already there, you’re asked before it’s replaced.'
        }
      },
      {
        id: 'save-results-formats',
        title: 'Save results as Parquet, JSON or Excel',
        subtitle: 'Pick the file format that suits where the results are going.',
        intro:
          'The save dialog can convert your results as it saves them. CSV is saved straight away; the other formats are converted first, in the background.',
        steps: [
          'Click <b>Save results…</b>, and pick a <b>Format</b>: <b>CSV</b>, <b>Parquet</b>, <b>JSON</b> or <b>Excel</b>. The file extension follows the format you pick.',
          'For any format but CSV the button reads <b>Convert and save</b>. Click it, and you get a <b>notification</b> when the file is ready — you can close the tab and carry on working.',
          'Every row is converted, not just the page on screen.'
        ],
        callout: {
          kind: 'tip',
          text: 'Which to choose: <b>CSV</b> and <b>Excel</b> open in a spreadsheet; <b>Parquet</b> is the one to build a table from, and of the converted formats it takes the largest results, up to about 1.4 GB; <b>JSON</b> is written one object per line, which is what most tools expect. <b>Excel</b> takes results up to 64 MB and about a million rows, fewer when the results are wide, and it stores numbers approximately, so very large whole numbers and long decimals may be rounded. No converted file takes more than 1,500 columns. Over a limit, the notification says which one it reached.'
        }
      },
      {
        id: 'create-view',
        title: 'Create a view from a query',
        subtitle: 'Keep a query in a database, where it works like a table.',
        intro:
          'A view is a saved query that behaves like a table: it shows up in the schema rail, you can query it by name, and it runs its SQL again each time it’s read, so it always reflects the latest data.',
        steps: [
          'Write the query in the editor, naming every table in full as <b>database.table</b>, all from the same database. That is the database the view is created in. The view is made from what <b>Run Statement</b> would run: your selection if you have one, otherwise the statement the cursor is in.',
          'Click <b>Create view</b> in the toolbar above the editor — in a narrower window it shows only its eye icon. If the query names no database, or more than one, or your selection takes in more than one statement, a message says so and nothing is created.',
          'The dialog names the database the view goes into and shows the statement it will save. Type a <b>View name</b> — 3 to 63 characters of lowercase letters, digits or underscores, starting with a letter — and click <b>Create</b>. If that database already has a view of that name, it is replaced.',
          'A message confirms the view was created, and it appears under that database in the schema rail, for anyone who can see that database.',
          'To remove it, open its <b>⋮</b> menu in the schema rail and choose <b>Drop view</b>.'
        ]
      },
      {
        id: 'query-on-a-phone',
        title: 'Use Query on a phone',
        subtitle: 'Run your saved queries and read the results on a small screen.',
        intro:
          'On a phone — or any screen narrower than about 900 pixels, such as a tablet held upright — the Query tab drops the SQL editor and becomes a browse-first surface: your saved queries and your history, ready to run. Writing and editing SQL needs a wider screen, so turn the tablet sideways or widen the window.',
        steps: [
          'Tap <b>☰</b> at the left-hand end of the top bar and choose <b>Query</b>. It opens on <b>Saved</b>, with <b>History</b> a tap away.',
          'On <b>Saved</b>, pick the space to look in if you belong to more than one. Tap <b>Run</b> on any card to run that query, or <b>View</b> to read its SQL without running it.',
          'Results show one card per row — each card lists every column and its value — with <b>Prev</b> and <b>Next</b> at the bottom to page through them.',
          'Tap <b>Run</b> at the top of the results to run it again, or the back arrow to return to your lists.',
          'Need the schema? Tap <b>☰</b> again — your databases and their tables are in the drawer it opens.',
          'From a table’s <b>⋮</b> menu in that drawer, <b>View data</b> runs a query over the whole table and shows its rows, and <b>View DDL</b> shows how the table was defined.'
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
          'Have a folder full of data files — CSV, JSON, or Parquet — that you’d like to run SQL against? This turns them into a table without moving or copying anything. Data Quarry reads the files where they already sit and builds the table in the background, then it shows up in the <b>Query</b> tab ready to go. Every file in the folder has to be in the same one of those formats; empty files, and files or folders whose names start with <b>_</b> or <b>.</b>, are left out. One thing to sort out before you start: <b>column names have to be letters, digits and underscores</b>. A header like <b>Order ID</b> or <b>sales-2024</b> will stop the build, and you’ll get a notification naming the columns to fix. Names are also stored in lowercase, so <b>OrderID</b> becomes <b>orderid</b> — and two headers that differ only by case (<b>Total</b> and <b>TOTAL</b>) become one column, which is refused for the same reason. Your files themselves are never rewritten.',
        steps: [
          'In the <b>Files</b> tab, tick the folder whose files you want to query — exactly one, and it has to be a folder rather than a file — then click <b>Create table</b>. <b>If you cannot see Create table, the window is too narrow</b> — the toolbar drops it below about 900 pixels wide, so widen the window or use a larger display for this step. A table can’t be built from the top of a space itself, because a table reads everything below it and the top of a space also holds your query results, saved queries and shared files.',
          'Check the <b>Table name</b>. It’s filled in from the folder’s name, and it must be 3 to 63 characters of lowercase letters, digits or underscores, starting with a letter.',
          'If your files sit in <b>key=value</b> folders (for example <b>year=2026/month=01/</b>), click <b>Add partition keys</b> and declare each key in order — coarsest first — with its type: <b>Integer</b> or <b>Date</b> with a range, or <b>String</b> with its values. <b>Add another key</b> adds the next one. Files in folders outside the range or values you declare don’t show up in the table, so set them wide enough. If your files also have a column named after a key, even with different capital letters (<b>Year</b> beside the key <b>year</b>), what happens depends on the format. <b>In a CSV the table keeps that column under a new name</b>, such as <b>year_in_file</b>, in the same place, because a CSV’s columns are read in order — the notification that the table is ready names it. In JSON or Parquet the table leaves that column out and takes the value from the folder name instead.',
          'Click <b>Create table</b>. It’s built in the background, and you’ll get a notification when it’s ready — or if something stopped it from being created.'
        ],
        callout: {
          kind: 'tip',
          text: 'Once it’s ready, the table appears in the <b>Query</b> tab under the same space, so you can start writing SQL against it straight away. The table takes its columns from the first file in the folder, alphabetically, so if that file’s columns change later, use <b>Refresh table</b> rather than building it again. In a table built from CSV files every column is text, whatever it holds — to use one as a number in a query, write <code>TRY_CAST(amount AS double)</code>.'
        }
      },
      {
        id: 'refresh-table',
        title: 'Refresh a table after the files change',
        subtitle: 'Update the table’s columns from the first file in its folder.',
        intro:
          'A table takes its columns from <b>one file: the first in its folder, alphabetically</b>. <b>Refresh table</b> reads the folder’s first file again and updates the table’s column list to match it, so a new column is only picked up once it’s in that file. Add it only to a later file — say, <code>sales_2026_09.csv</code> in a folder that starts with <code>sales_2025_01.csv</code> — and the refresh will say the table is already up to date. To pick it up, add the column to that first file too, then refresh again. CSV columns are matched by position, not by name, so a refresh <b>adds new columns at the end of a CSV table and never moves the columns it already has</b> — add a column and the files already in the folder go on being read exactly as before. (Removing one is the exception, below.) That leaves one rule worth following: <b>in CSV files, put a new column last</b>, in every file that has it. Put it anywhere else and it is that file’s own values that land in the wrong columns, because the table reads every file by position. Capital letters sort before lowercase ones, and a file in a subfolder sorts by its full path, so <code>archive/old.csv</code> comes before <code>current.csv</code>. That isn’t always the order the <b>Files</b> tab shows. A refresh never modifies your files, only the table’s definition, and the table stays queryable the whole time.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, hover over the table, open its <b>⋮</b> menu and choose <b>Refresh table</b>.',
          'Check that the <b>Folder</b> line ends with the path of the folder you added files to, then click <b>Refresh table</b>.',
          'The refresh runs in the background. You’ll get a notification saying how many columns were added, retyped or removed, or that the table was already up to date.'
        ],
        callout: {
          kind: 'warning',
          text: 'If a column has <b>disappeared</b> from the folder’s first file, the refresh stops and changes nothing — the notification names the columns and links you back to the dialog. That can also happen when a different file now sorts first (you deleted or renamed the old first file, or added one that sorts earlier) and it’s missing some of the table’s columns. To keep them, add them to the file that now sorts first — in a CSV, in the same position they have in the table — or make the old first file sort first again, then refresh again. To remove them, tick <b>Allow columns to be removed</b> and refresh again. Removing a column breaks any saved query or view that references it, even if other files still have it. In a table built from CSV files, a file that still has a removed column will have the values after it read into the wrong columns — and a removed column comes back as a <b>new</b> column, at the <b>end</b> of the table. So putting it back in the first file restores the table only if it was the last column to begin with. If you removed one from the middle of a CSV table by mistake, build the table again.'
        }
      },
      {
        id: 'refresh-table-limits',
        title: 'When a table can’t be refreshed',
        subtitle: 'What refresh won’t do, and what to do instead.',
        intro:
          'Refresh updates a table’s columns and nothing else. Where that isn’t enough, the answer is to build the table again — you’ll get a notification explaining which of these applied.',
        steps: [
          '<b>Partition keys can’t be changed.</b> A refresh keeps the keys the table already has. To change them, drop the table and create it again.',
          '<b>Views can’t be refreshed.</b> A view has no data files to re-read, so the menu doesn’t offer it. Re-create the view instead.',
          '<b>Tables with catalog-registered partitions can’t be refreshed</b> — partitions added to a table one at a time, rather than declared when Data Quarry built it — and neither can tables built outside Data Quarry or pointing at files outside your space.',
          '<b>The file format can’t change.</b> If the folder’s files are no longer the format the table expects, build a new table over them.',
          '<b>Two columns can’t differ only by capital letters.</b> Athena treats <code>Amount</code> and <code>amount</code> as one column, so if the folder’s first file has both, the refresh stops, changes nothing, and the notification names them. Rename one in your files, then refresh again.',
          '<b>One refresh at a time per table.</b> If a refresh of that table is already running, a second one is refused and changes nothing — wait for the notification from the first, then check whether you still need to refresh again.'
        ]
      },
      {
        id: 'share-table',
        title: 'Share a table',
        subtitle: 'Copy a table into other people’s databases.',
        intro:
          'Any table you can browse in the <b>Query</b> schema rail can be shared. Sharing copies the table’s data files into each recipient’s space and creates the table in their database, so they can query it as their own — it’s a one-time snapshot, not a live link.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, hover over a table, open its <b>⋮</b> menu and choose <b>Share table</b> (views can’t be shared).',
          'Type one or more usernames and click <b>Add</b>, or press <kbd>Enter</kbd>. Existing usernames are offered as you type, from a list refreshed once a day, so a very new colleague might not appear yet and can still be typed in full. A share can go to up to 50 recipients.',
          'Adjust the <b>Table name for recipients</b> if you like (it defaults to the source table’s name).',
          'Click <b>Share</b>. The copy runs in the background — each person is notified when their copy is ready, and every outcome lands in your notifications.'
        ],
        callout: {
          kind: 'warning',
          text: 'If a recipient already has a table with that name (or leftover files where it would go), that recipient’s share fails with a notification — nothing is overwritten. The others still go through.'
        }
      },
      {
        id: 'share-table-to-a-space',
        title: 'Share with a shared space',
        subtitle: 'Put a copy of a table in a team’s database.',
        intro:
          'A table can be shared into a shared space’s database as well as to a person, and one share can go to both. Everyone in the space can then query the copy.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, hover over the table, open its <b>⋮</b> menu and choose <b>Share table</b>.',
          'Under <b>Share with</b>, choose <b>Shared spaces</b>, type a space’s name in <b>Space names</b> and click <b>Add</b>. The spaces you belong to are offered as you type, and you can share to a space you’re not a member of by typing its name in full.',
          'To include people as well, switch back to <b>Users</b> and add their names. The spaces you already added stay.',
          'Click <b>Share</b>. For a shared space its <b>owner</b> is the one notified, and every outcome lands in your notifications.'
        ]
      }
    ]
  },
  {
    id: 'data-explorer',
    label: 'Data Explorer',
    subtitle: 'Point-and-click your way through a table — no SQL required.',
    icon: 'explore',
    guides: [
      {
        id: 'start-exploring',
        title: 'Start exploring a table',
        subtitle: 'Open a table and look at its rows.',
        intro:
          'The <b>Data Explorer</b> is the Query workspace without the SQL: you pick a table, and then filter, sort, group and summarize it by clicking. Each table you open gets its own tab — up to 10 at once — and your tabs are still there when you come back to the Explorer in the same browser tab. Every filter, sort and grouping you set is written as SQL — <b>contains</b> as a <b>LIKE</b>, <b>is one of</b> as an <b>IN</b> — and you can read it under <b>Generated SQL</b>.',
        steps: [
          'Open the <b>Data Explorer</b> tab. Pick a <b>Space</b> — your own is listed under your username, and any shared space you belong to follows it — then choose a table or view from the list.',
          'Already in the <b>Query</b> tab? Hover over a table in the schema rail, open its <b>⋮</b> menu and choose <b>Explore data</b> to open it here.',
          'Got a query result you want to filter, group or color? Choose <b>Explore in Data Explorer</b> beside <b>Save results…</b> to open that statement here. It runs the statement again, and every column needs its own name — give an expression or a repeated column one with <b>AS</b>.',
          'Use <b>+</b> on the tab strip to explore another table alongside this one, and <b>✕</b> to close one.',
          'The rows show as a table at every screen size. On a narrow screen, scroll it sideways, and select a cell and choose <b>Value</b> from <b>Options</b> to read the whole of it.'
        ],
        callout: {
          kind: 'tip',
          text: 'Opening a table runs a query, and so does every filter, sort or grouping you apply. The line at the bottom tells you what each one scanned, and what this exploration has scanned in total. One still running after <b>30 minutes</b> keeps going in Athena, and keeps scanning, but the Explorer stops waiting for it and says so. When it finishes, its results are saved in your files under <b>system_settings</b> › <b>athenaresults</b>, in a file named after the query ID the message shows.'
        }
      },
      {
        id: 'explore-filter-sort',
        title: 'Filter and sort',
        subtitle: 'Filter by value or by part of a value, and put the rows in order.',
        intro:
          'This is what the Explorer is for. Everything here is a click, and each one rewrites the query underneath and runs it again — so the rows you end up with are the real answer over the whole table, not just over what was on screen.',
        steps: [
          'Click the <b>⋯</b> on a column header to sort it, to filter it, or to hide it with <b>Hide column</b>. The filters read <b>Filter: equals…</b> and so on. A text column offers <b>equals</b>, <b>does not equal</b>, <b>greater than</b> and the other comparisons, <b>contains</b>, <b>does not contain</b>, <b>starts with</b>, <b>ends with</b>, <b>is one of</b>, <b>is not one of</b>, <b>is null</b>, <b>is not null</b>, <b>is empty</b> and <b>is not empty</b>; a number column offers the comparisons, the two list tests and <b>is null</b> / <b>is not null</b>; a date or true/false column offers the comparisons and <b>is null</b> / <b>is not null</b>. <b>Is one of</b> asks for one value per line, with a box each for <b>(empty)</b> and <b>NULL</b>, which a line can’t hold. A column holds one filter at a time, and filters on several columns all apply together.',
          'Choose <b>Filter by value…</b> from a column’s <b>⋯</b> menu, or click a cell and choose it from <b>Options</b>, to see every value the column holds, most common first, with how many rows hold each. <b>NULL</b> and <b>(empty)</b> are listed like any other value. Tick the ones you want, then choose <b>is one of</b> to keep those rows or <b>is not one of</b> to hide them. From <b>Options</b>, the cell you are on starts ticked.',
          'The list follows the filters on the other columns, so it shows only values that are still there. It shows the 1,000 most common, and <b>Search values</b> looks only at those — for a value it doesn’t show, type it with <b>Filter: is one of…</b>. Counting the values runs a query, so it adds to the tab’s scanned total; opening the list again with the same filters is free.',
          "Used to <b>LIKE</b> and <b>NOT LIKE</b>? <b>Contains</b> and <b>does not contain</b> are those, with a <code>%</code> either side of what you type, and <b>starts with</b> and <b>ends with</b> put the <code>%</code> at one end only. They ignore capitals, and a <code>%</code> or <code>_</code> you type is looked for as itself rather than taken as a wildcard, so for a pattern of your own, use the <b>Filter expression</b> box. A <b>LIKE</b> you write there minds capitals: <code>name LIKE 'A%B'</code> matches them exactly, and <code>lower(name) LIKE 'a%b'</code> ignores them. <b>Generated SQL</b> shows each filter written out.",
          '<b>Is one of</b> and <b>is not one of</b> are <b>IN</b> and <b>NOT IN</b>. As in SQL, <b>does not contain</b>, <b>does not equal</b> and <b>is not one of</b> leave out every row where the column is <b>NULL</b>. <b>Is one of</b> can keep those rows: tick <b>NULL</b>.',
          'Open <b>Options</b> and choose <b>Order and filter</b> for everything at once: several sorts in priority order, several filters, and which columns are hidden or pinned. It applies as one change.',
          'Open <b>Options</b> and choose <b>Columns</b> to hide, show, pin or reorder columns. <b>Show all</b> brings back every hidden column and <b>Unpin all</b> unpins every pinned one; a column you moved stays where you put it.',
          "Type your own condition in the <b>Filter expression</b> box and click <b>Apply expression</b> when the menus can’t say it — two columns compared with each other, or an <b>OR</b> between conditions on different columns, such as <code>state = 'NY' OR city = 'Boston'</code>. Leave out the word <b>WHERE</b>.",
          'Every column filter, whether you set it from a column’s menu or in <b>Order and filter</b>, shows as a chip under the <b>Filter expression</b> box. The chips and the expression all apply together, and a chip’s <b>×</b> removes just that filter.',
          'Use <b>‹ Back</b> and <b>Forward ›</b> on the bar to step back and forward through earlier versions of this query, or choose <b>Remove all filters and sorts</b> from <b>Options</b> to start over. It clears the filter expression too, and while you are grouping it reads <b>Remove all filters, sorts and grouping</b>.',
          'In a table built from CSV files a blank cell is empty text, shown as <b>(empty)</b>, and it is not the same as <b>NULL</b>. <b>Is empty</b> finds both; <b>is null</b> finds only the NULLs, so it is the one that comes back with nothing on a table like that.',
          'In a table built from CSV files every column is text, so <b>greater than</b>, <b>less than</b> and sorting compare the values as text: <b>9</b> comes after <b>10</b>. To compare them as numbers, use a <b>Filter expression</b> such as <code>TRY_CAST(amount AS double) > 100</code>.'
        ],
        callout: {
          kind: 'warning',
          text: 'Every apply runs a real query and scans data, which is what it costs. The line at the bottom shows what the last one scanned and the running total for the tab — that figure is the cost signal, so watch it on a large table. Paging through results is free, and re-applying something you have already run in this tab is too: it says so rather than scanning again. <b>Filter by value…</b> counts a column’s values with a query of its own, and its list says what that scanned.'
        }
      },
      {
        id: 'explore-group-and-calc',
        title: 'Group rows, and add up a selection',
        subtitle: 'Two ways to summarize — one asks the database, one doesn’t.',
        intro:
          'These two panels look alike and work very differently, and it is worth knowing which is which. <b>Grouping</b> asks the database a new question. <b>Calc</b> adds up the cells you have highlighted, right here in your browser.',
        steps: [
          'Open <b>Options</b> and click <b>Grouping</b>, then choose the columns to group by and what to work out for each group — a count, a sum, an average, a minimum or a maximum. You can also drag a column header onto the panel.',
          'Tick <b>Show percentage of the total on this page</b> to add a share-of-total column beside the first figure. It is worked out from the rows on the page, and the column header says so.',
          'Click <b>Apply grouping</b>. Grouping is a query like any other — it runs, and it scans. <b>Stop grouping</b> takes you back to the rows.',
          'For a quick total instead, drag across some cells and pick <b>Calc</b> from <b>Options</b>. It shows <b>Count</b> and <b>Count distinct</b> for exactly what you selected; tick others under <b>Functions</b> — <b>Sum</b>, <b>Average</b>, <b>Minimum</b>, <b>Maximum</b>, <b>Median</b>, <b>Mode</b> or <b>Count nulls</b>.',
          'Pick <b>Value</b> from <b>Options</b> to open a panel showing the full contents of the cell you are on — useful when a value is too long for its column.'
        ],
        callout: {
          kind: 'tip',
          text: '<b>Calc</b> runs no query at all, so selecting different cells costs nothing. It describes the cells you selected on the page in front of you — never the whole result. <b>Grouping</b> is the one that covers every row.'
        }
      },
      {
        id: 'explore-colors-and-formats',
        title: 'Color cells and change how values are shown',
        subtitle: 'Highlight what matters, and show a column as rounded numbers, codes or links.',
        intro:
          'Two dialogs change what the page looks like and nothing else. <b>Colors</b> tints values, bands rows and highlights cells by what they hold; <b>Transformers</b> changes how a column’s values are written. Both work on the rows already in your browser, so neither one runs a query or costs anything, and each tab keeps its own.',
        steps: [
          'Open <b>Options</b> and choose <b>Colors</b>. Tick <b>Color values by their data type</b> to tint each value by its type, so numbers, dates and true-or-false values stand apart from plain text.',
          'Under <b>Band rows by</b>, tick the column or columns that tie rows together — an order number, say. Each run of rows with the same values in all of them becomes a band, and every other band is shaded. Bands are worked out from the rows on this page.',
          'Click <b>Add rule</b> and choose the column it tests, or <b>Any column</b> to test every cell in the row. Then pick a test and type its value: <b>equals</b>, <b>does not equal</b>, <b>greater than</b> and the other comparisons; <b>matches (% and _)</b>, where <code>%</code> stands for any run of characters and <code>_</code> for one, and the whole value has to match; <b>matches, ignoring case</b>, the same without minding capitals; or <b>matches a pattern</b>, which looks for a regular expression anywhere in the value. <b>Is empty</b> and <b>is not empty</b> need no value, and a <b>NULL</b> cell matches only <b>is empty</b>.',
          'Choose <b>Paint the matching cells</b> or <b>Paint the whole row</b>, then a text color, a background, or both — <b>No change</b> leaves that one as it was. To shade by size instead, tick <b>Shade a number range</b>, type the two ends of the range and pick a tint for each; a value that isn’t a number is left alone.',
          'Rules run in order, and a later one wins where two set the same thing. Use <b>↑</b> and <b>↓</b> to move a rule and <b>Remove</b> to delete one, then click <b>Apply</b> — nothing changes until you do.',
          'Open <b>Options</b> and choose <b>Transformers</b> to change how a column is written. Every column starts <b>As it is</b>. <b>Number</b> rounds to the decimal places you give; with <b>Leave non-numbers alone</b> ticked a value that isn’t a number shows as it is, and without it shows <b>#ERR</b>. <b>Encoded</b> writes the value out as <b>Hex</b> or <b>Base64</b>, cut short with <b>…</b> past the length you set.',
          'Choose <b>Link</b> to turn a column’s values into links. Type the web address with <code>${value}</code> where the cell’s value goes, such as <code>https://example.com/orders/${value}</code>, or just <code>${value}</code> when the column already holds web addresses. Clicking a cell opens its link in a new browser tab. Only <b>https</b> links open: any other cell stays plain text, and hovering over it says why. From the keyboard, select the cell and open <b>Value</b> from <b>Options</b> to follow its link.',
          'Click <b>Apply</b> when you’re done — nothing changes until you do.'
        ],
        callout: {
          kind: 'tip',
          text: 'A transformer changes only how a value looks. Filters, colors, <b>Calc</b> and copying all still use the value itself, and so does <b>Save results…</b> — so a color rule on a <b>Number</b> column tests the value before it was rounded.'
        }
      },
      {
        id: 'explore-copy-and-export',
        title: 'Copy or save what you found',
        subtitle: 'Copy a selection to the clipboard, or export every row to a file.',
        intro:
          'Two ways out, for two different jobs. <b>Copy</b> takes the cells you have selected on the page. <b>Save results…</b> saves every row the query returned as a file in your files, where you can download it — and neither one runs another query.',
        steps: [
          'Select some cells and press <kbd>Ctrl/Cmd + C</kbd> to copy them as plain columns you can paste straight into a spreadsheet.',
          'Pick <b>Copy…</b> from <b>Options</b> instead to choose a format — <b>Tab-separated (for spreadsheets)</b>, <b>CSV</b>, <b>JSON</b>, a <b>Markdown table</b>, a <b>SQL INSERT</b> or <b>XML</b> — and whether to <b>Include column names</b>, <b>Include row numbers</b> or <b>Quote values</b>.',
          'Click <b>Save results…</b> beside the pager (it is in <b>Options</b> too) to save every row the query returned. Type a <b>File name</b>, then choose where it goes under <b>Save to</b> and <b>Destination folder</b>.',
          '<b>The file holds the result columns the grid is showing, in the order it shows them.</b> Hide a column, or move one, and it is saved that way — the dialog says how many columns it is about to write. Showing everything again, in the original order, saves the whole result as before. A column worked out in your browser, such as the <b>percentage</b> a grouping adds, is not part of the results and is never in the file.',
          'With every column of the results shown in its original order, the file is saved as CSV straight away — the button reads <b>Save here</b>. Hide or move one of those and there is no file to copy, so it is converted instead: the button reads <b>Convert and save</b>, and a <b>notification</b> tells you when the file is ready. Hiding a column worked out in your browser changes nothing, because it was never going into the file.',
          'If a file of that name is already there you are asked before anything is replaced.'
        ],
        callout: {
          kind: 'warning',
          text: 'Copy only takes the rows loaded on the page you are looking at — selecting a column header selects that page, not the whole table. <b>Save results…</b> is the one that saves every row. And if your selection has gaps in it, the copy comes out as one rectangle with the cells in between left blank.'
        }
      },
      {
        id: 'explore-save-formats',
        title: 'Save an exploration as Parquet, JSON or Excel',
        subtitle: 'Choose the file format when you save every row.',
        intro:
          '<b>Save results…</b> can write more than CSV. The other formats are converted in the background and arrive as a notification.',
        steps: [
          'In <b>Save results…</b>, pick a <b>Format</b>: <b>CSV</b>, <b>Parquet</b>, <b>JSON</b> or <b>Excel</b>. The file extension follows the format you pick.',
          '<b>Parquet</b>, <b>JSON</b> and <b>Excel</b> are always converted: the button reads <b>Convert and save</b>, and a <b>notification</b> tells you when the file is ready.',
          'Whichever format you pick, the file holds the result columns the grid is showing, in the order it shows them.'
        ],
        callout: {
          kind: 'tip',
          text: '<b>Parquet</b> is the one to build a table from, and of the converted formats it takes the largest results, up to about 1.4 GB. <b>JSON</b> is written one object per line. <b>Excel</b> takes results up to 64 MB and about a million rows, fewer when the results are wide, and stores numbers approximately, so long decimals may be rounded.'
        }
      },
      {
        id: 'explore-save-as-query',
        title: 'Save an exploration as a query',
        subtitle: 'Keep the SQL the Explorer wrote for you, as a saved query or a view.',
        intro:
          'Everything you click here builds a real SQL statement, and you can see it and keep it. Open <b>Generated SQL</b> at any time to read exactly what is about to run — a good way to learn the SQL for something you have just built by hand.',
        steps: [
          'Open <b>Generated SQL</b> above the rows to see the statement your filters, sorting and grouping produced.',
          'Choose <b>Open in Query</b> there, or from <b>Options</b>, to copy the statement into a new <b>Query</b> tab, where you can edit it and run it. It doesn’t run until you do, and changes you make there don’t come back to this exploration. On a phone it opens read-only, ready to run.',
          'Pick <b>Save as query</b> from <b>Options</b> to keep it. Give it a name and choose the space to save it in, and it is written to that space’s <b>saved_queries</b> folder as a <b>.sql</b> file. Exploring a table, the file also records your filters, sorting, grouping, column layout, colors and transformers.',
          'To pick up where you left off, click <b>+</b> on the tab strip, choose <b>Open saved view</b>, then <b>Open</b> the file. Everything comes back as you left it, ready to change.',
          'A view saved in a shared space opens without running, because anyone in that space can change the file. Check its <b>Generated SQL</b>, then choose <b>Run</b>. Its link columns and pattern color rules are left out, and the tab says so.',
          'Or pick <b>Create view…</b> from <b>Options</b> to keep it as a <b>view</b> in that space instead — a view already there under that name is replaced. A view behaves like a table — it turns up in the <b>Data Explorer</b> and the <b>Query</b> tab for anyone who can see that space, and it re-runs your query each time it is read.'
        ],
        callout: {
          kind: 'tip',
          text: 'The same file opens in the <b>Query</b> tab from <b>Saved queries</b>, as SQL you can edit. Once its SQL has been edited there — or if it was saved from <b>Query</b>, or from an exploration of a <b>Query</b> result — it opens only in <b>Query</b>.'
        }
      }
    ]
  },
  {
    id: 'shared-connections',
    label: 'Shared spaces',
    subtitle: 'Spaces you share with teammates — files and tables, together.',
    icon: 'connections',
    guides: [
      {
        id: 'create-shared-connection',
        title: 'Create a shared space',
        subtitle: 'Make a space several people can share.',
        intro:
          'A shared space is one that more than one person can work in — the same files and the same tables, visible to everyone you invite. It’s how you collaborate here. You always start out as the owner and the only member; you bring others in afterwards.',
        steps: [
          'On the <b>Shared spaces</b> tab, click <b>New shared space</b> — just <b>New</b> in a narrower window.',
          'Enter a <b>Space name</b>: 3 to 63 characters of lowercase letters, digits or underscores, starting with a letter.',
          'Click <b>Create</b>. It appears in your list straight away as <b>Provisioning…</b>, turns <b>Active</b> once it’s set up in the background, and you get a notification when it’s ready.',
          'If it can’t be set up, the row says why, with <b>Retry</b> to try again.'
        ],
        callout: {
          kind: 'tip',
          text: 'Choose the name carefully — it’s permanent, must be unique across every space, can’t be renamed later, and can’t be reused even if the space is deleted. You can belong to at most 10 shared spaces, counting the ones you own. You’ll start the space on your own; add people whenever you’re ready with <b>Add members</b>.'
        }
      },
      {
        id: 'use-shared-space-files',
        title: 'Work in a shared space’s files',
        subtitle: 'Open a space’s files and add to them.',
        intro:
          'A shared space has its own files, separate from yours, and everyone in the space sees the same ones. Anything you upload or change there, every member can see and change too.',
        steps: [
          'Open the <b>Files</b> tab. The <b>Spaces</b> list on the left shows your own space, under your username, and every shared space you belong to. On a phone or in a narrow window, it’s in the <b>☰</b> menu.',
          'Click a space to open its files. Uploading, folders, moving, copying and deleting all work the same way there as in your own space.',
          'If you were only just added, the space may say <b>Applying your access…</b>. Click <b>Refresh access</b> to pick it up without signing out.',
          'Opening the space is also what turns you from <b>Pending</b> to <b>Active</b> on the owner’s member list.',
          'A space that is still being set up is listed but can’t be opened until it’s ready.'
        ]
      },
      {
        id: 'add-members',
        title: 'Add members',
        subtitle: 'Give other people access to a space you own.',
        intro:
          'Ready to bring your team in? As the owner, you can add members at any time, and each one gets access to all the shared files and tables in the space.',
        steps: [
          'Open <b>Manage</b> on a space you own, then click <b>Add members</b>.',
          'Start typing in <b>Usernames</b> — existing usernames are offered as you type. Pick one, or press <kbd>Enter</kbd> to add the name you typed. You can also paste several at once, separated by spaces, commas, or new lines.',
          'Click <b>Add</b> once you have everyone. They all get access to the same shared files and tables, and each of them gets a notification.',
          'Someone who is already signed in may not see the space straight away. Clicking the refresh button on their <b>Shared spaces</b> tab, or <b>Refresh access</b> when they open the space in <b>Files</b>, brings it in without signing out.',
          'If the change can’t go ahead, you’ll get a notification telling you it didn’t go through.'
        ],
        callout: {
          kind: 'tip',
          text: 'The suggestion list is refreshed once a day, so someone very new might not appear in it yet — you can still type their name and add them. If a name turns out not to belong to anyone, or that person is already in 10 shared spaces, <b>you</b> get a notification saying so, and the rest of the people you added are unaffected.'
        }
      },
      {
        id: 'member-status',
        title: 'See who has access and their status',
        subtitle: 'Check the member list and each person’s join status.',
        intro:
          'Wondering who’s in a space and whether they’ve found their way to it yet? The member list shows everyone, with a status next to each person so you can tell who has actually opened the space.',
        steps: [
          'If you own the space, open <b>Manage</b>; if you’re a member, open <b>View members</b> — either one shows the full member list (read-only for members).',
          'Each member shows <b>Active</b> once they’ve opened the space in <b>Files</b>, or <b>Pending</b> until they do. The owner is marked <b>Owner</b>.',
          'Click the refresh button at the top of the list to pull in the latest statuses.'
        ],
        callout: {
          kind: 'tip',
          text: 'Pending vs Active only reflects whether someone has opened the space yet — their access is granted the moment you add them, not when they first show up — though someone already signed in may need to refresh before they can reach the space.'
        }
      },
      {
        id: 'remove-members',
        title: 'Remove a member',
        subtitle: 'Revoke someone’s access to a space you own.',
        intro:
          'If someone no longer needs to be in a space, you can remove them as the owner. Nothing they contributed goes away.',
        steps: [
          'In the <b>Manage</b> member list, click <b>Remove</b> next to a member and confirm.',
          'They lose access, but the shared files and tables stay put. The owner can’t be removed — transfer the space first if the owner is the one leaving.',
          'Access does not end the instant you confirm. Their permissions were issued when they signed in, so someone already signed in can keep using the space — changing and deleting its files included — until their session refreshes, up to about an hour. If that matters, ask them to sign out.',
          'They get a notification saying they’ve been removed.',
          'If the removal can’t go ahead, you’ll get a notification telling you it didn’t go through.'
        ]
      },
      {
        id: 'transfer-ownership',
        title: 'Hand a space to someone else',
        subtitle: 'Make another member the owner.',
        intro:
          'A space belongs to whoever created it — until you hand it on. If a project changes hands, or you’re moving on, you can make any existing member the owner instead. Nothing about the space itself changes: same files, same tables, same members.',
        steps: [
          'On a space you own, open <b>Manage</b> to see its members.',
          'Click <b>Make owner</b> next to the person you want to hand it to, and confirm with <b>Transfer</b>.',
          'They become the owner. You stay a member, keeping access to everything in the space — you just can’t add or remove members, or delete it, any more.'
        ],
        callout: {
          kind: 'tip',
          text: 'You can only transfer to someone who is already a member, so add them first if you need to. Once it’s done, only the new owner can transfer it back.'
        }
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
        subtitle: 'Remove a space you own from everyone’s list.',
        intro:
          'When a shared space has served its purpose, the owner can delete it. This is the big one — it ends everyone’s access at once, including your own, so it asks you to confirm by name first.',
        steps: [
          'On a space you own, choose <b>Delete</b>.',
          'Type the space’s name to confirm you mean it, then click <b>Delete</b>.'
        ],
        callout: {
          kind: 'warning',
          text: 'Deleting removes the space for everyone — every member loses access, you included, and it disappears from everyone’s list. Its files and tables are kept by administrators rather than destroyed, so ask one of them if you delete a space by mistake. The name can never be used for a new space.'
        }
      }
    ]
  },
  {
    id: 'notifications',
    label: 'Notifications',
    subtitle: 'How Data Quarry keeps you posted on activity.',
    icon: 'notifications',
    guides: [
      {
        id: 'find-notifications',
        title: 'Find your notifications',
        subtitle: 'Know when something needs your attention.',
        intro:
          'Some things in Data Quarry happen in the background — a table being built, results being exported, changes to a shared space. Notifications are how Data Quarry taps you on the shoulder when one of those finishes or needs you.',
        steps: [
          'Look for the <b>bell</b> in the top bar. In a wider window it has the word <b>Notifications</b> beside it.',
          'A number on the bell shows how many are unread, up to <b>9+</b>.',
          'Click it to open your notifications.'
        ]
      },
      {
        id: 'read-notifications',
        title: 'Read your notifications',
        subtitle: 'Browse your recent notifications.',
        intro:
          'The Notifications page lists your 200 most recent notifications — about your shared spaces and background jobs like table builds — with the newest at the top.',
        steps: [
          'The <b>Notifications</b> page lists them newest first, 10 per page.',
          'Switch between <b>All</b> and <b>Unread</b>, and use <b>Prev</b> / <b>Next</b> to page through them.',
          'Many messages are links: click one to go straight to the folder, table or report it’s about.',
          'The page doesn’t update by itself, so click the refresh button at the top to check for new ones.'
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
          'The notification and the unread count on the bell both update right away.'
        ],
        callout: {
          kind: 'tip',
          text: 'Notifications can’t be deleted — marking one read simply clears its unread marker. It stays in your list until newer ones push it out, since the 200 most recent are kept.'
        }
      }
    ]
  },
  {
    id: 'getting-around',
    label: 'Getting around',
    subtitle: 'Move between pages and choose how Data Quarry looks.',
    icon: 'getting-around',
    guides: [
      {
        id: 'move-between-pages',
        title: 'Move between pages',
        subtitle: 'Find each part of Data Quarry, on any screen.',
        intro: 'Everything in Data Quarry is a click or two from the top bar, whatever size your screen is.',
        steps: [
          'In a wider window, the tabs along the top bar take you to each part of Data Quarry.',
          'On a phone or in a narrow window the tabs fold away. Tap <b>☰</b> at the left-hand end of the top bar to open the menu, which also holds <b>Notifications</b> and <b>Help</b>.',
          'Click <b>Help</b> in the top bar for the guides. On most pages it opens a panel over the page you’re on, with the guides for that page, so whatever you had half-done stays as it was; <b>Open the full guide</b> brings you here.',
          'The account menu at the right-hand end of the top bar — the round badge with the first two letters of your username — holds <b>Give feedback</b> and <b>Sign out</b>.'
        ]
      },
      {
        id: 'choose-a-theme',
        title: 'Switch between light and dark',
        subtitle: 'Pick how Data Quarry looks, or let it follow your device.',
        intro:
          'A long session with the editor is easier on the eyes in the dark. Choose Light or Dark to fix it, or System to let Data Quarry follow whatever your computer or phone is set to — so it turns dark in the evening if your device does.',
        steps: [
          'Click <b>Theme</b> in the top bar and choose <b>Light</b>, <b>Dark</b>, or <b>System</b>. In a narrow window the word goes and its half-filled circle stays.',
          'It is in the same place at every screen size, phone included — there is no separate control to find on a small screen.',
          'The change applies straight away, and the editor, the results grid and every other screen follow it.'
        ],
        callout: {
          kind: 'tip',
          text: 'The choice is remembered in this browser, not on your account — so signing out keeps it, and signing in on another computer starts again from System.'
        }
      }
    ]
  },
  {
    id: 'feedback',
    label: 'Give feedback',
    subtitle: 'Tell us what is working, what is not, and what you wish Data Quarry did.',
    icon: 'feedback',
    guides: [
      {
        id: 'send-feedback',
        title: 'Send us feedback',
        subtitle: 'Report a problem, suggest an idea, or ask a question.',
        intro:
          'Everything else in Data Quarry tells us what you <b>clicked</b>. This is the only place that tells us what you <b>wanted</b> — so if something is awkward, missing, or just wrong, this is the fastest way to say so.',
        steps: [
          'Open the account menu — the round badge with the first two letters of your username, followed by a <b>⋮</b>, at the right-hand end of the top bar; in a wide window your username sits between them — and choose <b>Give feedback</b>. <b>Sign out</b> is in the same menu, which is there at every screen size.',
          'Pick <b>What is this about?</b> — <b>Something is broken</b> for a problem, <b>An idea or a request</b> for something you would like, <b>A question</b> when you are unsure how something works, and <b>Something else</b> for anything that fits none of those.',
          'Write your feedback. The more specific the better — what you were doing, what you expected, and what happened instead.',
          'Click <b>Send</b>. The page you were on when you opened the dialog is included automatically, so you do not need to describe where you were.'
        ],
        callout: {
          kind: 'tip',
          text: 'We read everything that comes through, but <b>this is not a support channel and you will not get a reply here</b>. If you need an answer to something, contact the Administrator.'
        }
      }
    ]
  }
];
