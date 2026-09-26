import type {FeatureFlagKey} from './featureFlags.types';

/**
 * One surface a flag controls.
 *
 * The registry test queries every surface by ACCESSIBLE NAME — not a test id and not a CSS
 * class. That is the point of it: a control removed from the DOM and a control still present
 * under a changed label are different bugs, and only an accessible-name query tells them
 * apart. A row's `name` is usually that accessible name, which is what makes it reviewable by
 * someone who has not read the component — `name` says when it is a description instead.
 */
export type GatedSurface = {
  /**
   * The accessible name, where the row is one control or nav item the recipe queries by it;
   * otherwise a description of the surface, where the recipe queries something inside it.
   *
   * Unique across the registry, because it keys the walking test's recipes. That is why one control
   * held under two flags carries its accessible name in one row and a description in the other.
   */
  name: string;
  kind: 'nav' | 'route' | 'control' | 'guide';
  /** Route path for `kind: 'route'`; the owning route otherwise. */
  path: string;
  /**
   * For `kind: 'guide'`, the `helpContent.ts` section or guide id this row hides.
   *
   * The registry is the ONLY home of the guide→flag mapping — `helpContent.ts`
   * knows nothing about flags, so a guide cannot end up gated in the Help list and ungated in
   * the search index, or vice versa.
   */
  helpId?: string;
};

/**
 * Every surface every flag hides, in one place.
 *
 * **THE REGISTRY EXISTS BECAUSE THE TABS ARE THE EASY PART.** "Create table from this folder"
 * lives in the file browser and is a Query feature; "Share table" lives in the Query rail and
 * pushes into Shared Workspaces; "Check data quality" is a button on a file-browser selection.
 * A per-component pass finds three of those and ships the fourth visible — the failure
 * `reviewer-contract.md` records the same finding, which is why this is a registry with a
 * walking test rather than a checklist.
 *
 * Adding a fifth entry point is therefore a registry edit, not a discovery exercise, and
 * `gatedSurfaces.test.tsx` fails for a row whose surface it cannot make disappear.
 *
 * **A flag is presentation, never authorization.** Nothing here revokes a grant; every row
 * removes a way of ASKING for something the user may still do by other means.
 */
