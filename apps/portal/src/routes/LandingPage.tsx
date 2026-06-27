import {Navigate, useNavigate} from 'react-router-dom';
import {useAuth} from '../features/auth';
import {takeReturnPath} from '../lib/returnPath';
import {BrandMark} from '../components/BrandMark';
import {Button} from '../components/Button';
import {UploadIcon, FolderIcon} from '../components/icons';
import {usePageTitle} from '../hooks/usePageTitle';

// ─── Inline icons (from docs/design/landing.html) ─────────────────────────────

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

function CheckIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      aria-hidden="true">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function UploadFeatureIcon() {
  return <UploadIcon className="h-5 w-5" />;
}

function FolderFeatureIcon() {
  return (
    <FolderIcon
      filled
      className="h-5 w-5"
    />
  );
}

function LinkFeatureIcon() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true">
      <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
      <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
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

type PreviewRow = {
  icon: 'folder' | 'file';
  name: string;
  size: string;
  date: string;
};

const PREVIEW_ROWS: PreviewRow[] = [
  {icon: 'folder', name: '2026-q1', size: '—', date: 'Mar 3'},
  {icon: 'file', name: 'annual-summary.pdf', size: '2.4 MB', date: 'Mar 2'},
  {icon: 'file', name: 'revenue-model.xlsx', size: '847 KB', date: 'Feb 27'},
  {icon: 'file', name: 'dataset-export.csv', size: '12.1 MB', date: 'Feb 24'}
];

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
      <div className="grid min-h-[320px] grid-cols-1 sm:grid-cols-[200px_1fr]">
        {/* Sidebar */}
        <div className="hidden border-r border-border-2 bg-surface p-4 sm:block">
          <p className="px-2 pb-1 text-xs font-semibold uppercase tracking-[.04em] text-text-3">My Files</p>
          <div className="flex items-center gap-2 rounded-sm bg-accent-soft px-2 py-[7px] text-sm font-semibold text-accent-text">
            <span className="h-[7px] w-[7px] rounded-full bg-current opacity-50" />
            alice
          </div>
          <p className="px-2 pb-1 pt-4 text-xs font-semibold uppercase tracking-[.04em] text-text-3">Shared</p>
          <div className="flex items-center gap-2 rounded-sm px-2 py-[7px] text-sm text-text-2">
            <span className="h-[7px] w-[7px] rounded-full bg-current opacity-50" />
            Project Alpha
          </div>
          <div className="flex items-center gap-2 rounded-sm px-2 py-[7px] text-sm text-text-2">
            <span className="h-[7px] w-[7px] rounded-full bg-current opacity-50" />
            Project Beta
          </div>
        </div>

        {/* Main content */}
        <div className="p-4 pl-5">
          <div className="grid h-[42px] grid-cols-[22px_1fr_80px_90px] items-center gap-3 border-b border-border-2 text-xs font-semibold uppercase tracking-[.03em] text-text-3">
            <span />
            <span>Name</span>
            <span>Size</span>
            <span>Modified</span>
          </div>
          {PREVIEW_ROWS.map((row) => (
            <div
              key={row.name}
              className="grid h-[42px] grid-cols-[22px_1fr_80px_90px] items-center gap-3 border-b border-border-2 text-sm">
              {row.icon === 'folder' ? <PreviewFolderIcon /> : <PreviewFileIcon />}
              <span className="font-medium text-text">{row.name}</span>
              <span className="text-text-3">{row.size}</span>
              <span className="text-text-3">{row.date}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Features ─────────────────────────────────────────────────────────────────

const FEATURES = [
  {
    icon: <UploadFeatureIcon />,
    title: 'Fast, resilient uploads',
    body: 'Drag and drop files up to several gigabytes. Large files switch to multipart upload automatically, with live progress for every file.'
  },
  {
    icon: <FolderFeatureIcon />,
    title: "A space that's yours",
    body: 'Browse, organize into folders, rename, move, and download. Your space is private to you — no one else can see or touch it.'
  },
  {
    icon: <LinkFeatureIcon />,
    title: 'Connect to shared data',
    body: 'Link the shared project prefixes you have access to and work with them alongside your own files, all from one place.'
  }
] as const;

// ─── Landing page ─────────────────────────────────────────────────────────────

// Public marketing landing page (`/`), SPEC-029. Renders its own self-contained
// nav (the app Header is suppressed on '/' by RootLayout) and makes no S3 calls.
export default function LandingPage() {
  const {status, signIn, signUp} = useAuth();
  const navigate = useNavigate();
  usePageTitle();

  const isAuthed = status === 'authenticated';

  // A visitor who just completed an auth round-trip is sent on to the route they
  // originally requested (captured by the auth gate) or the /files default both
  // signIn and signUp seed. A visitor who is simply already signed in and opened
  // the landing page has no pending return path — they stay here and see a
  // "Go to Dashboard" entry point instead of the sign-in/sign-up buttons.
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
        className="sticky top-0 z-20 h-16 border-b border-border bg-white/80 backdrop-blur-sm backdrop-saturate-150">
        <div className="mx-auto flex h-full max-w-[1080px] items-center gap-4 px-6">
          <a
            href="/"
            aria-label="S3 File Portal home">
            <BrandMark />
          </a>
          <div className="ml-8 hidden items-center gap-5 md:flex">
            <a
              href="#features"
              className="text-base font-medium text-text-2 hover:text-text">
              Features
            </a>
            <a
              href="#security"
              className="text-base font-medium text-text-2 hover:text-text">
              Security
            </a>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            {isAuthed ? (
              <Button
                variant="primary"
                className="!h-10 !px-5"
                onClick={() => navigate('/files')}>
                Go to Dashboard
              </Button>
            ) : (
              <>
                <Button
                  variant="ghost"
                  className="!h-10 !px-5"
                  onClick={() => void signIn()}>
                  Sign in
                </Button>
                <Button
                  variant="primary"
                  className="!h-10 !px-5"
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
            <span className="mb-5 inline-flex items-center gap-2 rounded-full border border-[#e0e3ff] bg-accent-soft px-3 py-1.5 text-xs font-semibold tracking-wide text-accent-text">
              <ShieldIcon />
              Secure, per-user file storage on AWS
            </span>
            <h1 className="mx-auto mb-5 max-w-[760px] text-[46px] font-bold leading-tight tracking-[-0.02em]">
              Your files in the cloud, <span className="text-accent">scoped to you</span>.
            </h1>
            <p className="mx-auto mb-8 max-w-[600px] text-lg text-text-2">
              Upload, organize, and share files in your own private space — and connect to shared project data when you
              need it. Backed by AWS, with isolation enforced at the infrastructure layer.
            </p>
            <div className="flex flex-wrap justify-center gap-3">
              {isAuthed ? (
                <Button
                  variant="primary"
                  size="lg"
                  onClick={() => navigate('/files')}>
                  Go to Dashboard
                </Button>
              ) : (
                <>
                  <Button
                    variant="primary"
                    size="lg"
                    onClick={() => void signUp()}>
                    Create your account
                  </Button>
                  <Button
                    variant="default"
                    size="lg"
                    onClick={() => void signIn()}>
                    Sign in
                  </Button>
                </>
              )}
            </div>
            {!isAuthed && (
              <div className="mt-5 flex items-center justify-center gap-2 text-sm text-text-3">
                <span className="text-success">
                  <CheckIcon />
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
              <h2 className="text-[30px] font-bold tracking-[-0.01em]">Everything you need to manage your files</h2>
              <p className="mt-3 text-md text-text-2">
                A focused workspace — no clutter, just your files where you expect them.
              </p>
            </div>
            <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
              {FEATURES.map((feature) => (
                <div
                  key={feature.title}
                  className="rounded-lg border border-border bg-surface p-6 shadow-sm">
                  <div className="mb-4 grid h-10 w-10 place-items-center rounded-md bg-accent-soft text-accent">
                    {feature.icon}
                  </div>
                  <h3 className="mb-2 text-md font-semibold">{feature.title}</h3>
                  <p className="text-sm text-text-2">{feature.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* CTA strip */}
        <section
          id="security"
          className="py-8 pb-10">
          <div className="mx-auto max-w-[1080px] px-6">
            <div className="rounded-lg bg-accent px-8 py-10 text-center text-white shadow-md">
              <h2 className="mb-3 text-[28px] font-bold tracking-[-0.01em]">
                Isolation enforced at the infrastructure layer
              </h2>
              <p className="mx-auto mb-6 max-w-[480px] text-md text-[#dfe0fb]">
                Authentication runs on AWS Cognito and every user is scoped to their own storage by AWS IAM — not by
                application code. Get started in under a minute.
              </p>
              <div className="flex flex-wrap justify-center gap-3">
                {isAuthed ? (
                  <button
                    type="button"
                    onClick={() => navigate('/files')}
                    className="h-[46px] rounded-md border-white bg-white px-6 text-md font-semibold text-accent-text hover:bg-[#f3f4ff]">
                    Go to Dashboard
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => void signUp()}
                      className="h-[46px] rounded-md border-white bg-white px-6 text-md font-semibold text-accent-text hover:bg-[#f3f4ff]">
                      Create account
                    </button>
                    <button
                      type="button"
                      onClick={() => void signIn()}
                      className="h-[46px] rounded-md border border-white/40 bg-white/10 px-6 text-md font-semibold text-white hover:bg-white/20">
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
            aria-label="S3 File Portal home">
            <BrandMark size="sm" />
          </a>
          <div className="flex-1" />
          <p className="text-sm text-text-3">
            © 2026 FilePortal ·{' '}
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
