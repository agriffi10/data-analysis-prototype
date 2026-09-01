import {beforeEach, describe, expect, it, vi} from 'vitest';
import {apiRequest} from '../../lib/apiClient';
import {toUserText} from '../../lib/errorMessages';
import {uploadFile} from './fileBrowser.service';
import {KEEP_SPECIFIC_CODES, PART_CONCURRENCY, PART_RETRIES} from './multipartUpload';
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
  /** Every slice offered to the transport, as `(offset, size)` — NOT size alone. */
  static offered: {offset: number; size: number}[] = [];
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
    RecordingXhr.offered.push({offset: (body as unknown as {offset: number}).offset, size: body.size});
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

/**
 * A blob whose `slice` reports real sizes AND remembers where it was cut from.
 *
 * The offset is what makes the part arithmetic checkable. A fixture recording only sizes satisfies
 * "count the bytes offered to the transport" literally while leaving `(partNumber - 1) * partSize`
 * wholly unpinned — measured: replacing that expression with `0`, so every part uploads part one's
 * bytes, passed the entire 2322-test suite. S3 accepts it too, because the ETags are genuine, so
 * the user is told their upload worked while the stored object is one part repeated.
 */
function blob(size: number, offset = 0): Blob {
  const made = {
    size,
    offset,
    type: 'application/octet-stream',
    slice: (start: number, end: number) => blob(Math.max(0, end - start), offset + start)
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
    // Belt and braces rather than the load-bearing half: `emit()` clamps to the total, so this
    // cannot fail while the clamp exists. What actually separates a running sum from a per-part
    // max is the monotonicity test below.
    expect(seen.filter((loaded) => loaded > total)).toEqual([]);
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
    // Three parts plus ONE retried part — not three plus three. And each slice is taken from its
    // OWN offset, which is what stops every part shipping part one's bytes.
    const sizes = RecordingXhr.offered.map((slice) => slice.size);
    expect(sizes).toEqual([PART_SIZE, PART_SIZE, PART_SIZE, PART_SIZE]);
    expect(sizes.reduce((a, b) => a + b, 0)).toBe(PART_SIZE * 4);
    // Parts 1, 2 and 3 cover the file exactly once; the retry re-sends the SAME offset, not a new
    // one — a retry reading the wrong slice would also pass a pure size count.
    expect(new Set(RecordingXhr.offered.map((slice) => slice.offset))).toEqual(new Set([0, PART_SIZE, PART_SIZE * 2]));
    expect(RecordingXhr.offered.filter((slice) => slice.offset === PART_SIZE)).toHaveLength(2);
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
          RecordingXhr.offered.push({offset: (body as unknown as {offset: number}).offset, size: body.size});
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

describe('the assembly gets its parts in S3 order, not in the order they finished', () => {
  it('numbers the parts ascending when a RETRY makes a later part finish first', async () => {
    // S3 refuses an out-of-order part list with `InvalidPartOrder`, which the API maps to
    // "the uploaded parts did not assemble" — a user-visible failure of an upload that worked.
    //
    // **The shape matters and most shapes hide it.** With two workers, part 1 failing once means
    // worker 2 takes part 3 while worker 1 retries part 2, so part 3 SETTLES before part 2 — and
    // pushing in completion order ships [1, 3, 2]. With `partCount: 3, failAttempt: 2` (the shape
    // the re-send test uses) completion order happens to equal index order, which is why writing
    // by index looked covered while a faithful `parts.push` mutation passed all 2333 tests.
    serverPlans(3);
    RecordingXhr.failAttempt = 1;

    const result = await upload(PART_SIZE * 3);

    expect(result.success).toBe(true);
    const complete = vi.mocked(apiRequest).mock.calls.find(([route]) => route === 'objects.uploadComplete');
    const body = (complete?.[1] as {body: {parts: {partNumber: number}[]}}).body;
    expect(body.parts.map((part) => part.partNumber)).toEqual([1, 2, 3]);
    // The positive control: without a retry the ordering is incidental, so prove one happened.
    expect(RecordingXhr.offered).toHaveLength(4);
  });

  it('leaves no hole in the list when a part is retried', async () => {
    // A sparse array would serialise a `null` into the assembly body, which S3 rejects with a
    // message naming none of this.
    serverPlans(4);
    RecordingXhr.failAttempt = 2;

    await upload(PART_SIZE * 4);

    const complete = vi.mocked(apiRequest).mock.calls.find(([route]) => route === 'objects.uploadComplete');
    const body = (complete?.[1] as {body: {parts: unknown[]}}).body;
    expect(body.parts).toHaveLength(4);
    expect(body.parts.filter((part) => part === null || part === undefined)).toEqual([]);
  });
});

describe('an upload that fails to assemble does not strand its parts', () => {
  /** Answers a multipart plan, then fails the assembly with the given code. */
  function assemblyFails(code: string) {
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 2}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      if (route === 'objects.uploadComplete') return {success: false, error: {message: 'no', code}};
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
  }

  it('abandons the upload when the assembly COLLIDES, which is the common way to get here', async () => {
    // The user is about to be offered Overwrite or Rename, and both re-enter with a NEW upload id.
    // Without the abort the first attempt's parts are stranded — a whole file's worth of multipart
    // storage, billed until the bucket's seven-day sweep, for an interruption nobody saw.
    assemblyFails('Conflict');

    const result = await upload(PART_SIZE * 2);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Collision');
    expect(vi.mocked(apiRequest).mock.calls.filter(([route]) => route === 'objects.uploadAbort')).toHaveLength(1);
  });

  it('abandons the upload when the assembly fails for any other reason', async () => {
    assemblyFails('InternalError');

    await upload(PART_SIZE * 2);

    expect(vi.mocked(apiRequest).mock.calls.filter(([route]) => route === 'objects.uploadAbort')).toHaveLength(1);
  });
});

describe('a cancel is reported as a cancel, wherever it lands', () => {
  it('does not send a part whose cancel arrived while its URL was being minted', async () => {
    // `addEventListener('abort')` on an already-fired signal never runs, so a listener attached
    // after the mint is attached to a spent signal: the bytes go out and, with nothing calling
    // `xhr.abort()`, the user's Cancelled waits for a whole part to finish uploading.
    const controller = new AbortController();
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 2}};
      }
      if (route === 'objects.uploadPart') {
        controller.abort();
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);

    const result = await upload(PART_SIZE * 2, {signal: controller.signal});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Cancelled');
    expect(RecordingXhr.offered).toEqual([]);
  });

  it('says Cancelled, not "took too long", when the cancel lands on the assembly call', async () => {
    // `apiRequest` maps a caller abort to `RequestTimeout`, so without recognising the abort first
    // the user is told their own cancel timed out.
    const controller = new AbortController();
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      if (route === 'objects.uploadComplete') {
        controller.abort();
        return {success: false, error: {message: 'aborted', code: 'RequestTimeout'}};
      }
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);

    const result = await upload(PART_SIZE, {signal: controller.signal});

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('Cancelled');
    expect(vi.mocked(apiRequest).mock.calls.filter(([route]) => route === 'objects.uploadAbort')).toHaveLength(1);
  });

  it('resolves the cancel WITHOUT waiting for the abort to answer', async () => {
    // FR-004 AC3. A stalled connection is a leading reason someone cancels, so an awaited abort
    // holds the queue row on "Uploading" for the client's full timeout — a control that stops
    // working exactly when it is wanted.
    const controller = new AbortController();
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 2}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      // Never answers, like an abort against the connection that caused the cancel.
      if (route === 'objects.uploadAbort') return new Promise(() => {});
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
    RecordingXhr.onSend = () => controller.abort();

    const raced = await Promise.race([
      upload(PART_SIZE * 2, {signal: controller.signal}),
      new Promise((resolve) => setTimeout(() => resolve('STILL PENDING'), 50))
    ]);

    expect(raced).not.toBe('STILL PENDING');
    expect((raced as {error: {code: string}}).error.code).toBe('Cancelled');
  });
});