export const GATED_SURFACES: Record<FeatureFlagKey, readonly GatedSurface[]> = {
  files: [
    {name: 'Files', kind: 'nav', path: '/files'},
    {name: '/files', kind: 'route', path: '/files'},
    // Signed-in visitors only — the signed-out page gates nothing.
    {name: 'Go to Dashboard', kind: 'control', path: '/'},
    {name: 'Files help section', kind: 'guide', path: '/help', helpId: 'files'},
    // A received-files notification deep-links into /files, and with this flag off
    // that route swaps its element — so an ungated link is a live anchor into the unavailable
    // page. The notification itself is never gated: the record of what happened outlives the
    // surface that would show it.
    {name: 'Received files link on a notification', kind: 'control', path: '/notifications'},
    // A SECOND, SEPARATELY NAMED control on a notification row — not the link gate above, which
    // is a mechanism already registered twice. This one appears only on a notification whose
    // producer named items it could not do, and it goes to a view that lives behind this flag, so
    // it is a surface in its own right and gets a row like any other.
    {name: 'Review conflicts on a notification', kind: 'control', path: '/notifications'},
    // The same control on a notification that carries no usable link, where it falls back to the
    // file browser's root. The message link above is gated first, so only this case reaches the
    // control's own check.
    {name: 'Review conflicts on a notification that carries no link', kind: 'control', path: '/notifications'},
    // The entry point itself. In the FILE BROWSER, like "Check data quality" and
    // unlike "Create table", which is a Query capability wearing a file-browser button.
    {name: 'Send to another user', kind: 'control', path: '/files'},
    {name: 'Send files guide', kind: 'guide', path: '/help', helpId: 'send-files'},
    // Archive is a Files SUB-SURFACE, so with this flag off it goes with the file browser — and
    // it needs THREE rows, because its two entry points are in different places and the restore
    // has no selection at all. The same surfaces are registered again under `archive`, its own
    // kill switch: one row per (surface, flag), because either gate can be deleted alone.
    //
    // Its notification link deliberately gets no row of its own: the `/files` link gate is a
    // mechanism, already registered twice above, and a row per producer would grow one row per
    // future plane for a clause nobody can change independently.
    {name: 'Archive selected items', kind: 'control', path: '/files'},
    // The DETAILS-PANEL entry point, and its own row for the reason the send plane gave its
    // dialog's recipient kind one: the toolbar row renders the toolbar, so nothing would notice
    // if this one stopped being gated. A single item that has not been selected is reachable
    // only here — there is no context menu in this file browser.
    {name: 'Archive this item', kind: 'control', path: '/files'},
    {name: 'Restore Archived Data', kind: 'control', path: '/files'},
    {name: 'Archive and restore guide', kind: 'guide', path: '/help', helpId: 'archive-files'},
    // The VIEW the `Review conflicts` control above opens, and it follows this flag rather than
    // the switchover that created the conflicts. Deliberate: throwing the async kill switch must
    // not strand a conflict raised before it was thrown, and resolving one finishes work the
    // plane already started rather than beginning a new gesture. It is also what keeps that
    // control from becoming a link to nothing.
    {name: 'Review conflicts for a file operation', kind: 'control', path: '/files'},
    // Three controls on OTHER features' screens that navigate into the file browser. Each asks
    // `useCanFollowLink` about its destination, so it follows this flag without naming it.
    {name: 'View source files', kind: 'control', path: '/query'},
    {name: 'View in Files after saving results', kind: 'control', path: '/query'},
    {name: 'Open folder on a data quality report', kind: 'control', path: '/data-quality/:space/:requestId'},
    // Two guides whose every step is on the file browser's screen, though each lives in another
    // flag's section: building a table follows `query` with its section, and working in a shared
    // space follows `sharedWorkspaces` with its. Registered here too, on the precedent of
    // `Explore data on the Query schema rail`, so neither describes a page that is not there.
    {name: 'Create table guide', kind: 'guide', path: '/help', helpId: 'create-table'},
    {name: 'Shared space files guide', kind: 'guide', path: '/help', helpId: 'use-shared-space-files'}
  ],
  query: [
    {name: 'Query', kind: 'nav', path: '/query'},
    {name: '/query', kind: 'route', path: '/query'},
    // In the FILE BROWSER, not the Query workspace. The one everyone forgets.
    {name: 'Create table', kind: 'control', path: '/files'},
    // The SECOND of that kind: a folder row in the file browser that is a Query
    // feature. With `query` off it leaves the listing and the destination picker together —
    // a destination the user cannot see is not a destination. Its delete/rename refusal is
    // NOT part of the gate and is asserted with the flag off, because "you cannot see it"
    // and "you cannot destroy it" are different guarantees.
    {name: 'saved_queries folder', kind: 'control', path: '/files'},
    // Belt to the route's braces: a later spec surfacing these elsewhere inherits the row.
    {name: 'Refresh table', kind: 'control', path: '/query'},
    {name: 'Share table', kind: 'control', path: '/query'},
    // The MIRROR IMAGE of "Create table": a Data Explorer capability living on a
    // Query-workspace surface, so it is gated by both flags and registered under both. With
    // `query` off the whole workspace is gone and the item is unreachable — this row asserts
    // that rather than assuming it, on the same belt-and-braces reasoning as the two above.
    {name: 'Explore data on the Query schema rail', kind: 'control', path: '/query'},
    // The same mirror, on a query result: it opens a Data Explorer tab from the Query workspace,
    // so it is registered under both flags, on the rail item's precedent.
    {name: 'Explore in Data Explorer on a query result', kind: 'control', path: '/query'},
    // The EXACT MIRROR of "Explore data" above: a saved-queries capability living
    // on a Data Explorer surface, so it follows the flag that owns the store rather than the
    // one that owns the screen. With `query` off there is no editor to open a `.sql` file in
    // and the `saved_queries` folder has left both the file browser and the destination
    // picker — writing into it would be a dead end the user cannot see, which is precisely
    // the failure "Create table" is on this list for.
    {name: 'Save as query', kind: 'control', path: '/explore'},
    {name: 'Create view', kind: 'control', path: '/query'},
    // Creating a Glue view is a Query capability wherever the control lives — the twin of
    // `Create view` on the Query workspace's own toolbar. Registered separately because it
    // is a different accessible name on a different route, and the walk is by name.
    {name: 'Create view…', kind: 'control', path: '/explore'},
    // Opening the generated statement in a Query tab lands the user on the Query workspace, so it
    // follows `query` for the reason `Save as query` does: without the flag it leads nowhere.
    {name: 'Open in Query', kind: 'control', path: '/explore'},
    // Reopening a saved view reads the saved-query store, which is hidden with Query off, so the
    // control follows `query` for the reason `Save as query` does.
    {name: 'Open saved view', kind: 'control', path: '/explore'},
    {name: 'Query help section', kind: 'guide', path: '/help', helpId: 'query'},
    // Building a table from a folder is a Query capability wearing a file-browser button, so
    // its guides follow the `query` flag rather than `files`.
    {name: 'Tables help section', kind: 'guide', path: '/help', helpId: 'tables'},
    // Every step past the first is a control this flag hides — Open in Query, Save as query,
    // Open saved view, Create view… — so the guide follows it as well as its own section's flag.
    {name: 'Save an exploration guide under Query', kind: 'guide', path: '/help', helpId: 'explore-save-as-query'},
    // The table builder's "columns removed" notification deep-links into `/query`, and the row's
    // gate is derived from that destination.
    {name: 'Refresh table link on a notification', kind: 'control', path: '/notifications'}
  ],
  sharedWorkspaces: [
    {name: 'Connections', kind: 'nav', path: '/connections'},
    {name: '/connections', kind: 'route', path: '/connections'},
    {name: 'Your spaces navigation', kind: 'control', path: '/files'},
    {name: 'Add members', kind: 'control', path: '/connections'},
    // The recipient-KIND choice, not the dialog: it drops the toggle rather than rendering a
    // one-option control.
    {name: 'Shared spaces', kind: 'control', path: '/query'},
    // The last two are beyond the spec's contract table — see the delivery doc. Hiding the
    // rail alone left both the schema rail and the move/copy WRITE path open.
    {name: 'Shared databases in the schema rail', kind: 'control', path: '/query'},
    // Its own row, and not a duplicate of the one above: that gate filters the
    // CONNECTIONS the rail browses, while this one is the saved-queries space selector,
    // which reads `useQuerySpaces` and would otherwise go on naming a colleague's space in a
    // dropdown after the rest of the app stopped showing it.
    {name: 'Shared spaces in the saved-queries selector', kind: 'control', path: '/query'},
    // A SECOND instance of the same choice, on the same reasoning the send plane used for
    // the send dialog's recipient kind: the row above renders the DRAWER, so nothing would
    // notice if the save dialog's destination control stopped being gated — and that failure
    // is the worse of the two, because it offers a colleague's space as a WRITE target.
    {name: 'Shared spaces in the save-query dialog', kind: 'control', path: '/query'},
    {name: 'Shared spaces as a move destination', kind: 'control', path: '/files'},
    {name: 'Shared connections help section', kind: 'guide', path: '/help', helpId: 'shared-connections'},
    // The recipient-kind choice in the send and share dialogs, each split into a guide of its
    // own so the Files and Tables guides beside them stay true with this flag off.
    {name: 'Send to a shared space guide', kind: 'guide', path: '/help', helpId: 'send-files-to-a-space'},
    {name: 'Share with a shared space guide', kind: 'guide', path: '/help', helpId: 'share-table-to-a-space'},
    // The SPACE variant of the same link, and the worse failure of the two: with this
    // flag off the route does not READ ?space=, resolves the personal space, and then discards a
    // prefix that does not start with it — landing the space's owner in their OWN files with no
    // banner, while the message tells them where to look.
    {name: 'Received files link to a space on a notification', kind: 'control', path: '/notifications'},
    // A SECOND instance of the recipient-kind choice, and it needs its own row: the
    // `Shared spaces` row above renders the share dialog, so nothing would notice if this one
    // stopped being gated. One surface per row is what makes the walking test mean anything.
    {name: 'Shared spaces recipient kind in the send dialog', kind: 'control', path: '/files'},
    // The Data Explorer's source picker reads `useQuerySpaces` exactly as the
    // saved-queries selector does, so it needs its own row for the same reason that one did:
    // the rows above render other surfaces, and an ungated picker would go on naming a
    // colleague's space after every other shared-workspace surface had gone.
    {name: 'Shared spaces in the Data Explorer source picker', kind: 'control', path: '/explore'},
    // The saved-view drawer's space select, a second reader of the same list on the same page:
    // the picker row renders the picker, so nothing would notice this one losing its gate.
    {name: 'Shared spaces in the saved-view drawer', kind: 'control', path: '/explore'},
    // A THIRD instance of the destination choice, and it needs its own row for the
    // reason the save-query one did: the rows above render other surfaces, so nothing would
    // notice if this one stopped being gated — and this is the WRITE-target variant, which
    // offers a colleague's space as somewhere to put a file.
    {name: 'Shared spaces in the Data Explorer save dialog', kind: 'control', path: '/explore'},
    // The export destination, on the same footing again — and its TWIN below is
    // the point: `useSaveResults` built its own list from an unfiltered `useQuerySpaces()`,
    // so the Query workspace's Save-results dialog had been offering a colleague's space as
    // a write target with this flag off, unregistered and unnoticed for a long time. The hook
    // now takes its destinations as a parameter and both views gate them.
    {name: 'Shared spaces in the Data Explorer export dialog', kind: 'control', path: '/explore'},
    {name: 'Shared spaces in the save-results dialog', kind: 'control', path: '/query'},
    // Links that name a shared space some other way than `?space=`: the refresh link's database,
    // and the report route's path segment. With this flag off Query cannot see the database and
    // the report route renders the unavailable page, so both links would be dead ends.
    {name: 'Refresh table link to a shared space on a notification', kind: 'control', path: '/notifications'},
    {name: 'Data quality link to a shared space on a notification', kind: 'control', path: '/notifications'},
    // The runs list aggregates every space's checks and linked each to its report, so it went on
    // naming a colleague's space after every other shared-workspace surface had gone.
    {name: 'Shared-space runs in the data quality list', kind: 'control', path: '/data-quality'},
    {
      name: 'Shared-space data quality report',
      kind: 'route',
      path: '/data-quality/:space/:requestId'
    }
  ],
  dataQuality: [
    {name: 'Data quality', kind: 'nav', path: '/data-quality'},
    {name: '/data-quality', kind: 'route', path: '/data-quality'},
    // Its own row: a report deep link must render unavailable and issue NO S3 request, or the
    // page becomes an existence oracle for someone else's report (the reason the route resolves before it mounts).
    {name: '/data-quality/:space/:requestId', kind: 'route', path: '/data-quality/:space/:requestId'},
    {name: 'Check data quality of the selected item', kind: 'control', path: '/files'},
    // Named by the contract table and gated by nothing until review said so.
    {name: 'Data quality link on a notification', kind: 'control', path: '/notifications'},
    // Inside the FILES section — which is why guides are gated individually, not by section.
    {name: 'Check data quality guide', kind: 'guide', path: '/help', helpId: 'check-data-quality'},
    {name: 'Past data quality checks guide', kind: 'guide', path: '/help', helpId: 'past-data-quality-checks'},
    {name: 'Data quality report guide', kind: 'guide', path: '/help', helpId: 'read-data-quality-report'}
  ],
  dataExplorer: [
    {name: 'Data Explorer', kind: 'nav', path: '/explore'},
    {name: '/explore', kind: 'route', path: '/explore'},
    // The Query rail's menu item, under ITS OWN flag. The `query` list carries the same
    // surface under the other one — one row per (surface, flag), because the two answer
    // different questions and either gate can be deleted alone.
    {name: 'Explore data', kind: 'control', path: '/query'},
    // The Query results' button, under ITS OWN flag, for the same reason as the rail item above.
    {name: 'Explore in Data Explorer', kind: 'control', path: '/query'},
    // The section AND each of its guides, on the `files` precedent: the section
    // row alone would be enough to hide them today, and it would go on passing if a later
    // spec moved one of these guides into the Query section — where it would then be
    // visible with `dataExplorer` off. The registry is the only home of the guide→flag
    // mapping, so a row per guide is what keeps that mapping true after a move.
    {name: 'Data Explorer help section', kind: 'guide', path: '/help', helpId: 'data-explorer'},
    {name: 'Start exploring guide', kind: 'guide', path: '/help', helpId: 'start-exploring'},
    {name: 'Filter and sort guide', kind: 'guide', path: '/help', helpId: 'explore-filter-sort'},
    {name: 'Grouping and Calc guide', kind: 'guide', path: '/help', helpId: 'explore-group-and-calc'},
    {name: 'Copy and export guide', kind: 'guide', path: '/help', helpId: 'explore-copy-and-export'},
    {name: 'Save an exploration guide', kind: 'guide', path: '/help', helpId: 'explore-save-as-query'}
  ],
  // A kill switch rather than an area, so it hides two things and not a tab: the record of what
  // this session handed to the plane, and the guide describing a round trip that only exists
  // while the routing does.
  //
  // WHAT THE FLAG NOW SWITCHES OFF IS A CAPABILITY, not a route to it. It used to be a fallback:
  // with it off, a folder copy, move or delete ran in the browser instead, slowly. The browser
  // has no recursive primitive any more — an operation whose cost grows with object count belongs
  // on the plane and building it twice is the loop the plane exists to remove — so with the flag
  // off nothing falls back, and every shape the routing rule sends to the plane is REFUSED AT THE
  // CONTROL: a folder or any multi-item selection leaves Copy, Move and Delete `aria-disabled`
  // with a reason, and a folder's Rename with them. A single-file copy, move, delete, rename and
  // download are unaffected either way.
  //
  // That refusal is not a surface and gets no row: a registry row can only say a control is there
  // or is not, and every control here is still there, only disabled. The test that says what it
  // does instead is the refused-at-the-control block in `fileOpsDispatch.test.tsx`, which pins it
  // for a folder Delete and for a two-file Copy, Move and Delete.
  asyncFileOperations: [
    {name: 'File operations in progress', kind: 'control', path: '/files'},
    {
      name: 'Background file operations guide',
      kind: 'guide',
      path: '/help',
      helpId: 'resolve-file-operation-conflicts'
    }
  ],
  // Neither an area nor a kill switch: a PRESENTATION flag over one control. Off, the
  // Save-results dialog offers no format choice; the enqueue route stays live and ungated
  // either way, so this takes nobody's access away.
  //
  // What it does NOT gate: whether a save copies or converts. With the flag off
  // the format is always csv, and a csv save still converts when the grid is hiding or
  // reordering columns — because a copy cannot produce that file, and the alternative is a user
  // who hid a column silently getting one that has it. The flag hides OPTIONS; it is not a
  // second answer to what a save should write.
  //
  // Two rows for one control, because there are two dialogs — the Query workspace's and the
  // Data Explorer's — and they are reached down different paths. The `sharedWorkspaces` list
  // above carries the same pair for the same reason, and it records why: the twin rows render
  // other surfaces, so nothing would notice if one of the two stopped being gated.
  //
  // The completion notification's link gets NO row. Its destination is `/files`, already gated
  // by the notification row's link gate — a mechanism registered twice over,
  // which the archive plane's link is the precedent for leaving alone.
  resultsConversion: [
    {name: 'Format in the save-results dialog', kind: 'control', path: '/query'},
    {name: 'Format in the Data Explorer export dialog', kind: 'control', path: '/explore'},
    // The formats each have a guide of their own, so the save guides they were split from stay
    // true with this switch thrown.
    {name: 'Save results formats guide', kind: 'guide', path: '/help', helpId: 'save-results-formats'},
    {name: 'Data Explorer save formats guide', kind: 'guide', path: '/help', helpId: 'explore-save-formats'}
  ],
  // The second kill switch, over the one surface where a mistake cannot be undone. One key for
  // archive AND restore: they run on one state machine, so a defect in it can reach either
  // direction, and hiding Restore delays data that already takes hours to return rather than
  // losing any. It hides the entry points and nothing else — the routes stay live, an execution in
  // flight finishes, and the notifications and their `/files` links are not gated, because the
  // record of what happened outlives the surface that started it. The receipt folder stays listed
  // and the "Rename, move, copy, or delete" guide, which names Archive in passing, stays visible.
  //
  // Every row here is also a row under `files`, whose gate stays: one row per (surface, flag), on
  // the precedent of `Explore data`. The names are descriptions because the `files` rows already
  // hold the accessible names, and a name keys the walk.
  archive: [
    {name: 'Archive in the selection toolbar', kind: 'control', path: '/files'},
    // The FILE details panel. The folder panel takes the same button behind the same gate, and is
    // asserted beside the archive journey rather than walked twice.
    {name: 'Archive in the details panel', kind: 'control', path: '/files'},
    {name: 'Restore Archived Data in the file browser', kind: 'control', path: '/files'},
    {
      name: 'Archive and restore guide under the archive switch',
      kind: 'guide',
      path: '/help',
      helpId: 'archive-files'
    }
  ]
};

