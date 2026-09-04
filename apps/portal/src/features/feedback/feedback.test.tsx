import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {cleanup, screen, within} from '@testing-library/react';
import {Header} from '../../components/Header';
import {renderWithProviders} from '../../test/renderWithProviders';
import {authenticated} from '../../test/authFixtures';
import {apiFailure, mockApi, type ApiMock} from '../../test/apiMock';
import {expectContainerHasNoA11yViolations, COMPONENT_AXE_OPTIONS} from '../../test/axe';
import {MAX_FEEDBACK_MESSAGE_CHARS, MAX_FEEDBACK_ROUTE_CHARS} from './feedback.constants';
import type {FeedbackSubmitRequest} from '../../types/apiContract.generated';

vi.mock('../../lib/apiClient', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../lib/apiClient')>()),
  apiRequest: vi.fn()
}));

// The bell polls on mount in the always-present shell; it is the AWS boundary, not this feature.
vi.mock('../notifications/notifications.service', () => ({
  getNotifications: vi.fn().mockResolvedValue({success: true, data: []}),
  enqueueNotificationAction: vi.fn().mockResolvedValue({success: true, data: undefined})
}));

const TABLET = 1024;
const PHONE = 375;

function setWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', {value: width, writable: true, configurable: true});
}

describe('Give feedback', () => {
  let api: ApiMock;

  beforeEach(async () => {
    const {apiRequest} = await import('../../lib/apiClient');
    api = mockApi(vi.mocked(apiRequest) as unknown as ReturnType<typeof vi.fn>);
    api.on('feedback.submit', {success: true, data: {submittedAt: '2026-08-28T14:03:11Z'}});
    setWidth(TABLET);
  });

  afterEach(() => {
    cleanup();
    setWidth(TABLET);
  });

  function renderHeader(route = '/query') {
    return renderWithProviders(<Header />, {auth: authenticated('acarter'), route});
  }

  /**
   * Reach Give feedback, which is an item in the account menu rather than a header button.
   * One helper rather than the two lines inline everywhere, so the menu's shape lives in one
   * place — the same reason the Data Explorer's options menu has a testkit.
   */
  async function openFeedback(user: ReturnType<typeof renderHeader>['user']) {
    await user.click(screen.getByRole('button', {name: 'Account: acarter'}));
    await user.click(
      within(screen.getByRole('menu', {name: 'Account'})).getByRole('menuitem', {name: 'Give feedback'})
    );
  }

  it('sends the category, the trimmed message and the page you were on, then thanks you', async () => {
    const {user} = renderHeader('/query');

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'bug');
    await user.type(screen.getByLabelText('Your feedback'), '  The upload bar sticks at 0%.  ');
    await user.click(screen.getByRole('button', {name: 'Send'}));

    expect(api.countOf('feedback.submit')).toBe(1);
    expect(api.bodyFor('feedback.submit')).toEqual({
      category: 'bug',
      message: 'The upload bar sticks at 0%.',
      route: '/query'
    } satisfies FeedbackSubmitRequest);
    expect(await screen.findByText('Thanks — your feedback has been sent.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', {name: 'Give feedback'})).not.toBeInTheDocument();
  });

  it('captures the route the dialog OPENED on, not the one submitted from', async () => {
    // The one behaviour a submit-time read would get wrong, and it is the common case: a user
    // hits something odd, opens the dialog, and the app navigates underneath them.
    const {user} = renderHeader('/files');

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'idea');
    await user.type(screen.getByLabelText('Your feedback'), 'A thought.');
    await user.click(screen.getByRole('link', {name: 'Data Explorer'}));
    await user.click(screen.getByRole('button', {name: 'Send'}));

    expect(api.bodyFor('feedback.submit')).toMatchObject({route: '/files'});
  });

  it('keeps the dialog and the message on a failure, and renders OUR wording for the code', async () => {
    api.on('feedback.submit', apiFailure('RateLimited'));
    const {user} = renderHeader();

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'question');
    await user.type(screen.getByLabelText('Your feedback'), 'Where do exports go?');
    await user.click(screen.getByRole('button', {name: 'Send'}));

    const dialog = await screen.findByRole('dialog', {name: 'Give feedback'});
    expect(within(dialog).getByLabelText('Your feedback')).toHaveValue('Where do exports go?');
    expect(within(dialog).getByText('The service is busy. Wait a moment and try again.')).toBeInTheDocument();
    expect(screen.queryByText('Thanks — your feedback has been sent.')).not.toBeInTheDocument();
  });

  it('refuses to submit until both fields are filled, and preselects no category', async () => {
    const {user} = renderHeader();

    await openFeedback(user);
    // A default category would be the modal answer to every submission; the field records a choice.
    expect(screen.getByLabelText('What is this about?')).toHaveValue('');
    expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('What is this about?'), 'other');
    expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled();

    await user.type(screen.getByLabelText('Your feedback'), '   ');
    expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled();

    await user.type(screen.getByLabelText('Your feedback'), 'x');
    expect(screen.getByRole('button', {name: 'Send'})).toBeEnabled();
    expect(api.countOf('feedback.submit')).toBe(0);
  });

  it('submits from the category field on Enter and inserts a newline in the message', async () => {
    const {user} = renderHeader();

    await openFeedback(user);
    await user.type(screen.getByLabelText('Your feedback'), 'line one{Enter}line two');
    expect(screen.getByLabelText('Your feedback')).toHaveValue('line one\nline two');
    expect(api.countOf('feedback.submit')).toBe(0);

    // Enter on the category with the message still empty must submit NOTHING. What enforces that
    // is `FormDialog`'s own `submitDisabled` gate rather than the handler's guard — measured, by
    // deleting the handler's and watching this still pass — so the assertion is on the outcome a
    // user gets, which is true whichever of the two is doing the work.
    await user.clear(screen.getByLabelText('Your feedback'));
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'bug');
    await user.type(screen.getByLabelText('What is this about?'), '{Enter}');
    expect(api.countOf('feedback.submit')).toBe(0);

    await user.type(screen.getByLabelText('Your feedback'), 'now it has one');
    await user.type(screen.getByLabelText('What is this about?'), '{Enter}');
    expect(api.countOf('feedback.submit')).toBe(1);
  });

  it('locks the form while the submission is in flight, and swallows Escape', async () => {
    // The api mock resolves synchronously, so nothing else in this file ever observes the
    // in-flight state — and `busy` is what wires BOTH of FR-007's in-flight criteria: Send is
    // disabled, and `FormDialog` passes `dismissible={!busy}` so a busy modal eats Escape.
    let release!: (r: {success: true; data: {submittedAt: string}}) => void;
    api.on('feedback.submit', new Promise((resolve) => (release = resolve)) as never);
    const {user} = renderHeader();

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'bug');
    await user.type(screen.getByLabelText('Your feedback'), 'Stuck at 0%.');
    await user.click(screen.getByRole('button', {name: 'Send'}));

    const dialog = await screen.findByRole('dialog', {name: 'Give feedback'});
    expect(within(dialog).getByRole('button', {name: 'Sending…'})).toBeDisabled();
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog', {name: 'Give feedback'})).toBeInTheDocument();
    expect(api.countOf('feedback.submit')).toBe(1);

    release({success: true, data: {submittedAt: '2026-08-28T14:03:11Z'}});
    await screen.findByText('Thanks — your feedback has been sent.');
  });

  it('clears the message, so reopening does not show the last submission', async () => {
    // What this pins is the USER-VISIBLE criterion, and it is worth being exact about what it
    // cannot see: the host unmounts the dialog on close, so a reopened dialog starts empty even
    // with the explicit reset deleted — measured. The reset stays because it is what keeps the
    // criterion true if the dialog is ever kept mounted, and nothing here can prove that.
    const {user} = renderHeader();

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'idea');
    await user.type(screen.getByLabelText('Your feedback'), 'The first one.');
    await user.click(screen.getByRole('button', {name: 'Send'}));
    await screen.findByText('Thanks — your feedback has been sent.');

    await openFeedback(user);
    expect(screen.getByLabelText('Your feedback')).toHaveValue('');
    expect(screen.getByLabelText('What is this about?')).toHaveValue('');
  });

  it('clips a pathological pathname rather than losing the whole submission to it', async () => {
    // The `*` 404 route renders the shell, so the header and this control appear on any garbage
    // URL — which is when somebody most wants to report something. Unclipped, the route refuses
    // the submission over a path the user never typed.
    const {user} = renderHeader(`/${'x'.repeat(400)}`);

    await openFeedback(user);
    await user.selectOptions(screen.getByLabelText('What is this about?'), 'bug');
    await user.type(screen.getByLabelText('Your feedback'), 'This page is broken.');
    await user.click(screen.getByRole('button', {name: 'Send'}));

    const sent = api.bodyFor('feedback.submit') as {route: string};
    expect(sent.route.length).toBe(MAX_FEEDBACK_ROUTE_CHARS);
    await screen.findByText('Thanks — your feedback has been sent.');
  });

  it('caps the message at the same length the route does', () => {
    // Mirrored rather than shared: the route's cap is the control. A pair that disagrees means a
    // user writes past the limit and loses the overflow to a refusal, so the numbers are pinned
    // to each other by `lambdas/test_feedback_caps_agree.py` on the other side.
    expect(MAX_FEEDBACK_MESSAGE_CHARS).toBe(4000);
  });

  describe('at mobile width', () => {
    beforeEach(() => setWidth(PHONE));

    it('adds NOTHING to the header, and reaches the control through the account menu', async () => {
      // FR-007, and the criterion SPEC-207 and SPEC-210 both build against. Asserted by MOUNT,
      // not by class: jsdom loads no Tailwind, so a `tablet:hidden` button is indistinguishable
      // from a visible one here and this test would pass over a header that gained a control.
      const {user} = renderHeader();
      const header = screen.getByRole('banner');
      // Every interactive control, by accessible name, REGARDLESS OF ROLE. The criterion is the
      // header's control count; counting buttons alone made it role-sensitive, and SPEC-207 turns
      // the help control from a link into a button on routes that have a guide panel — the same
      // one control, which a button-only count would report as the header gaining one.
      const controls = [...header.querySelectorAll('button, a[href]')].map(
        (el) => el.getAttribute('aria-label') ?? el.textContent?.trim()
      );

      // Still the criterion FR-007 owns: no Give feedback control of its own on the bar.
      expect(controls).not.toContain('Give feedback');

      // Pinned whole, as a tripwire. It lists the PrimaryNav tabs because jsdom loads no
      // Tailwind, so `hidden tablet:flex` does not remove them. A header change in any spec
      // reddens this and sends the next author back to FR-007's measurement.
      //
      // THE MEASUREMENT, re-taken because that is what this tripwire is for. The bar's
      // fixed-width chrome was a hamburger, the brand mark, help, the bell, an avatar and a
      // text "Sign out" button — six things, over budget at 375px, which is why theme and
      // feedback were mount-gated off the phone entirely. It is now a hamburger, the brand
      // mark, help, the bell and ONE account trigger: five, with the username hidden below
      // `tablet` so the trigger is the 32px avatar alone. Strictly narrower than before, and
      // every option the two gated controls carried is now reachable at this width.
      expect(controls).toEqual([
        'Open navigation',
        'Files',
        'Query',
        'Data Explorer',
        'Connections',
        'Data quality',
        'Help for this page',
        'Notifications, none unread',
        'Account: acarter'
      ]);

      // The drawer no longer carries a copy — one control, reachable at every width.
      await user.click(screen.getByRole('button', {name: 'Open navigation'}));
      const drawer = await screen.findByRole('dialog', {name: 'Navigation'});
      expect(within(drawer).queryByRole('button', {name: 'Give feedback'})).not.toBeInTheDocument();
    });

    it('opens the dialog from the account menu at this width too', async () => {
      const {user} = renderHeader();

      await openFeedback(user);

      expect(await screen.findByRole('dialog', {name: 'Give feedback'})).toBeInTheDocument();
    });
  });

  it('has no axe violations with the dialog open', async () => {
    const {user, container} = renderHeader();

    await openFeedback(user);
    await screen.findByRole('dialog', {name: 'Give feedback'});

    // The DRIVEN container, not a fresh render: `expectNoA11yViolations` renders its argument
    // again and would check the closed state, where axe never sees the dialog at all.
    await expectContainerHasNoA11yViolations(container, COMPONENT_AXE_OPTIONS);
  });
});