describe('a refusal keeps the sentence that tells the user what to do', () => {
  /** Fails every part PUT with the given status. */
  function partsRefused(status: number, expiresAt: string) {
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') return {success: true, data: {url: 'https://signed/part', expiresAt}};
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends RecordingXhr {
        status = status;
      }
    );
  }

  it('reports a DENIAL as a denial, and does not retry it', async () => {
    // Retrying past a denial spends a whole part's bytes per attempt to be refused again — at the
    // server's part size, hundreds of megabytes to be told the same thing three times.
    partsRefused(403, '2999-01-01T00:00:00Z');

    const result = await upload(PART_SIZE);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('AccessDenied');
    expect(RecordingXhr.offered).toHaveLength(1);
  });

  it('reports an EXPIRED link as an expiry, after retrying — which is what a re-mint fixes', async () => {
    partsRefused(403, '2020-01-01T00:00:00Z');

    const result = await upload(PART_SIZE);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadLinkExpired');
    expect(RecordingXhr.offered).toHaveLength(1 + PART_RETRIES);
  });
});

describe('a plan that cannot cover the file is refused, not uploaded', () => {
  /** Answers a multipart plan with the given arithmetic, whatever the body's real size. */
  function plans(partSize: number, partCount: number) {
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize, partCount}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      return {success: true, data: {key: 'alice/big.bin', etag: 'e'}};
    }) as unknown as typeof apiRequest);
  }

  // Every one of these is caught by the PRODUCT clause — `0 * 3` and `5 * 0` are both under the
  // file's size, so the `< 1` clauses are defence in depth rather than what these exercise. Named
  // for the server answer each represents, not for the clause each happens to hit.
  it.each([
    ['parts that do not reach the end of the file', 5, 3, 20],
    ['no parts at all', 5, 0, 20],
    ['parts of no size', 0, 3, 20]
  ])('refuses a plan with %s rather than truncating', async (_why, partSize, partCount, size) => {
    // The ONE bad answer that fails silently AND successfully: every part uploads, every ETag is
    // genuine, S3 assembles what it was given, and the user is told their file is saved while what
    // is stored is a prefix of it. The bar cannot show it either — the aggregate clamps to the
    // file's size and the queue pins a finished row to 100%.
    plans(partSize, partCount);

    const result = await upload(size);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadPlanUnusable');
    expect(RecordingXhr.offered).toEqual([]);
  });

  it('accepts a plan whose last part is short, which is the ordinary case', async () => {
    // The guard must not refuse the arithmetic the server actually produces: 3 parts of 5 covers
    // a 12-byte file with a 2-byte last part.
    plans(PART_SIZE, 3);

    const result = await upload(12);

    expect(result.success).toBe(true);
    expect(RecordingXhr.offered.map((slice) => slice.size)).toEqual([PART_SIZE, PART_SIZE, 2]);
  });
});

