import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiRequest} from '../../lib/apiClient';
import {toUserText} from '../../lib/errorMessages';
import {uploadFile} from './fileBrowser.service';
import {PART_CONCURRENCY, PART_RETRIES} from './multipartUpload';
import {UPLOAD_CONCURRENCY} from './upload.types';
import {maxUploadBytes} from './uploadLimits';

vi.mock('../../lib/apiClient', () => ({apiRequest: vi.fn()}));

/** How the server cuts these test files. Small, so a whole upload is a handful of parts. */
const PART_SIZE = 5;

/**
 * A transport that records every byte offered to it and can be told to fail a given attempt.
 *
 * **It counts bytes rather than requests**, because the claim under test is that a failed part
 * re-sends *that part* and not the whole file — and a request count cannot tell those apart.
 */
class RecordingXhr {
  static offered: number[] = [];
  static opened: string[] = [];
  static failAttempt: number | null = null;
  static etagHeader: string | null = '"etag"';
  static attempts = 0;
  static onSend: ((xhr: RecordingXhr) => void) | null = null;
  static emitProgress = false;

  upload = {addEventListener: (_: string, handler: (e: unknown) => void) => (this.progress = handler)};
  private handlers = new Map<string, () => void>();
  private progress: ((e: unknown) => void) | null = null;
  status = 200;

  addEventListener(event: string, handler: () => void) {
    this.handlers.set(event, handler);
  }
  open(_method: string, url: string) {
    RecordingXhr.opened.push(url);
  }
  setRequestHeader() {}
  getResponseHeader() {
    return RecordingXhr.etagHeader;
  }
  fireProgress(loaded: number) {
    this.progress?.({loaded, total: loaded, lengthComputable: true});
  }
  send(body: Blob) {
    RecordingXhr.attempts += 1;
    RecordingXhr.offered.push(body.size);
    const attempt = RecordingXhr.attempts;
    const failing = RecordingXhr.failAttempt === attempt;

    // **A transfer fires SEVERAL progress events, and a failing one stops partway.** One event per
    // attempt is what makes an aggregate test vacuous: with a single full-size event, per-part
    // max, last-value-wins and a running sum all report the same number and no mutation can be
    // told from the original. A retried part is a NEW request whose first event reports a small
    // `loaded`, which is the moment the three diverge.
    if (RecordingXhr.emitProgress) {
      for (const loaded of failing ? [1, 4] : [1, 4, body.size]) this.fireProgress(loaded);
    }

    RecordingXhr.onSend?.(this);
    queueMicrotask(() => {
      if (failing) {
        this.handlers.get('error')?.();
        return;
      }
      this.handlers.get('load')?.();
    });
  }
  abort() {}
}

/** A blob whose `slice` reports real sizes without allocating anything. */
function blob(size: number): Blob {
  const made = {
    size,
    type: 'application/octet-stream',
    slice: (start: number, end: number) => blob(Math.max(0, end - start))
  };
  return made as unknown as Blob;
}

/** Answers create with a multipart plan, then every part call, then the assembly. */
function serverPlans(partCount: number) {
  vi.mocked(apiRequest).mockImplementation((async (route: string) => {
    if (route === 'objects.upload') {
      return {
        success: true,
        data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount}
      };
    }
    if (route === 'objects.uploadPart') {
      return {success: true, data: {url: `https://signed/part`, expiresAt: '2999-01-01T00:00:00Z'}};
    }
    if (route === 'objects.uploadComplete') return {success: true, data: {key: 'alice/big.bin', etag: 'e'}};
    if (route === 'objects.uploadAbort') return {success: true, data: {key: 'alice/big.bin'}};
    return {success: false, error: {message: 'unexpected route', code: 'InternalError'}};
  }) as unknown as typeof apiRequest);
}

function upload(size: number, over: Partial<Parameters<typeof uploadFile>[0]> = {}) {
  return uploadFile({
    bucket: 'user-space',
    key: 'alice/big.bin',
    body: blob(size),
    contentType: 'application/octet-stream',
    ...over
  });
}

