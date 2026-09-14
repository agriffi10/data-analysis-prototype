import type {HelpSection} from './help.types';

// MAINTENANCE NOTE.
// This content describes only the portal behavior that is shipped and reachable
// by users as of implementation: Files (incl. background file operations and their
// conflict round trip, running a data-quality check and
// reading its report), Query, Tables (create-from-folder + share,
// the table planes), Shared connections (incl. join status pending/active
// join status), and Notifications. Every step below maps to a real, wired
// affordance in the code.
//
// The data-quality guides now cover the whole loop: starting a check from EITHER
// entry point (Files, or Data quality → New quality check), the
// notification that reports it, the report itself, and browsing past
// checks from the Data quality tab. The guides say a failure reports itself in
// notifications, with no adverb. "usually" went when the drain began sweeping every
// control plane's request DLQ back into notifications, since a request that never
// started an execution had notified nobody; "always" overclaims, because an
// uncatchable Step Functions error ends the execution without reaching the failure
// notifier. The data-quality page's footer note carries the long form.
// When a feature is added, changed, or removed, revisit this file so the guides
// never promise behavior that isn't shipped — the post-spec ritual in
// docs/process/completion-ritual.md includes a check for exactly this.
//
// ONE GUIDE COVERS RENAME, MOVE, COPY AND DELETE, and it cannot be gated. The conflict guide
// beside it follows the async switchover, because a refusal round trip only exists while the
// routing does — but the four verbs themselves work in either state, so gating their one guide
// would leave the core of the Files section undocumented whenever the kill switch is thrown. The
// accepted cost, stated rather than hidden: with that switch off, this guide's background-operation
// paragraph overstates for as long as it stays off.

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
          'Everything starts here — getting your files into Data Quarry. Uploads always land in the folder you’re currently viewing, so browse to where you want them first, then drop them in. Big files are welcome; the panel keeps you posted on each one.',
        steps: [
          'Open the <b>Files</b> tab and browse to the folder you want to upload into.',
          'Click <b>Upload</b> to open the upload panel.',
          'Drag files onto the drop zone, or click it to pick files from your computer.',
          'Each file uploads into the current folder, and the panel tracks its progress until it’s done.',
          'Small files upload in one go. Large ones are sent in pieces, so if your connection drops partway only the piece in flight is sent again rather than the whole file — you may see the progress bar pause while it catches up.',
          'If a file does fail, the panel marks it <b>Failed</b> and nothing is saved: an upload that never finishes leaves no file behind for you to find or tidy up. Drop it in again to retry. Pieces from an interrupted upload are cleaned up automatically within a few days.'
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
          'Plans change, and so does how you want your files arranged. Tick items for a bulk toolbar, or open a single item’s details to rename it. A single file is done straight away. Whole folders work too, and because a folder can hold thousands of files Data Quarry does those in the background while you carry on.',
        steps: [
          'Tick the checkbox on one or more items — a toolbar with <b>Copy</b>, <b>Move</b>, and <b>Delete</b> appears.',
          'For <b>Move</b> or <b>Copy</b>, pick a destination folder, then confirm with <b>Move here</b> or <b>Copy here</b>.',
          'To <b>Rename</b> a single item, click <b>Details</b> on its row and choose <b>Rename</b>, then type a <b>New name</b> — a file keeps its original extension automatically.',
          'A single file is done straight away. <b>Anything else — a folder, or more than one item — is handed to Data Quarry to do in the background.</b> You get a note that it has been requested, an entry in the in-progress list, and a notification when it finishes.',
          'While one of those is running, anything else in that space that would also run in the background — another folder or multi-item <b>Copy</b>, <b>Move</b> or <b>Delete</b>, and <b>Archive</b> — is unavailable and says so. Nothing is queued, so start it again once the first has finished. Single files are unaffected, and the file list does not update by itself either: press <b>Refresh</b>, or leave the tab and come back.',
          'If Data Quarry’s background service is unavailable, a folder Copy, Move or Delete is refused and says so — the files you picked alongside it still go through, and the message names the folders that did not. Try those again later.',
          'The folders Data Quarry fills for you are gathered under <b>system_settings</b>, sorted in among your own folders — <b>athenaresults</b>, where your query results are kept, and your <b>archive</b> receipts. Click it to open it up, and browse what is inside as normal. Both are managed for you, so neither can be deleted or moved. Tables shared with you stay in <b>shared_tables</b> at the top level, because they are yours to work with.'
        ],
        callout: {
          kind: 'warning',
          text: 'Deleting is forever — there’s no version history or trash, so a deleted file or folder is gone for good. A background delete can also <b>partly</b> succeed: some items go and others are kept back, and the notification names each one. To keep you safe, the confirm dialog starts on <b>Cancel</b>, so a stray Enter key won’t delete anything.'
        }
      },
      {
        id: 'resolve-file-operation-conflicts',
        title: 'When a move or copy is refused',
        subtitle: 'Something was already in the way — here is how to finish the job.',
        intro:
          'A background move or copy never quietly writes over your files. If something with the same name is already at the destination, that item is left exactly where it was and the rest of the request goes ahead. The notification tells you which ones, and you can settle them from there.',
        steps: [
          'Open the notification for the operation. Alongside the message there is a <b>Review conflicts</b> link.',
          'The review lists the items that could not be placed, with a sample of what is already in the way.',
          'For a rename, choose <b>Use a different name…</b> and type a name that is free. Nothing is written over, and the request is sent again for that item only.',
          'Otherwise choose <b>Overwrite…</b>, read the confirmation, and confirm. Only the items that were refused are sent again — the rest already happened.',
          'You get a fresh notification for the second request, the same as the first.'
        ],
        callout: {
          kind: 'warning',
          text: 'Overwriting <b>cannot be undone</b>: there is no version history and no trash here, so whatever was at the destination is replaced for good. Renaming is the safe way out, and it is what most people want. Anything created at the destination after you first asked is left alone either way.'
        }
      },
      {
        id: 'send-files',
        title: 'Send files to someone',
        subtitle: 'Hand files or folders to another person or a shared space.',
        intro:
          'Sometimes the quickest way to share something is to give someone a copy of it. Select what you want, pick who gets it, and Data Quarry copies it into their space in the background — you keep your originals, and you hear back about each recipient.',
        steps: [
          'In the <b>Files</b> tab, tick one or more items — files, folders, or a mix — and click <b>Send to…</b>.',
          'Choose <b>Users</b> or <b>Shared spaces</b>, then type one or more names. Names are suggested as you type, and a name that isn’t suggested is still allowed — it’s checked when the request is sent.',
          'Click <b>Send</b>. The copy runs in the background, so you can carry on working.',
          'What you sent lands under <b>shared_files</b> → your username in their space. A person you sent to gets a notification with a link straight to it; for a shared space, its <b>owner</b> is the one notified.'
        ],
        callout: {
          kind: 'tip',
          text: 'A send is a <b>copy</b>, and it never overwrites: you keep yours, the recipient isn’t asked to accept, and if they already have something you sent under the same name that recipient is refused — the notification tells you which item it was, so you can rename it and send again.'
        }
      },
      {
        id: 'archive-files',
        title: 'Archive and restore files',
        subtitle: 'Move files you rarely need into long-term storage, and bring them back later.',
        intro:
          'Archiving takes files or folders out of your space and stores them cheaply for the long term. It is the one action here that <b>removes your data from this space</b> — the copy is kept safely, but it is no longer in your file list, and getting it back is not instant. Use it for things you want to keep but do not expect to open again soon.',
        steps: [
          'In the <b>Files</b> tab, tick one or more items and click <b>Archive</b> — or open a single item’s <b>Details</b> and choose <b>Archive</b> there.',
          'Read the confirmation. It names what will go, and says plainly that these files leave this space.',
          'Click <b>Archive</b>. The work happens in the background, and a notification tells you when it has finished — including the <b>archive id</b> you will need to get it back.',
          'Every archive also leaves a folder under <b>system_settings</b> → <b>archive</b> in your space, named after its id, holding a receipt you can download and read.',
          'To bring an archive back, click <b>Restore Archived Data</b> in the <b>Files</b> tab, paste the archive id, and click <b>Restore</b>. Everything comes back where it was. In a narrow window that first button moves to a bar along the bottom and says just <b>Restore</b>.',
          'A restore takes <b>several hours</b> — the files have to be retrieved from long-term storage first. You get one notification when it starts and another when it is done.'
        ],
        callout: {
          kind: 'warning',
          text: 'A restore puts every file back where it came from, and it refuses to overwrite anything: if even one of those files exists again, <b>nothing</b> is restored and the notification names the files in the way. Move, rename or delete them and request the restore again. The <b>archive</b> folder itself — under <b>system_settings</b> — is read-only: you can open and download receipts, but not upload into it, rename it or delete it.'
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
          'There are two ways in. From <b>Files</b>: tick the checkbox on <b>one</b> file or <b>one</b> folder, then click <b>Check data quality</b> in the toolbar above the list and confirm — the dialog names exactly what will be read.',
          'Or from <b>Data quality</b>: click <b>New quality check</b>, choose the space, then browse to the folder you want checked. Click a file first if you want to check just that one file.',
          'The check runs in the background and can take a few minutes. Carry on working; you don’t have to wait on the page.',
          'When it finishes you’ll get a <b>notification</b> naming what was checked. Click it to open the full report — the findings live there, not in the notification.',
          'The report shows every finding: row and column counts, blank values, columns whose values don’t match their type, repeated rows, and — for a folder — any file whose columns disagree with the rest.',
          'Checking <b>one file</b> reports on that file alone — its neighbours in the same folder are not counted, even though they sit alongside it.',
          'If a source turns out to have <b>no rows at all</b> — an empty or header-only export — the report says so as a finding rather than calling it clean.',
          'If the <b>column names</b> in your data won’t work in Athena — a header like <b>Order ID</b>, or two headers that differ only by case — the check stops and the notification names them. There’s no report in that case: those names are also what would stop a table being readable, so they’re worth fixing before anything else.'
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
          text: 'A row tagged <b>Sampled</b> means some of that check’s figures are estimates rather than exact counts — open the report to see which. A check that <b>failed</b> has no row here, because it never produced a report; it reports itself in your <b>notifications</b> instead — including a request that couldn’t be started at all.'
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
        ],
        callout: {
          kind: 'warning',
          text: 'A query still running after <b>30 minutes</b> keeps going in Athena, and keeps scanning, but the tab stops waiting for it and says so, and <b>Stop</b> is no longer offered for it. When it finishes, its results are saved in your files under <b>system_settings</b> › <b>athenaresults</b>, in a file named after the query ID the message shows.'
        }
      },
      {
        id: 'run-script',
        title: 'Run several statements at once',
        subtitle: 'Write a script of ;-separated statements and run it top to bottom.',
        intro:
          'You don’t have to run statements one at a time. Put several in the editor separated by semicolons — say, a <b>CREATE TABLE</b> followed by a <b>SELECT</b> — and Data Quarry runs them in order, one after another. Each gets its own history entry, and you pick whether you want a single final result or one result per statement.',
        steps: [
          'Write multiple statements in one editor, separated by semicolons.',
          'Open the dropdown next to <b>Run Statement</b> to reach the two whole-script options.',
          'Choose <b>Run Query Tab</b> (<kbd>Ctrl/Cmd + Shift + Enter</kbd>) to run every statement in order and show the last result set.',
          'Or choose <b>Run Multiple Queries</b> (<kbd>Ctrl/Cmd + Alt + Enter</kbd>) to keep every statement’s result in its own tab above the results table.',
          'Statements run one at a time, in order. The status bar shows which one is running (for example “Statement 2 of 4”), and each gets its own history entry.',
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
          'Got a query you’ll want again? Save it and give it a name so it’s a click away next time, instead of retyping it or hunting through your history. A saved query is an ordinary <code>.sql</code> file in a <b>saved_queries</b> folder in a space, so you can find it, download it or delete it like anything else — and saving into a shared space is how you hand a query to the people you work with.',
        steps: [
          'With a valid query in the editor, click <b>Save</b>.',
          'Choose a <b>Space</b> to save it into: your own files, or any shared space available to you. It opens on the space the query came from, or the last one you worked in.',
          'Give it a <b>Name</b> and click <b>Save</b>. Saving always asks — even when you opened the query from a file — so you can see which file, in which space, you are about to write.',
          'The query is written to that space’s <b>saved_queries</b> folder as a <code>.sql</code> file named after the name you gave it. Type <code>report</code>, <code>report.sql</code> or <code>report.SQL</code> and you get the same file.',
          'If a query of that name is already there, you’re asked to confirm before it’s replaced. Names are case-sensitive, so <b>Report</b> and <b>report</b> are two different files.',
          'Saving into a different space than the one your tab came from writes a <i>new</i> file there and leaves the original alone. Your tab then follows the new file.',
          'Everyone with access to that space can open what you saved — a saved query in a shared space belongs to the space, not to you alone.',
          'A small marker on the tab lets you know when your edits have drifted from the file you opened.',
          'The <b>saved_queries</b> folder itself can’t be deleted or renamed, but everything inside it is yours to manage.'
        ]
      },
      {
        id: 'load-saved-query',
        title: 'Open a saved query',
        subtitle: 'Find a saved query — yours or a colleague’s — and load it.',
        intro:
          'Saved queries live in a <b>saved_queries</b> folder in a space, so opening one starts by choosing which space to look in.',
        steps: [
          'Click <b>Saved queries</b> to open the list.',
          'Choose a <b>Space</b> at the top. Your own files come first, and any shared space available to you is listed after it. Your choice is remembered for the rest of the session.',
          'The list shows the <code>.sql</code> files in that space’s <b>saved_queries</b> folder, in the order the storage returns them, with when each changed and how big it is. Use <b>Prev</b> and <b>Next</b> to page through them.',
          'A count ending in <b>+</b> — like <b>1–10 of 25+</b> — means there are at least that many; pressing Next fetches more.',
          'Click <b>Open</b> to load one into a new tab. Editing it changes only your tab: the file changes when you save, and not before.',
          'Click <b>Delete</b> to remove one. Deleting a query in a shared space removes it for everyone in that space.'
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
          'Want more room? Drag the divider between the editor and the results to any split you like — or, if you would rather not drag, use the small <b>▲</b> and <b>▼</b> buttons on the divider to nudge it a step at a time. Click the divider (or tab to it — it sits just after the editor) and the arrow keys, <b>Home</b> and <b>End</b> move it too. Double-click it to go back to an even split. Where you leave it sticks for the session.'
        ]
      },
      {
        id: 'save-results',
        title: 'Save results to your files',
        subtitle: 'Export a result set back into your files.',
        intro:
          'Results don’t have to stay in the Query tab. Save a query’s output as a file — in your own space or a shared one — and it becomes just another file you can download, share, or even build a new table from. If a multi-statement script failed or you stopped it part-way, the earlier statement’s full result can still be saved, so you don’t have to re-run to get it.',
        steps: [
          'Click <b>Save results to my files</b> in the status bar, beside the run’s status.',
          'Choose a destination space, a file name, and a <b>Format</b>: <b>CSV</b>, <b>Parquet</b>, <b>JSON</b> or <b>Excel</b>. The file extension is added for you.',
          '<b>CSV</b> is saved straight away and a message confirms where it landed. The other three have to be converted first, so the button reads <b>Convert and save</b> and you get a <b>notification</b> when the file is ready — you can close the tab and carry on working.',
          'The whole result set is saved either way — every row, not just the page on screen.'
        ],
        callout: {
          kind: 'tip',
          text: 'Which to choose: <b>CSV</b> and <b>Excel</b> open in a spreadsheet; <b>Parquet</b> is the one to build a table from, and the only one with no size limit worth worrying about; <b>JSON</b> is written one object per line, which is what most tools expect. <b>Excel</b> holds about a million rows at most, and fewer when the results are wide — over that you are asked to save as Parquet instead, and the notification says which limit it reached — and it stores numbers approximately, so very large whole numbers and long decimals may be rounded.'
        }
      },
      {
        id: 'query-on-a-phone',
        title: 'Use Query on a phone',
        subtitle: 'Run your saved queries and read the results on a small screen.',
        intro:
          'On a phone the Query tab drops the SQL editor and becomes a browse-first surface: your saved queries and your history, ready to run. Writing and editing SQL stays a job for a tablet or a desktop, where there’s room for the editor.',
        steps: [
          'Open the <b>Query</b> tab on your phone — it opens on <b>Saved</b>, with <b>History</b> a tap away.',
          'Tap <b>Run</b> on any card to run that query, or <b>View</b> to read its SQL without running it.',
          'Results show one card per row — each card lists every column and its value — with <b>Prev</b> and <b>Next</b> at the bottom to page through them.',
          'Tap <b>Run</b> at the top of the results to run it again, or the back arrow to return to your lists.',
          'Need the schema? Tap the <b>☰</b> at the left-hand end of the top bar — your databases and their tables are in the drawer it opens.',
          'From a table’s <b>⋮</b> menu in that drawer, <b>View data</b> opens the table’s rows in the results view, and <b>View DDL</b> shows how the table was defined.'
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
          'Have a folder full of data files — CSV, JSON, or Parquet — that you’d like to run SQL against? This turns them into a table without moving or copying anything. Data Quarry reads the files where they already sit and builds the table in the background, then it shows up in the <b>Query</b> tab ready to go. One thing to sort out before you start: <b>column names have to be letters, digits and underscores</b>. A header like <b>Order ID</b> or <b>sales-2024</b> will stop the build, and you’ll get a notification naming the columns to fix. Names are also stored in lowercase, so <b>OrderID</b> becomes <b>orderid</b> — and two headers that differ only by case (<b>Total</b> and <b>TOTAL</b>) become one column, which is refused for the same reason. Your files themselves are never rewritten.',
        steps: [
          'In the <b>Files</b> tab, tick the folder whose files you want to query — exactly one, and it has to be a folder rather than a file — then click <b>Create table</b>. <b>If you cannot see Create table, the window is too narrow</b> — the toolbar drops it on small screens, so widen the window or use a larger display for this step. <b>Create table</b> is also unavailable at the top of a space, because a table reads everything below it and the top of a space also holds your query results, saved queries and shared files.',
          'Enter a <b>Table name</b> (lowercase letters, digits, or underscores, starting with a letter).',
          'If your files sit in <b>key=value</b> folders (for example <b>year=2026/month=01/</b>), click <b>Add partition keys</b> and declare each key in order — coarsest first — along with its type and range.',
          'Click <b>Create table</b>. It’s built in the background, and you’ll get a notification when it’s ready — or if something stopped it from being created.'
        ],
        callout: {
          kind: 'tip',
          text: 'Once it’s ready, the table appears in the <b>Query</b> tab under the same space, so you can start writing SQL against it straight away. The table takes its columns from the first file in the folder, alphabetically, so if that file’s columns change later, use <b>Refresh table</b> rather than building it again.'
        }
      },
      {
        id: 'refresh-table',
        title: 'Refresh a table after the files change',
        subtitle: 'Update the table’s columns from the first file in its folder.',
        intro:
          'A table takes its columns from <b>one file: the first in its folder, alphabetically</b>. <b>Refresh table</b> reads the folder’s first file again and updates the table’s column list to match it, so a new column is only picked up once it’s in that file. Add it only to a later file — say, <code>sales_2026_09.csv</code> in a folder that starts with <code>sales_2025_01.csv</code> — and the refresh will say the table is already up to date. To pick it up, add the column to that first file too, then refresh again. <b>In CSV files, put a new column last</b>, in every file that has it: CSV columns are matched by position, not by name, so a column added anywhere else puts older files’ values in the wrong columns. Capital letters sort before lowercase ones, and a file in a subfolder sorts by its full path, so <code>archive/old.csv</code> comes before <code>current.csv</code>. That isn’t always the order the <b>Files</b> tab shows. A refresh never modifies your files, only the table’s definition, and the table stays queryable the whole time.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, open the <b>⋮</b> menu on the table and choose <b>Refresh table</b>.',
          'Check that the folder shown is the one you added files to, then click <b>Refresh table</b>.',
          'The refresh runs in the background. You’ll get a notification saying how many columns were added, retyped or removed, or that the table was already up to date.'
        ],
        callout: {
          kind: 'warning',
          text: 'If a column has <b>disappeared</b> from the folder’s first file, the refresh stops and changes nothing — the notification names the columns and links you back to the dialog. That can also happen when a different file now sorts first (you deleted or renamed the old first file, or added one that sorts earlier) and it’s missing some of the table’s columns. To keep them, add them to the file that now sorts first — in a CSV, in the same position they have in the table — or make the old first file sort first again, then refresh again. To remove them, tick <b>Allow columns to be removed</b> and refresh again. Removing a column breaks any saved query or view that references it, even if other files still have it.'
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
          '<b>Tables with catalog-registered partitions can’t be refreshed</b>, nor can tables built outside Data Quarry or pointing at files outside your space.',
          '<b>The file format can’t change.</b> If the folder’s files are no longer the format the table expects, build a new table over them.',
          '<b>One refresh at a time per table.</b> If a refresh of that table is already running, a second one is refused and changes nothing — wait for the notification from the first, then check whether you still need to refresh again.'
        ]
      },
      {
        id: 'share-table',
        title: 'Share a table',
        subtitle: 'Copy a table into other users’ or shared spaces’ databases.',
        intro:
          'Any table you can browse in the <b>Query</b> schema rail can be shared. Sharing copies the table’s data files into each recipient’s space and creates the table in their database, so they can query it as their own — it’s a one-time snapshot, not a live link.',
        steps: [
          'In the <b>Query</b> tab’s schema rail, open the <b>⋮</b> menu on a table and choose <b>Share table</b> (views can’t be shared).',
          'Pick who to share with — <b>Users</b> or <b>Shared spaces</b> — type one or more names, and click <b>Add</b> (or press <b>Enter</b>). Both kinds suggest as you type: under <b>Users</b>, existing usernames, from a list refreshed once a day, so a very new colleague might not appear yet and can still be typed in full; under <b>Shared spaces</b>, the spaces you belong to. You can share to a space you’re not a member of — just type its name in full. You can mix both kinds in one share.',
          'Adjust the <b>Table name for recipients</b> if you like (it defaults to the source table’s name).',
          'Click <b>Share</b>. The copy runs in the background — each recipient is notified on success, and the outcomes land in your notifications.'
        ],
        callout: {
          kind: 'warning',
          text: 'If a recipient already has a table with that name (or leftover files where it would go), that recipient’s share fails with a notification — nothing is overwritten. The others still go through.'
        }
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
          'The <b>Data Explorer</b> is the Query workspace without the SQL: you pick a table, and then filter, sort, group and summarize it by clicking. Each table you open gets its own tab, and your tabs are still there when you come back.',
        steps: [
          'Open the <b>Data Explorer</b> tab. Pick a <b>Space</b> — your own files, or a shared space you belong to — then choose a table or view from the list.',
          'Already in the <b>Query</b> tab? Open the <b>⋮</b> menu on a table in the schema rail and choose <b>Explore data</b> to open it here.',
          'Use <b>+</b> on the tab strip to explore another table alongside this one, and <b>✕</b> to close one.',
          'Switch between <b>Grid</b>, <b>Record</b> and <b>Text</b> with the <b>Presentation</b> control — <b>Record</b> shows one row at a time, which is the easier read on a phone.',
          'An apply still running after <b>30 minutes</b> keeps going in Athena, and keeps scanning, but the Explorer stops waiting for it and says so. When it finishes, its results are saved in your files under <b>system_settings</b> › <b>athenaresults</b>, in a file named after the query ID the message shows.'
        ],
        callout: {
          kind: 'tip',
          text: 'Opening a table runs a query, and so does every filter, sort or grouping you apply. The line at the bottom tells you what each one scanned, and what this exploration has scanned in total.'
        }
      },
      {
        id: 'explore-filter-sort',
        title: 'Filter and sort',
        subtitle: 'Narrow the rows down and put them in order.',
        intro:
          'This is what the Explorer is for. Everything here is a click, and each one rewrites the query underneath and runs it again — so the rows you end up with are the real answer over the whole table, not just over what was on screen.',
        steps: [
          'Click the <b>⌄</b> on a column header to sort it, or to filter it with <b>is</b>, <b>is not</b>, <b>greater than</b>, <b>is empty</b> and the rest.',
          'Click a cell, then open <b>Options</b> and choose <b>Filter by this value</b> to filter on what is in it — the quickest way in.',
          'Open <b>Options</b> and choose <b>Order and filter</b> for everything at once: several sorts in priority order, several filters, and which columns are hidden or pinned. It applies as one change.',
          'Type your own condition in the <b>Filter expression</b> box and click <b>Apply expression</b> when the menus can’t say it.',
          'Use the <b>back</b> and <b>forward</b> arrows on the bar to step through the filters you have already tried, or choose <b>Remove all filters</b> from <b>Options</b> to start over.'
        ],
        callout: {
          kind: 'warning',
          text: 'Every apply runs a real query against Athena and scans data, which is what it costs. The line at the bottom shows what the last one scanned and the running total for the tab — that figure is the cost signal, so watch it on a large table. Paging through results is free, and re-applying something you have already run in this tab is too: it says so rather than scanning again.'
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
          'Tick <b>Show percentage of the rows on this page</b> to add a share-of-total column beside the first figure. It is worked out from the rows on the page, and the column header says so.',
          'Click <b>Apply</b>. Grouping is a query like any other — it runs, and it scans.',
          'For a quick total instead, drag across some cells and pick <b>Calc</b> from <b>Options</b>. It shows the count, sum, average, minimum, maximum and more for exactly what you selected.',
          'Pick <b>Value</b> from <b>Options</b> to open a panel showing the full contents of the cell you are on — useful when a value is too long for its column.'
        ],
        callout: {
          kind: 'tip',
          text: '<b>Calc</b> runs no query at all, so selecting different cells costs nothing. It describes the cells you selected on the page in front of you — never the whole result. <b>Grouping</b> is the one that covers every row.'
        }
      },
      {
        id: 'explore-copy-and-export',
        title: 'Copy or save what you found',
        subtitle: 'Take a selection to the clipboard, or the whole result to a file.',
        intro:
          'Two ways out, for two different jobs. <b>Copy</b> takes the cells you have selected on the page. <b>Save results to my files</b> saves every row the query returned as a file in your files — as <b>CSV</b>, <b>Parquet</b>, <b>JSON</b> or <b>Excel</b> — and neither one runs another query.',
        steps: [
          'Select some cells and press <b>Ctrl+C</b> (<b>⌘C</b> on a Mac) to copy them as plain columns you can paste straight into a spreadsheet.',
          'Pick <b>Copy…</b> from <b>Options</b> instead to choose a format — <b>CSV</b>, <b>JSON</b>, a <b>Markdown table</b>, a <b>SQL INSERT</b> or <b>XML</b> — and whether to include column names, row numbers or quotes.',
          'Click <b>Save results to my files</b> beside the pager (it is in <b>Options</b> too) to save the full result. Give the file a name, choose the space and folder, and pick a <b>Format</b>.',
          '<b>CSV</b> is saved straight away — the button reads <b>Save here</b>. <b>Parquet</b>, <b>JSON</b> and <b>Excel</b> are converted first: the button reads <b>Convert and save</b>, and a <b>notification</b> tells you when the file is ready. JSON is written one object per line; Excel holds about a million rows at most, fewer when the results are wide, and stores numbers approximately, so long decimals may be rounded.',
          'If a file of that name is already there you are asked before anything is replaced.'
        ],
        callout: {
          kind: 'warning',
          text: 'Copy only takes the rows loaded on the page you are looking at — selecting a column header selects that page, not the whole table. <b>Save results to my files</b> is the one that saves every row. And if your selection has gaps in it, the copy comes out as one rectangle with the cells in between left blank.'
        }
      },
      {
        id: 'explore-save-as-query',
        title: 'Save an exploration as a query',
        subtitle: 'Keep the SQL the Explorer wrote for you.',
        intro:
          'Everything you click here builds a real SQL statement, and you can see it and keep it. Open <b>Generated SQL</b> at any time to read exactly what is about to run — a good way to learn the SQL for something you have just built by hand.',
        steps: [
          'Open <b>Generated SQL</b> above the rows to see the statement your filters, sorting and grouping produced.',
          'Pick <b>Save as query</b> from <b>Options</b> to keep it. Give it a name and choose the space to save it in, and it is written to that space’s <b>saved_queries</b> folder as a <b>.sql</b> file.',
          'To use it again, open the <b>Query</b> tab and load it from <b>Saved queries</b>.',
          'Or pick <b>Create view…</b> from <b>Options</b> to keep it as a <b>view</b> in the catalogue instead. A view behaves like a table — it turns up in the <b>Data explorer</b> and the <b>Query</b> tab for anyone who can see that space, and it re-runs your query each time it is read.'
        ],
        callout: {
          kind: 'warning',
          text: 'A saved exploration is saved as its SQL, so it opens in the <b>Query</b> tab as a statement you can edit — not back here as an exploration with its filters still in the panels. If you want to carry on exploring, keep the tab open rather than reloading the file.'
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
          text: 'Choose the name carefully — it’s permanent, must be unique across every space, can’t be renamed later, and can’t be reused even if the space is deleted. You’ll start the space on your own; add people whenever you’re ready with <b>Add members</b>.'
        }
      },
      {
        id: 'add-members',
        title: 'Add members',
        subtitle: 'Give other people access to a space you own.',
        intro:
          'Ready to bring your team in? As the owner, you can add members at any time, and each one gets access to all the shared files and tables in the space.',
        steps: [
          'Open <b>Manage</b> on a space you own, then click <b>Add members</b>.',
          'Start typing a <b>Username</b> — existing usernames are suggested as you type. Pick one, or press <b>Enter</b> to add the name you typed. You can also paste several at once, separated by spaces, commas, or new lines.',
          'Click <b>Add</b> once you have everyone. They all get access to the same shared files and tables.',
          'Someone who is already signed in may not see the space straight away — permissions are issued at sign-in, so they may need to sign out and back in.',
          'If the change can’t go ahead, you’ll get a notification telling you it didn’t go through.'
        ],
        callout: {
          kind: 'tip',
          text: 'The suggestion list is refreshed once a day, so someone very new might not appear in it yet — you can still type their name and add them. If a name turns out not to belong to anyone, <b>you</b> get a notification saying so, and the rest of the people you added are unaffected.'
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
          'Each person shows a status: <b>Active</b> once they’ve signed in and opened the space, or <b>Pending</b> until they do.',
          'Click <b>Refresh</b> to pull in the latest statuses.'
        ],
        callout: {
          kind: 'tip',
          text: 'Pending vs Active only reflects whether someone has opened the space yet — their access is granted the moment you add them, not when they first show up — though someone already signed in may need to sign in again before they can reach the space.'
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
          'Access does not end the instant you confirm. Their permissions were issued when they signed in, so someone already signed in can keep reading the space until their session refreshes — up to about an hour. If that matters, tell them to sign out.',
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
          'Click <b>Make owner</b> next to the person you want to hand it to, and confirm.',
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
          'Some things in Data Quarry happen in the background — a table being built, results being exported, changes to a shared space. Notifications are how Data Quarry taps you on the shoulder when one of those finishes or needs you. Look to the bell in the top bar.',
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
          'The Notifications page is the full record of everything Data Quarry has let you know about — your shared spaces and background jobs like table builds — with the newest at the top.',
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
          'Open the account menu — the round badge with the first letters of your username, followed by a <b>⋮</b>, at the right-hand end of the top bar — and choose <b>Give feedback</b>. <b>Sign out</b> is in the same menu, which is there at every screen size.',
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