describe('a code that survives the retry loop is one a user can act on', () => {
  /** Fails every part MINT with the given code, which is the path that reaches the keep list. */
  function mintRefused(code: string) {
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') return {success: false, error: {message: 'no', code}};
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
  }

  it('is exactly this set, stated LITERALLY rather than read from the module', () => {
    // Derived cases cannot see a SHRINK: `it.each(KEEP_SPECIFIC_CODES)` runs one case per entry,
    // so deleting three entries deletes three cases and the suite still passes — measured, twice.
    // The literal is what makes a removal fail rather than disappear.
    expect(KEEP_SPECIFIC_CODES).toEqual(['AccessDenied', 'UploadLinkExpired', 'Cancelled', 'SessionExpired']);
  });

  it.each(['AccessDenied', 'UploadLinkExpired', 'SessionExpired'])(
    'keeps %s rather than flattening it to the generic exhausted code',
    async (code) => {
      // Listed literally, for the same reason as above. Each entry needs its own case: dropping
      // one is invisible while a sibling still exercises the return.
      mintRefused(code);

      const result = await upload(PART_SIZE);

      expect(result.success).toBe(false);
      if (result.success) return;
      expect(result.error.code).toBe(code);
      // No bytes were spent: the mint never produced a URL to send to.
      expect(RecordingXhr.offered).toEqual([]);
    }
  );

  it('flattens a code that is NOT on the list, so the list is doing the work', async () => {
    // The other half. Without this, a list of every code would pass the cases above.
    mintRefused('RateLimited');

    const result = await upload(PART_SIZE);

    expect(result.success).toBe(false);
    if (result.success) return;
    expect(result.error.code).toBe('UploadPartsExhausted');
  });

  it('gives every code on the list an authored sentence', () => {
    // Derived here DELIBERATELY, and it is the safe direction: a code ADDED to the keep list is a
    // code this path can now surface, and this walks whatever the list holds. The literal above is
    // what catches a removal; this catches an addition with no wording. Both directions, two
    // assertions.
    const generic = 'Something went wrong. Contact the Administrator.';
    const unruled = KEEP_SPECIFIC_CODES.filter((code) => toUserText({code}) === generic);

    expect(KEEP_SPECIFIC_CODES.length).toBeGreaterThan(0);
    expect(unruled).toEqual([]);
  });
});

