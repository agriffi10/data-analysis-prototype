import type {ReactNode} from 'react';
import {Navigate, useNavigate} from 'react-router';
import {useAuth} from '../features/auth';
import {FEATURE_FLAG_KEYS, navDestination, useFeatureSet} from '../features/feature-flags';
import {takeReturnPath} from '../lib/returnPath';
import {BrandMark} from '../components/BrandMark';
import {Badge} from '../components/Badge';
import {Button} from '../components/Button';
import {StatusPill} from '../components/StatusPill';
import {LandingNavMenu, type LandingNavLink} from './LandingNavMenu';
import {ThemeMenu} from '../components/ThemeMenu';
import {FeatureUnavailablePage} from './FeatureUnavailablePage';
import {cx} from '../lib/cx';
import {CheckIcon, FolderIcon, DatabaseIcon, ConnectionsIcon, PlayIcon} from '../components/icons';
import {usePageTitle} from '../hooks/usePageTitle';
import {SECTION_CAPTION} from '../components/fieldStyles';

// ─── Inline icons ──────────────────────────────────────────────────────────────

function ShieldIcon() {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.2"
      aria-hidden="true">
      <path d="M12 2 4 5v6c0 5 3.4 8.3 8 10 4.6-1.7 8-5 8-10V5z" />
    </svg>
  );
}

// ─── Static app-preview illustration (decorative) ─────────────────────────────

function PreviewFolderIcon() {
  return (
    <FolderIcon
      filled
      className="h-[18px] w-[18px] text-accent"
    />
  );
}

function PreviewFileIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      className="h-[18px] w-[18px] text-text-3"
      aria-hidden="true">
      <path d="M6 2h8l4 4v16H6z" />
      <path d="M14 2v4h4" />
    </svg>
  );
}

type PreviewSpace = {name: string; active?: boolean; tag?: string};

const PREVIEW_SPACES: PreviewSpace[] = [
  {name: 'alice', active: true, tag: 'user space'},
  {name: 'marketing_data'},
  {name: 'sales_2026'}
];

type PreviewRow = {icon: 'folder' | 'file'; name: string; size: string; modified: string; type: string};

const PREVIEW_ROWS: PreviewRow[] = [
  {icon: 'folder', name: '2026-q1', size: '—', modified: 'Apr 2', type: 'Folder'},
  {icon: 'file', name: 'annual-summary.pdf', size: '2.4 MB', modified: 'Apr 12', type: 'PDF'},
  {icon: 'file', name: 'revenue-model.xlsx', size: '812 KB', modified: 'Apr 11', type: 'XLSX'},
  {icon: 'file', name: 'dataset-export.csv', size: '14.7 MB', modified: 'Apr 9', type: 'CSV'}
];

/** Static Files-page illustration (decorative) — Spaces rail + toolbar + file table,
 *  mirroring the shipped FileBrowser (Type column, Create table / New folder / Upload). */