beforeEach(() => {
  // Cleared, not merely re-stubbed: `apiRequest` is a module-level mock, so its call log
  // accumulates across tests and every "was this route called" assertion would read a neighbour's.
  vi.clearAllMocks();
  RecordingXhr.offered = [];
  RecordingXhr.opened = [];
  RecordingXhr.failAttempt = null;
  RecordingXhr.etagHeader = '"etag"';
  RecordingXhr.attempts = 0;
  RecordingXhr.onSend = null;
  RecordingXhr.emitProgress = false;
  vi.stubGlobal('XMLHttpRequest', RecordingXhr);
});

describe('the server decides the path, and the browser holds no threshold', () => {
  it('takes the multipart path by ROUTE ID when the server plans one', async () => {
    // Without the route-id half, a threshold regression sending every upload down one path passes
    // everything that only asserts the upload succeeded.
    serverPlans(3);

    const result = await upload(PART_SIZE * 3);

    expect(result).toEqual({success: true, data: {key: 'alice/big.bin'}});
    const routes = vi.mocked(apiRequest).mock.calls.map(([route]) => route);
    expect(routes[0]).toBe('objects.upload');
    expect(routes.filter((route) => route === 'objects.uploadPart')).toHaveLength(3);
    expect(routes.at(-1)).toBe('objects.uploadComplete');
  });

  it('mints each part URL immediately before that part is sent, never in a batch', async () => {
    // A batch ages while the parts ahead of it upload, so its last URL is signed long before it is
    // redeemed. Asserted by INTERLEAVING: a batch would show every mint before the first send.
    serverPlans(3);
    const order: string[] = [];
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 3}};
      }
      if (route === 'objects.uploadPart') {
        order.push('mint');
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      return {success: true, data: {key: 'alice/big.bin', etag: 'e'}};
    }) as unknown as typeof apiRequest);
    RecordingXhr.onSend = () => order.push('send');

    await upload(PART_SIZE * 3);

    // The claim is NOT strict alternation — two parts are in flight, so two mints precede the
    // first send. It is that the mints do not all happen up front: a batch would show three mints
    // before any send, and the third part's URL would age while the first two uploaded.
    const firstSend = order.indexOf('send');
    expect(order.slice(0, firstSend)).toEqual(['mint', 'mint']);
    expect(firstSend).toBeLessThan(order.filter((step) => step === 'mint').length);
  });

  it('still clamps the ceiling to S3 single-PUT, which multipart does NOT raise', async () => {
    // Multipart would technically permit 5 TiB. Not raising it is a product decision about cost
    // and blast radius, and this is what stops it drifting upward by accident.
    const result = await upload(maxUploadBytes() + 1);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('TooLarge');
    expect(apiRequest).not.toHaveBeenCalled();
  });
});

describe('aggregate progress', () => {
  it('reports an INTERMEDIATE value across a part boundary, driven by a RETRY', async () => {
    // A boundary crossed WITHOUT a failure passes under all three implementations — running sum,
    // last-value-wins and per-part max — so it cannot be the test that pins this. The retry is
    // what separates them: last-value-wins would drop the retried part's contribution to near
    // zero and the bar would FALL.
    serverPlans(3);
    RecordingXhr.failAttempt = 2;
    RecordingXhr.emitProgress = true;
    const seen: number[] = [];

    const result = await upload(PART_SIZE * 3, {onProgress: (loaded) => seen.push(loaded)});

    expect(result.success).toBe(true);
    const total = PART_SIZE * 3;
    const intermediate = seen.filter((loaded) => loaded > PART_SIZE && loaded < total);
    expect(intermediate.length).toBeGreaterThan(0);
    // A running sum over-reports: with every event added rather than maxed, the parts alone
    // exceed the total long before the upload ends, and only the clamp hides it.
    const unclamped = seen.filter((loaded) => loaded > total);
    expect(unclamped).toEqual([]);
  });

  it('never goes BACKWARDS when a part is retried', async () => {
    // The concrete defect: with parts in flight and one failing near its end, last-value-wins
    // takes the aggregate down as the retry's first event arrives.
    serverPlans(3);
    RecordingXhr.failAttempt = 2;
    RecordingXhr.emitProgress = true;
    const seen: number[] = [];

    await upload(PART_SIZE * 3, {onProgress: (loaded) => seen.push(loaded)});

    // The positive control: without events to compare, `drops` is empty for the wrong reason.
    expect(seen.length).toBeGreaterThan(4);
    const drops = seen.filter((loaded, index) => index > 0 && loaded < seen[index - 1]);
    expect(drops).toEqual([]);
  });

  it('never reports more than the total', async () => {
    serverPlans(3);
    RecordingXhr.emitProgress = true;
    RecordingXhr.onSend = (xhr) => xhr.fireProgress(PART_SIZE * 10);
    const seen: number[] = [];

    await upload(PART_SIZE * 3, {onProgress: (loaded) => seen.push(loaded)});

    expect(Math.max(...seen)).toBe(PART_SIZE * 3);
  });
});