/**
 * Every help section or guide id hidden while `flags` says its feature is off.
 *
 * Derived from the registry rather than declared beside it, so the Help page and the walking
 * test cannot disagree about which guide belongs to which flag.
 *
 * @param isEnabled - Answers whether one flag is on (normally `useFeature`).
 * @returns The ids to drop, as a Set for a cheap lookup per section and per guide.
 *
 * @example
 * const hidden = hiddenHelpIds((key) => flags[key]);
 * HELP_SECTIONS.filter((s) => !hidden.has(s.id));
 */
export function hiddenHelpIds(isEnabled: (key: FeatureFlagKey) => boolean): Set<string> {
  const hidden = new Set<string>();
  for (const [key, surfaces] of Object.entries(GATED_SURFACES) as [FeatureFlagKey, readonly GatedSurface[]][]) {
    if (isEnabled(key)) continue;
    for (const surface of surfaces) if (surface.helpId) hidden.add(surface.helpId);
  }
  return hidden;
}

/**
 * The nav destinations a flag governs, as `path → flag`.
 *
 * `PrimaryNav` and `AppNavDrawer` live in `components/`, which may not import a feature,
 * so they take a predicate instead of reaching for the hook. This is what the
 * predicate is built from — and it is derived from the registry, so a nav row cannot be gated
 * on a different flag from the route it points at.
 */
/**
 * A flag's own nav destination — its label and where it points.
 *
 * Read from the registry's `nav` row rather than declared separately, so the name the
 * unavailable page says out loud is the same string the missing tab used to carry.
 *
 * @param key - The flag.
 * @returns The destination, or `undefined` for a flag with no nav row.
 */
export function navDestination(key: FeatureFlagKey): {to: string; label: string} | undefined {
  const nav = GATED_SURFACES[key].find((surface) => surface.kind === 'nav');
  return nav ? {to: nav.path, label: nav.name} : undefined;
}

/** Every gated nav path mapped to the flag that gates it, for route-level gating. */
export const NAV_PATH_FLAGS: ReadonlyMap<string, FeatureFlagKey> = new Map(
  (Object.entries(GATED_SURFACES) as [FeatureFlagKey, readonly GatedSurface[]][]).flatMap(([key, surfaces]) =>
    surfaces.filter((s) => s.kind === 'nav').map((s) => [s.path, key] as const)
  )
);