function AppPreview() {
  return (
    <div
      aria-hidden="true"
      className="mx-auto mt-10 max-w-[920px] overflow-hidden rounded-lg border border-border bg-surface shadow-lg">
      {/* Browser chrome */}
      <div className="flex h-[38px] items-center gap-[7px] border-b border-border bg-surface-2 px-4">
        <span className="h-[11px] w-[11px] rounded-full bg-border" />
        <span className="h-[11px] w-[11px] rounded-full bg-border" />
        <span className="h-[11px] w-[11px] rounded-full bg-border" />
      </div>

      {/* Body */}
      <div className="grid min-h-[320px] grid-cols-1 tablet:grid-cols-[210px_1fr]">
        {/* Spaces rail */}
        <div className="hidden border-r border-border-2 bg-surface p-3 tablet:block">
          <p className={`px-3 pb-1 pt-1 ${SECTION_CAPTION}`}>Spaces</p>
          {PREVIEW_SPACES.map((space) => (
            <div
              key={space.name}
              className={cx(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium',
                space.active ? 'bg-accent-soft text-accent-text' : 'text-text-2'
              )}>
              <FolderIcon className="h-[18px] w-[18px] flex-none" />
              <span className="min-w-0 truncate">{space.name}</span>
              {space.tag && <span className="ml-auto flex-none text-xs text-text-3">{space.tag}</span>}
            </div>
          ))}
        </div>

        {/* Main content */}
        <div className="min-w-0 p-4 tablet:p-5">
          {/* Toolbar — breadcrumb + primary actions (actions ≥ tablet, as shipped) */}
          <div className="mb-3 flex items-center gap-3">
            <div className="flex min-w-0 flex-1 items-center gap-1 text-sm">
              <span className="text-text-2">alice</span>
              <span className="text-text-3">/</span>
              <span className="font-semibold text-text">reports</span>
            </div>
            <div className="hidden items-center gap-2 tablet:flex">
              <span className="inline-flex h-8 items-center rounded-md border border-border bg-surface px-3 text-sm font-medium text-text-2">
                Create table
              </span>
              <span className="inline-flex h-8 items-center rounded-md border border-border bg-surface px-3 text-sm font-medium text-text-2">
                New folder
              </span>
              <span className="inline-flex h-8 items-center rounded-md bg-accent px-3 text-sm font-medium text-white">
                Upload
              </span>
            </div>
          </div>

          {/* File table */}
          <div className="overflow-hidden rounded-lg border border-border">
            <div className={`flex h-9 items-center border-b border-border bg-surface-2 ${SECTION_CAPTION}`}>
              <span className="w-9 flex-none" />
              <span className="min-w-0 flex-1 px-2">Name</span>
              <span className="hidden w-20 flex-none pr-3 text-right tablet:block">Size</span>
              <span className="hidden w-20 flex-none pr-3 text-right tablet:block">Modified</span>
              <span className="hidden w-20 flex-none pr-3 text-right desktop:block">Type</span>
            </div>
            {PREVIEW_ROWS.map((row) => (
              <div
                key={row.name}
                className="flex h-11 items-center border-b border-border-2 text-sm last:border-0">
                <span className="flex w-9 flex-none items-center justify-center">
                  <span className="h-4 w-4 rounded-sm border border-border" />
                </span>
                <span className="flex min-w-0 flex-1 items-center gap-2.5 px-2">
                  {row.icon === 'folder' ? <PreviewFolderIcon /> : <PreviewFileIcon />}
                  <span className="truncate font-medium text-text">{row.name}</span>
                </span>
                <span className="hidden w-20 flex-none pr-3 text-right text-text-3 tablet:block">{row.size}</span>
                <span className="hidden w-20 flex-none pr-3 text-right text-text-3 tablet:block">{row.modified}</span>
                <span className="hidden w-20 flex-none pr-3 text-right desktop:block">
                  <Badge>{row.type}</Badge>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Feature showcases (decorative — mirror the shipped Upload + Query UIs) ──────

/** Browser-chrome frame shared by the two feature showcases. `aria-hidden` — the
 *  meaningful copy lives in each figure's caption, not the illustration. */
function ShowcaseFrame({title, children}: {title: string; children: ReactNode}) {
  return (
    <div
      aria-hidden="true"
      className="overflow-hidden rounded-lg border border-border bg-surface shadow-md">
      <div className="flex h-[34px] items-center gap-[7px] border-b border-border bg-surface-2 px-4">
        <span className="h-[10px] w-[10px] rounded-full bg-border" />
        <span className="h-[10px] w-[10px] rounded-full bg-border" />
        <span className="h-[10px] w-[10px] rounded-full bg-border" />
        <span className="ml-2 truncate text-xs font-medium text-text-3">{title}</span>
      </div>
      {children}
    </div>
  );
}

type UploadShowcaseRow = {ext: string; name: string; status: 'uploading' | 'done'; detail: string; percent?: number};

const UPLOAD_ROWS: UploadShowcaseRow[] = [
  {ext: 'CSV', name: 'dataset-export.csv', status: 'uploading', detail: '8.4 MB of 14.7 MB', percent: 57},
  {ext: 'XLSX', name: 'revenue-model.xlsx', status: 'uploading', detail: '512 KB of 812 KB', percent: 63},
  {ext: 'PDF', name: 'annual-summary.pdf', status: 'done', detail: '2.4 MB'}
];

// Mirrors UploadList's StatusChip: amber pulsing while uploading, green when done.
function UploadShowcaseChip({status}: {status: 'uploading' | 'done'}) {
  const uploading = status === 'uploading';
  return (
    <StatusPill
      tone={uploading ? 'warning' : 'success'}
      pulse={uploading}>
      {uploading ? 'Uploading' : 'Uploaded'}
    </StatusPill>
  );
}

/** Uploads-in-flight panel — reproduces the in-app Upload drawer's UploadList. */
function UploadShowcase() {
  return (
    <ShowcaseFrame title="Uploads">
      <div className="p-4">
        <div className="mb-3 flex items-center gap-2">
          <span className={SECTION_CAPTION}>Uploads</span>
          <span className="text-sm text-text-2">2 in progress</span>
        </div>
        <ul className="space-y-3.5">
          {UPLOAD_ROWS.map((row) => (
            <li
              key={row.name}
              className="flex items-start gap-3">
              <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-[10px] font-semibold text-text-2">
                {row.ext}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-text">{row.name}</span>
                  <UploadShowcaseChip status={row.status} />
                </div>
                <div className="mt-1 flex items-center gap-1.5">
                  <span className="inline-flex flex-none items-center gap-1 rounded-full bg-surface-2 px-1.5 py-0.5 text-xs font-medium text-text-2">
                    <FolderIcon
                      filled
                      className="h-3 w-3 text-text-3"
                    />
                    alice
                  </span>
                  <span className="truncate text-xs text-text-2">{row.detail}</span>
                </div>
                {row.status === 'uploading' && (
                  <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-border">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{width: `${row.percent}%`}}
                    />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ul>
      </div>
    </ShowcaseFrame>
  );
}

const QUERY_RESULT_ROWS = [
  {n: '1', region: 'us-east', revenue: '1,284,300.00', orders: '4,021'},
  {n: '2', region: 'eu-west', revenue: '902,145.50', orders: '2,884'},
  {n: '3', region: 'ap-south', revenue: '655,980.25', orders: '1,902'}
];

/** Query workspace panel — editor + run bar, status line, and a results table. */
function QueryShowcase() {
  return (
    <ShowcaseFrame title="Query">
      {/* Editor toolbar */}
      <div className="flex h-11 items-center gap-2 border-b border-border px-4">
        <span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-border bg-surface-2 px-2 text-xs text-text-2">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          <code className="font-mono text-text">alice</code>
        </span>
        <div className="flex-1" />
        <span className="inline-flex h-7 items-center gap-1.5 rounded-md bg-accent px-3 text-xs font-semibold text-white">
          <PlayIcon className="h-3 w-3" />
          Run
        </span>
      </div>

      {/* SQL editor */}
      <div className="flex border-b border-border font-mono text-xs leading-[1.7]">
        <div className="shrink-0 border-r border-border-2 bg-surface-2 py-3 pr-2 text-right text-text-3">
          <div>1</div>
          <div>2</div>
          <div>3</div>
          <div>4</div>
        </div>
        <pre className="min-w-0 flex-1 overflow-hidden px-4 py-3 text-text">
          <div>
            <span className="italic text-text-3">-- Top regions by revenue</span>
          </div>
          <div>
            <span className="font-semibold text-accent">SELECT</span> region, <span className="text-accent">SUM</span>
            (amount) <span className="font-semibold text-accent">AS</span> revenue
          </div>
          <div>
            <span className="font-semibold text-accent">FROM</span> sales_2026
          </div>
          <div>
            <span className="font-semibold text-accent">GROUP BY</span> region{' '}
            <span className="font-semibold text-accent">ORDER BY</span> revenue{' '}
            <span className="font-semibold text-accent">DESC</span>;
          </div>
        </pre>
      </div>

      {/* Status bar */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-xs">
        <span className="inline-flex items-center gap-1.5 font-semibold text-success">
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          Succeeded
        </span>
        <span className="truncate text-text-2">3 rows · 1.2 MB scanned · 0.8s</span>
      </div>

      {/* Results table */}
      <div className="p-4">
        <div className="overflow-hidden rounded-md border border-border">
          <div className="grid grid-cols-[28px_1fr_1fr_60px] bg-surface-2 text-[10px] font-semibold uppercase tracking-wide text-text-3">
            <div className="px-2 py-1.5">#</div>
            <div className="px-2 py-1.5">region</div>
            <div className="px-2 py-1.5">revenue</div>
            <div className="px-2 py-1.5">orders</div>
          </div>
          {QUERY_RESULT_ROWS.map((r) => (
            <div
              key={r.n}
              className="grid grid-cols-[28px_1fr_1fr_60px] border-t border-border-2 font-mono text-xs">
              <div className="px-2 py-1.5 text-text-3">{r.n}</div>
              <div className="px-2 py-1.5 text-text">{r.region}</div>
              <div className="truncate px-2 py-1.5 text-text">{r.revenue}</div>
              <div className="px-2 py-1.5 text-text">{r.orders}</div>
            </div>
          ))}
        </div>
      </div>
    </ShowcaseFrame>
  );
}

// ─── Features ─────────────────────────────────────────────────────────────────

const NAV_LINKS: LandingNavLink[] = [
  {label: 'Features', href: '#features'},
  {label: 'Security', href: '#security'}
];

const FEATURES = [
  {
    icon: (
      <FolderIcon
        filled
        className="h-5 w-5"
      />
    ),
    title: 'Files & uploads',
    body: 'Drag-and-drop uploads, folders, and bulk move / copy / rename — then turn any folder into a queryable table.'
  },
  {
    icon: <DatabaseIcon className="h-5 w-5" />,
    title: 'SQL query workspace',
    body: 'A full SQL editor with saved queries, history, and paginated results you can save straight back into Files.'
  },
  {
    icon: <ConnectionsIcon className="h-5 w-5" />,
    title: 'Shared spaces',
    body: 'Create shared connections, invite members, and share tables — with notifications when a space is ready.'
  }
] as const;

// ─── Landing page ─────────────────────────────────────────────────────────────

/** Public marketing landing page (`/`) — self-contained nav (the app Header is suppressed on '/'), no S3 calls. */
export default function LandingPage() {
  const {status, signIn, signUp} = useAuth();
  const navigate = useNavigate();
  usePageTitle();

  const isAuthed = status === 'authenticated';

  // The UNAUTHENTICATED page is untouched by flags and never waits on the
  // document: it offers sign-in and sign-up, which nothing gates, and the flags gate the
  // fetch itself on a signed-in user — so a visitor who is not signed in would wait forever.
  // Everything below is therefore scoped to `isAuthed`.
  //
  // "Go to Dashboard" points at /files, so it is a `files` surface. With Files off it becomes
  // the first ENABLED feature rather than disappearing — a signed-in visitor still needs a
  // way in. While the flags resolve it renders NOTHING, which is why each site below is
  // `dashboard && …` rather than defaulting to /files.
  const {isEnabled, status: flagsStatus} = useFeatureSet();
  const dashboardKey = FEATURE_FLAG_KEYS.find((key) => isEnabled(key) && navDestination(key));
  const dashboard = dashboardKey
    ? // Keep the established wording for the ordinary case; name the destination otherwise.
      dashboardKey === 'files'
      ? {to: '/files', label: 'Dashboard'}
      : navDestination(dashboardKey)
    : undefined;

  // A visitor who just completed an auth round-trip is sent on to their pending
  // return path. An already-signed-in visitor has none — they stay here and see
  // "Go to Dashboard" instead of the sign-in/sign-up buttons.
  // Signed in with every feature off: there is nowhere to send them, so the landing page
  // becomes the same "not available" state a gated route renders, naming no feature.
  if (isAuthed && flagsStatus !== 'loading' && !dashboardKey) return <FeatureUnavailablePage />;

  if (isAuthed) {
    const target = takeReturnPath();
    if (target)
      return (
        <Navigate
          to={target}
          replace
        />
      );
  }

  return (
    <div className="min-h-screen bg-bg">
      {/* Sticky nav */}
      <nav
        aria-label="Primary"
        className="sticky top-0 z-20 h-16 border-b border-border bg-surface/80 backdrop-blur-sm backdrop-saturate-150">
        <div className="mx-auto flex h-full max-w-[1080px] items-center gap-3 px-4 tablet:gap-4 tablet:px-6">
          <LandingNavMenu links={NAV_LINKS} />
          <a
            href="/"
            aria-label="Data Workspace home">
            <BrandMark />
          </a>
          <div className="ml-8 hidden items-center gap-5 tablet:flex">
            {NAV_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="text-base font-medium text-text-2 hover:text-text">
                {link.label}
              </a>
            ))}
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            {/* The landing page suppresses the app header, so this is the only theme control a
                signed-out visitor can reach. */}
            <ThemeMenu />
            {isAuthed ? (
              dashboard && (
                <Button
                  variant="primary"
                  className="!h-10 !px-3 tablet:!px-5"
                  onClick={() => navigate(dashboard.to)}>
                  Go to {dashboard.label}
                </Button>
              )
            ) : (
              <>
                <Button
                  variant="ghost"
                  className="!h-10 !px-3 tablet:!px-5"
                  onClick={() => void signIn()}>
                  Sign in
                </Button>
                <Button
                  variant="primary"
                  className="!h-10 !px-3 tablet:!px-5"
                  onClick={() => void signUp()}>
                  Create account
                </Button>
              </>
            )}
          </div>
        </div>
      </nav>

      <main id="main">
        {/* Hero */}
        <section className="py-16 text-center">
          <div className="mx-auto max-w-[1080px] px-6">
            <span className="mb-5 inline-flex items-center gap-2 rounded-full border border-accent-border bg-accent-soft px-3 py-1.5 text-xs font-semibold tracking-wide text-accent-text">
              <ShieldIcon />
              Private storage · SQL query · shared spaces — on your own AWS
            </span>
            <h1 className="mx-auto mb-5 max-w-[760px] text-[32px] font-bold leading-tight tracking-[-0.02em] tablet:text-[40px] desktop:text-[46px]">
              Your data workspace, <span className="text-accent">scoped to you</span>.
            </h1>
            <p className="mx-auto mb-8 max-w-[600px] text-lg text-text-2">
              Upload files to a private space, turn folders into queryable tables, run SQL right in the browser, and
              share spaces with your team — all backed by your own AWS account.
            </p>
            <div className="flex flex-col gap-3 tablet:flex-row tablet:flex-wrap tablet:justify-center">
              {isAuthed ? (
                dashboard && (
                  <Button
                    variant="primary"
                    size="lg"
                    className="w-full tablet:w-auto"
                    onClick={() => navigate(dashboard.to)}>
                    Go to {dashboard.label}
                  </Button>
                )
              ) : (
                <>
                  <Button
                    variant="primary"
                    size="lg"
                    className="w-full tablet:w-auto"
                    onClick={() => void signUp()}>
                    Create your account
                  </Button>
                  <Button
                    variant="default"
                    size="lg"
                    className="w-full tablet:w-auto"
                    onClick={() => void signIn()}>
                    Sign in
                  </Button>
                </>
              )}
            </div>
            {!isAuthed && (
              <div className="mt-5 flex items-center justify-center gap-2 text-sm text-text-3">
                <span className="text-success">
                  <CheckIcon className="h-[14px] w-[14px]" />
                </span>
                Sign-in and sign-up are handled by AWS Cognito — we never see your password.
              </div>
            )}

            <AppPreview />
          </div>
        </section>

        {/* Features */}
        <section
          id="features"
          className="py-10">
          <div className="mx-auto max-w-[1080px] px-6">
            <div className="mb-8 text-center">
              <h2 className="text-[30px] font-bold tracking-[-0.01em]">Everything you need to work with your data</h2>
              <p className="mt-3 text-md text-text-2">
                From raw files to queryable tables to shared collaboration — one focused workspace.
              </p>
            </div>
            {/* 1-col mobile → 2-up at tablet (3rd card spans) → 3-up at desktop. */}
            <div className="grid grid-cols-1 gap-5 tablet:grid-cols-2 desktop:grid-cols-3">
              {FEATURES.map((feature, i) => (
                <div
                  key={feature.title}
                  className={cx(
                    'rounded-lg border border-border bg-surface p-6 shadow-sm',
                    i === 2 && 'tablet:col-span-2 desktop:col-span-1'
                  )}>
                  <div className="mb-4 grid h-10 w-10 place-items-center rounded-md bg-accent-soft text-accent">
                    {feature.icon}
                  </div>
                  <h3 className="mb-2 text-md font-semibold">{feature.title}</h3>
                  <p className="text-sm text-text-2">{feature.body}</p>
                </div>
              ))}
            </div>

            {/* Showcase graphics — the real Upload + Query surfaces, side-by-side. */}
            <div className="mt-10 grid grid-cols-1 gap-6 tablet:mt-12 tablet:grid-cols-2">
              <figure className="m-0">
                <UploadShowcase />
                <figcaption className="mt-3 text-center text-sm text-text-2">
                  Live progress for every upload — large files switch to multipart automatically.
                </figcaption>
              </figure>
              <figure className="m-0">
                <QueryShowcase />
                <figcaption className="mt-3 text-center text-sm text-text-2">
                  Write SQL, run it, and page through results — then save them straight back to your files.
                </figcaption>
              </figure>
            </div>
          </div>
        </section>

        {/* CTA strip */}
        <section
          id="security"
          className="py-8 pb-10">
          <div className="mx-auto max-w-[1080px] px-6">
            {/* A fixed brand surface: its colours are declared outside `@theme` and outside
                every theme block, so it looks the same in both. That is what keeps its white
                buttons legible — a themed label colour would go light in the dark theme and
                vanish against them. */}
            <div className="rounded-lg bg-(--landing-cta-bg) px-8 py-10 text-center text-(--landing-cta-text) shadow-md">
              <h2 className="mb-3 text-[28px] font-bold tracking-[-0.01em]">
                Isolation enforced at the infrastructure layer
              </h2>
              <p className="mx-auto mb-6 max-w-[480px] text-md text-(--landing-cta-text-muted)">
                Authentication runs on AWS Cognito and every user is scoped to their own storage by AWS IAM — not by
                application code. Get started in under a minute.
              </p>
              <div className="flex flex-col justify-center gap-3 tablet:flex-row tablet:flex-wrap">
                {isAuthed ? (
                  dashboard && (
                    <button
                      type="button"
                      onClick={() => navigate(dashboard.to)}
                      className="h-[46px] w-full rounded-md bg-(--landing-cta-button-bg) px-6 text-md font-semibold text-(--landing-cta-button-text) hover:bg-(--landing-cta-button-hover) tablet:w-auto">
                      Go to {dashboard.label}
                    </button>
                  )
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void signUp()}
                      className="h-[46px] w-full rounded-md bg-(--landing-cta-button-bg) px-6 text-md font-semibold text-(--landing-cta-button-text) hover:bg-(--landing-cta-button-hover) tablet:w-auto">
                      Create account
                    </button>
                    <button
                      type="button"
                      onClick={() => void signIn()}
                      className="h-[46px] w-full rounded-md border border-(--landing-cta-text)/40 bg-(--landing-cta-text)/10 px-6 text-md font-semibold text-(--landing-cta-text) hover:bg-(--landing-cta-text)/20 tablet:w-auto">
                      Sign in
                    </button>
                  </>
                )}
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface">
        <div className="mx-auto flex h-16 max-w-[1080px] items-center gap-4 px-6">
          <a
            href="/"
            aria-label="Data Workspace home">
            <BrandMark size="sm" />
          </a>
          <div className="flex-1" />
          <p className="text-sm text-text-3">
            © 2026 Data Workspace ·{' '}
            <a
              href="#"
              className="text-text-2 hover:text-text">
              Privacy
            </a>{' '}
            <a
              href="#"
              className="text-text-2 hover:text-text">
              Terms
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}
