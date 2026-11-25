export interface FrameResult {
    png: Uint8Array;
    ms: number;
    hash: string;
}
export interface ViewResult extends FrameResult {
    meta: Record<string, unknown> | null;
}
export declare function backendJson(port: number, path: string, timeoutMs?: number, init?: RequestInit): Promise<Record<string, unknown>>;
/**
 * Parse a backend response (fixed in v0.8.9): the backend answers in two shapes -
 *   1) normal routes: the whole body is one JSON document;
 *   2) streaming routes (/headless /worker /txn /preset): NDJSON, **one line every 15 s** {"heartbeat":true,...}, and the result is the last line.
 * The old implementation ran JSON.parse on the whole body, so any call **longer than 15 s** threw Extra data -> callers saw only exit=undefined (the child had actually finished).
 * Now: on parse failure it walks backwards line by line to the last non-heartbeat JSON, and records the heartbeat count in __heartbeats for the tool layer to report.
 */
export declare function parseBackendBody(body: unknown): Record<string, unknown>;
/**
 * Every write operation goes through this: it adds the holder automatically (for lease gating) and keeps the HTTP status code so 409 can be recognized.
 *
 * v0.9.3 (important): **the timer must live until the body is fully read**.
 * The old version was withTimeout(fetch) -> fetch resolved as soon as the **response headers** arrived (streaming routes such as /headless send headers immediately + a heartbeat every 15 s),
 * so the timeout budget only covered "waiting for headers" and the following r.text() waited forever - the client wait window was effectively useless,
 * and as soon as the outer run_code deadline hit, the whole result was dropped (exactly the reported symptom).
 * Now text() runs under the same AbortController: when the deadline hits it aborts -> fetch and the body read both throw AbortError.
 */
export declare function backendPost(port: number, path: string, body: unknown, timeoutMs?: number): Promise<Record<string, unknown>>;
/** v0.9.1: tolerant tool arguments - the harness's type:"json" sometimes delivers an object as a **string** (both forms were observed in the same session),
 *  and the old typeof x === 'object' check silently dropped the argument (showed up as "parameters had no effect yet ok:true", very hard to debug). */
export declare function jsonPayload(v: unknown): Record<string, unknown>;
/** Split a string such as "--flag \"a b\" c" into argv (paired quotes do not act as separators; fixes the headless args quoting issue in v0.8.9)
 *  v0.9.1: arrays pass straight through (the old String([...]) turned them into a single bracketed token such as "[delta]") */
export declare function splitArgs(s: unknown): string[];
/** 409 leased -> give the model a sentence it can act on (instead of dumping raw JSON) */
export declare function leasedText(r: unknown): string | undefined;
/** Fetch one PNG frame (with timing); full=true uses screenshot_area (whole window/area) */
export declare function fetchFrame(port: number, size: number, full?: boolean, area?: number): Promise<FrameResult>;
/** Custom-view render: POST /view (view.py) - does not touch objects or the user's viewport */
export declare function fetchView(port: number, spec: unknown, timeoutMs?: number): Promise<ViewResult>;
export declare function numTriple(v: unknown): number[] | undefined;