describe('a failed part is retried, and only that part', () => {
  it('re-sends ONE part rather than the whole file', async () => {
    // The capability this spec exists to restore. Counted in BYTES: a request count cannot tell a
    // re-sent part from a re-sent file.
    serverPlans(3);
    RecordingXhr.failAttempt = 2;

    const result = await upload(PART_SIZE * 3);

    expect(result.success).toBe(true);
    // Three parts plus ONE retried part — not three plus three.
    expect(RecordingXhr.offered).toEqual([PART_SIZE, PART_SIZE, PART_SIZE, PART_SIZE]);
    expect(RecordingXhr.offered.reduce((a, b) => a + b, 0)).toBe(PART_SIZE * 4);
  });

  it('RE-MINTS the URL on every attempt rather than reusing the failed one', async () => {
    // Forced, not chosen: a part is sized to use half its window, so a second attempt on the same
    // URL starts with half the window already spent and a third could not finish at all. Reusing
    // it would reintroduce the tail-403 on the path built to remove it.
    serverPlans(2);
    RecordingXhr.failAttempt = 1;

    await upload(PART_SIZE * 2);

    const mints = vi.mocked(apiRequest).mock.calls.filter(([route]) => route === 'objects.uploadPart');
    // Two parts, one of which was attempted twice.
    expect(mints).toHaveLength(3);
  });

  it('fails the file once a part exhausts its retries, and says nothing was saved', async () => {
    serverPlans(1);
    // Every attempt fails: the first plus PART_RETRIES more.
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
    RecordingXhr.onSend = null;
    let attempt = 0;
    RecordingXhr.failAttempt = -1;
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends RecordingXhr {
        send(body: Blob) {
          attempt += 1;
          RecordingXhr.offered.push(body.size);
          queueMicrotask(() => this['handlers'].get('error')?.());
        }
      }
    );

    const result = await upload(PART_SIZE);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadPartsExhausted');
    expect(attempt).toBe(1 + PART_RETRIES);
    // True of multipart in a way it is not of a single PUT: nothing was assembled.
    expect(toUserText(result.error)).toContain('nothing was saved');
  });

  it('abandons the upload when a part finally fails, so its parts are not left billing', async () => {
    serverPlans(1);
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends RecordingXhr {
        send() {
          queueMicrotask(() => this['handlers'].get('error')?.());
        }
      }
    );

    await upload(PART_SIZE);

    const routes = vi.mocked(apiRequest).mock.calls.map(([route]) => route);
    expect(routes).toContain('objects.uploadAbort');
    expect(routes).not.toContain('objects.uploadComplete');
  });
});

describe('the ETag round trip', () => {
  it('fails with a NAMED code when a part ETag is absent, rather than completing with a null', async () => {
    // FR-007's CORS regression. `getResponseHeader` answers null rather than throwing, so without
    // this check the assembly request carries nulls and S3 answers an error naming none of it.
    serverPlans(2);
    RecordingXhr.etagHeader = null;

    const result = await upload(PART_SIZE * 2);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadUnverifiable');
    const routes = vi.mocked(apiRequest).mock.calls.map(([route]) => route);
    expect(routes).not.toContain('objects.uploadComplete');
  });

  it('carries each part ETag to the assembly, stripped of S3 quotes', async () => {
    serverPlans(2);

    await upload(PART_SIZE * 2);

    const complete = vi.mocked(apiRequest).mock.calls.find(([route]) => route === 'objects.uploadComplete');
    const body = (complete?.[1] as {body: {parts: {partNumber: number; etag: string}[]}}).body;
    expect(body.parts).toEqual([
      {partNumber: 1, etag: 'etag'},
      {partNumber: 2, etag: 'etag'}
    ]);
  });
});