describe('no failure path waits on the discard', () => {
  /** A plan whose assembly fails, and whose abort never answers. */
  function assemblyFailsAndAbortHangs(code: string) {
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      if (route === 'objects.uploadComplete') return {success: false, error: {message: 'no', code}};
      if (route === 'objects.uploadAbort') return new Promise(() => {});
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
  }

  it.each([
    ['a collision', 'Conflict', 'Collision'],
    ['any other assembly failure', 'InternalError', 'InternalError']
  ])('answers %s without waiting for the abort to come back', async (_why, given, expected) => {
    // The queue holds the row on "Uploading" until this resolves, and the collision prompt only
    // appears afterwards — so an awaited discard leaves the user watching a progress bar for the
    // client's full timeout, on the arm they meet most often. The cancel path learned this first;
    // the failure paths have the same caller and the same consequence.
    assemblyFailsAndAbortHangs(given);

    const raced = await Promise.race([
      upload(PART_SIZE),
      new Promise((resolve) => setTimeout(() => resolve('STILL PENDING'), 50))
    ]);

    expect(raced).not.toBe('STILL PENDING');
    expect((raced as {error: {code: string}}).error.code).toBe(expected);
  });

  it('answers an exhausted part without waiting for the abort either', async () => {
    // The THIRD exit. Each of the three abandons, so each has to be covered separately — a test
    // driving only the assembly arm leaves the part-failure arm free to block, which is what
    // planting `await` on it showed.
    vi.mocked(apiRequest).mockImplementation((async (route: string) => {
      if (route === 'objects.upload') {
        return {success: true, data: {mode: 'multipart', uploadId: 'up-1', partSize: PART_SIZE, partCount: 1}};
      }
      if (route === 'objects.uploadPart') {
        return {success: true, data: {url: 'https://signed/part', expiresAt: '2999-01-01T00:00:00Z'}};
      }
      if (route === 'objects.uploadAbort') return new Promise(() => {});
      return {success: true, data: {key: 'alice/big.bin'}};
    }) as unknown as typeof apiRequest);
    vi.stubGlobal(
      'XMLHttpRequest',
      class extends RecordingXhr {
        send() {
          queueMicrotask(() => this['handlers'].get('error')?.());
        }
      }
    );

    const raced = await Promise.race([
      upload(PART_SIZE),
      new Promise((resolve) => setTimeout(() => resolve('STILL PENDING'), 50))
    ]);

    expect(raced).not.toBe('STILL PENDING');
    expect((raced as {error: {code: string}}).error.code).toBe('UploadPartsExhausted');
  });
});