describe('cancel', () => {
  it('aborts the upload WITHOUT the caller signal, so the abort itself is not aborted', async () => {
    // The cancel path is entered BECAUSE the signal fired, so passing it to the abort call aborts
    // the abort — leaving the upload to the seven-day sweep for a cancel the user watched succeed.
    serverPlans(3);
    const controller = new AbortController();
    RecordingXhr.onSend = () => controller.abort();

    const result = await upload(PART_SIZE * 3, {signal: controller.signal});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Cancelled');
    const abort = vi.mocked(apiRequest).mock.calls.find(([route]) => route === 'objects.uploadAbort');
    expect(abort).toBeDefined();
    expect((abort?.[1] as {signal?: AbortSignal}).signal).toBeUndefined();
  });
});

describe('the part-concurrency budget', () => {
  it('states its PRODUCT with the file limit, not the factor alone', async () => {
    // The budget is the browser's own per-origin connection limit, and the number that has to fit
    // under it is the PRODUCT: three files each running two parts is six concurrent transfers.
    // `UPLOAD_CONCURRENCY` bounds files; this bounds parts within one file; neither alone is the
    // quantity a browser enforces.
    const BROWSER_CONNECTIONS_PER_ORIGIN = 6;

    expect(PART_CONCURRENCY).toBe(2);
    expect(UPLOAD_CONCURRENCY * PART_CONCURRENCY).toBe(BROWSER_CONNECTIONS_PER_ORIGIN);
  });

  it('states the makespan its retry count is budgeted against', async () => {
    // Each attempt RE-MINTS, so each gets a full window and the constraint is not expiry — it is
    // how long one part may take before the upload is worse than starting over. The server's part
    // size and its slowest supported uplink are what set it; both are stated here because the
    // browser deliberately holds neither.
    const SERVER_PART_BYTES = 112_500_000;
    const SERVER_MIN_UPLINK_BYTES_PER_SEC = 250_000;

    const worstCaseSeconds = ((1 + PART_RETRIES) * SERVER_PART_BYTES) / SERVER_MIN_UPLINK_BYTES_PER_SEC;

    expect(PART_RETRIES).toBe(2);
    expect(worstCaseSeconds).toBe(1350);
  });
});

describe('a create answer the chosen branch cannot use', () => {
  it('answers a named code rather than crashing on a missing member', async () => {
    // The generated type is one object with optional members and a discriminant that narrows
    // nothing else, so every member the branch needs is checked at runtime.
    vi.mocked(apiRequest).mockResolvedValue({
      success: true,
      data: {mode: 'multipart'}
    } as unknown as Awaited<ReturnType<typeof apiRequest>>);

    const result = await upload(PART_SIZE * 3);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadPlanUnusable');
  });

  it('answers the same named code for a single answer with no url', async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      success: true,
      data: {mode: 'single'}
    } as unknown as Awaited<ReturnType<typeof apiRequest>>);

    const result = await upload(10);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadPlanUnusable');
  });
});

describe('every code this path can produce has an authored sentence', () => {
  it('never resolves one to the generic contact-the-administrator line', () => {
    // Extends the walk the single-PUT path already ships. A code with no rule is not a crash — it
    // is the generic sentence, which is right for an unknown code and wrong for a known one.
    const generic = 'Something went wrong. Contact the Administrator.';
    // Authored codes: the rule supplies the whole sentence, so a bare code is the real input.
    const authored = [
      'UploadPartsExhausted',
      'UploadUnverifiable',
      'UploadPlanUnusable',
      'UploadLinkExpired',
      'UploadFailed',
      'Cancelled'
    ];
    // Passthrough codes carry their own text — they name the file or the limit — so a bare code
    // has nothing to pass through and would resolve generic for the right reason. Walked with the
    // message they actually travel with.
    const passthrough = [
      {code: 'Collision', message: '"big.bin" already exists.'},
      {code: 'TooLarge', message: 'File exceeds the maximum upload size of 5 bytes.'}
    ];

    expect(authored.filter((code) => toUserText({code}) === generic)).toEqual([]);
    expect(passthrough.filter((error) => toUserText(error) === generic)).toEqual([]);
  });
});
